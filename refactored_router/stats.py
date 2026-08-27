import json
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from .settings import config
from .schema import CallRecord

# 熔断器配置
CIRCUIT_FAIL_THRESHOLD = 3  # 连续失败N次触发熔断
CIRCUIT_RESET_TIMEOUT = 30  # 熔断后30秒尝试恢复


class StatsService:
    """调用统计/熔断/限流记账。

    参数化后同时服务两条链路：
    - stats_service: 老路由（/old），行为与改造前完全一致
    - provider_stats_service: 新多提供商路由，额外带限流冷却
    """

    def __init__(
        self,
        models: List[Dict],
        stats_file: Path,
        limited_cooldown: Optional[int] = None,
    ):
        self.models = models
        self.stats_file = Path(stats_file)
        # 限流冷却秒数：被标记限流后经过该时长恢复可用；None=老行为（限流后直到重启/跨天才解除）
        self.limited_cooldown = limited_cooldown
        self.stats = {}
        self.model_limits = {}
        # 熔断器状态: {name: {open_time: float, failures: int}}
        self.circuit_breakers: Dict[str, Dict] = {}

        for model in self.models:
            self.model_limits[model["name"]] = model.get("estimated_limit", 50)
        self.load_all()

    def load_all(self):
        try:
            if self.stats_file.exists():
                with open(self.stats_file, "r") as f:
                    data = json.load(f)
                    if data.get("date") == str(date.today()):
                        self.stats = data.get("stats", {})
                    else:
                        self.reset_daily_stats()
            else:
                self.reset_daily_stats()
        except:
            self.reset_daily_stats()

        for model in self.models:
            if model["name"] not in self.stats:
                self._init_model_stat(model["name"])

    def _init_model_stat(self, name: str):
        self.stats[name] = {
            "calls": 0,
            "success_calls": 0,
            "error_calls": 0,
            "total_response_time": 0,
            "last_error": None,
            "is_limited": False,
        }

    def save_stats(self):
        try:
            data = {"date": str(date.today()), "stats": self.stats}
            with open(self.stats_file, "w") as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def reset_daily_stats(self):
        self.stats = {}
        for model in self.models:
            self._init_model_stat(model["name"])
        self.save_stats()

    def is_circuit_open(self, name: str) -> bool:
        """检查熔断器是否打开"""
        cb = self.circuit_breakers.get(name)
        if not cb:
            return False

        # 检查是否超时需要重试
        if time.time() - cb.get("open_time", 0) > CIRCUIT_RESET_TIMEOUT:
            cb["failures"] = 0  # 重置失败计数
            cb["open_time"] = 0
            return False

        return cb.get("failures", 0) >= CIRCUIT_FAIL_THRESHOLD

    def record_failure(self, name: str):
        """记录失败，触发熔断"""
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = {"failures": 0, "open_time": 0}

        cb = self.circuit_breakers[name]
        cb["failures"] += 1
        if cb["failures"] >= CIRCUIT_FAIL_THRESHOLD:
            cb["open_time"] = time.time()

    def record_success(self, name: str):
        """记录成功，重置熔断器"""
        if name in self.circuit_breakers:
            self.circuit_breakers[name] = {"failures": 0, "open_time": 0}

    def mark_limited(self, name: str):
        """标记限流并记录时间（供冷却机制使用）"""
        if name not in self.stats:
            self._init_model_stat(name)
        st = self.stats[name]
        st["is_limited"] = True
        st["limited_since"] = time.time()
        self.save_stats()

    def _cooldown_expired(self, st: Dict) -> bool:
        if self.limited_cooldown is None:
            return False
        since = st.get("limited_since", 0)
        return bool(since) and (time.time() - since) > self.limited_cooldown

    def is_available(self, name: str) -> bool:
        """单项可用性：未限流（或冷却已过）且未熔断"""
        st = self.stats.get(name, {})

        if st.get("is_limited", False):
            if self._cooldown_expired(st):
                st["is_limited"] = False
                st["limited_since"] = 0
                self.save_stats()
            else:
                return False
        if self.is_circuit_open(name):
            return False
        return True

    def record_call(self, record: CallRecord):
        if record.model_name not in self.stats:
            self.reset_daily_stats()

        st = self.stats[record.model_name]
        st["calls"] += 1
        st["total_response_time"] += record.response_time

        if record.success:
            st["success_calls"] += 1
            self.record_success(record.model_name)
        else:
            st["error_calls"] += 1
            st["last_error"] = record.error_message
            self.record_failure(record.model_name)

            if record.error_message and any(
                x in str(record.error_message).lower()
                for x in ["limit", "quota", "429"]
            ):
                st["is_limited"] = True
                st["limited_since"] = time.time()

        self.stats[record.model_name] = st
        self.save_stats()

    def get_available_models(self) -> List[Dict]:
        """获取当前可用模型，按level优先级排序，排除熔断和限流（老路由语义）"""
        available = []
        for model in self.models:
            name = model["name"]
            if not self.is_available(name):
                continue

            st = self.stats.get(name, {})
            model_with_stats = model.copy()
            model_with_stats["_calls"] = st.get("calls", 0)
            model_with_stats["_level"] = model.get("level", 999)
            available.append(model_with_stats)

        available.sort(key=lambda x: (x["_level"], x["_calls"]))
        return available

    def get_snapshot(self) -> Dict:
        return {"stats": self.stats, "limits": self.model_limits}


class ProviderStatsService(StatsService):
    """新路由统计：修正熔断检查语义。

    原实现中未熔断时 open_time=0，`time.time() - 0 > CIRCUIT_RESET_TIMEOUT`
    恒成立，每次检查都会清零失败计数，导致熔断永远无法触发。
    老路由保持原实现不动（/old 行为等价），仅新路由使用修正版。
    """

    def is_circuit_open(self, name: str) -> bool:
        cb = self.circuit_breakers.get(name)
        if not cb:
            return False
        if cb.get("failures", 0) < CIRCUIT_FAIL_THRESHOLD:
            return False
        if time.time() - cb.get("open_time", 0) > CIRCUIT_RESET_TIMEOUT:
            cb["failures"] = 0
            cb["open_time"] = 0
            return False
        return True


stats_service = StatsService(config.MODELS, config.STATS_FILE)
provider_stats_service = ProviderStatsService(
    config.PROVIDERS,
    config.PROVIDER_STATS_FILE,
    limited_cooldown=config.LIMITED_COOLDOWN,
)
