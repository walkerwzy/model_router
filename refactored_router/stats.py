import json
import time
from datetime import date
from typing import Dict, List, Optional
from .settings import config
from .schema import CallRecord

# 熔断器配置
CIRCUIT_FAIL_THRESHOLD = 3  # 连续失败N次触发熔断
CIRCUIT_RESET_TIMEOUT = 30  # 熔断后30秒尝试恢复


class StatsService:
    def __init__(self):
        self.stats = {}
        self.model_limits = {}
        # 熔断器状态: {model_name: {open_time: float, failures: int}}
        self.circuit_breakers: Dict[str, Dict] = {}

        for model in config.MODELS:
            self.model_limits[model["name"]] = model.get("estimated_limit", 50)
        self.load_all()

    def load_all(self):
        try:
            if config.STATS_FILE.exists():
                with open(config.STATS_FILE, "r") as f:
                    data = json.load(f)
                    if data.get("date") == str(date.today()):
                        self.stats = data.get("stats", {})
                    else:
                        self.reset_daily_stats()
            else:
                self.reset_daily_stats()
        except:
            self.reset_daily_stats()

        for model in config.MODELS:
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
            with open(config.STATS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def reset_daily_stats(self):
        self.stats = {}
        for model in config.MODELS:
            self._init_model_stat(model["name"])
        self.save_stats()

    def is_circuit_open(self, model_name: str) -> bool:
        """检查熔断器是否打开"""
        cb = self.circuit_breakers.get(model_name)
        if not cb:
            return False

        # 检查是否超时需要重试
        if time.time() - cb.get("open_time", 0) > CIRCUIT_RESET_TIMEOUT:
            cb["failures"] = 0  # 重置失败计数
            cb["open_time"] = 0
            return False

        return cb.get("failures", 0) >= CIRCUIT_FAIL_THRESHOLD

    def record_failure(self, model_name: str):
        """记录失败，触发熔断"""
        if model_name not in self.circuit_breakers:
            self.circuit_breakers[model_name] = {"failures": 0, "open_time": 0}

        cb = self.circuit_breakers[model_name]
        cb["failures"] += 1
        if cb["failures"] >= CIRCUIT_FAIL_THRESHOLD:
            cb["open_time"] = time.time()

    def record_success(self, model_name: str):
        """记录成功，重置熔断器"""
        if model_name in self.circuit_breakers:
            self.circuit_breakers[model_name] = {"failures": 0, "open_time": 0}

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

        self.stats[record.model_name] = st
        self.save_stats()

    def get_available_models(self) -> List[Dict]:
        """获取当前可用模型，按level优先级排序，排除熔断和限流"""
        available = []
        for model in config.MODELS:
            name = model["name"]
            st = self.stats.get(name, {})

            # 排除限流和熔断
            if st.get("is_limited", False):
                continue
            if self.is_circuit_open(name):
                continue

            model_with_stats = model.copy()
            model_with_stats["_calls"] = st.get("calls", 0)
            model_with_stats["_level"] = model.get("level", 999)
            available.append(model_with_stats)

        available.sort(key=lambda x: (x["_level"], x["_calls"]))
        return available

    def get_snapshot(self) -> Dict:
        return {"stats": self.stats, "limits": self.model_limits}
