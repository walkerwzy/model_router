import os
import json
from pathlib import Path
from typing import List, Dict


class Settings:
    def __init__(self):
        self.BASE_DIR = Path(__file__).parent

        if os.environ.get("VERCEL"):
            self.DATA_DIR = Path("/tmp/router_data")
        else:
            self.DATA_DIR = self.BASE_DIR / "router_data"

        self.STATS_FILE = self.DATA_DIR / "model_stats.json"
        self.PROVIDER_STATS_FILE = self.DATA_DIR / "provider_stats.json"
        self.ROTATION_FILE = self.DATA_DIR / "rotation_state.json"
        self.CONFIG_FILE = self.BASE_DIR / "config.json"
        self.PROVIDERS_FILE = self.BASE_DIR / "providers.json"
        self.ENV_FILE = self.BASE_DIR / ".env"

        self.DATA_DIR.mkdir(exist_ok=True)

        self._load_env()
        self.API_KEY = os.getenv("MS_API_KEY", "")
        self.BASE_URL = (
            os.getenv("MS_BASE_URL") or "https://api-inference.modelscope.cn/v1"
        )
        self.TOKEN = os.getenv("TOKEN", "")
        self.PORT = int(os.getenv("PORT", "2166"))
        self.ROUTER_ALIAS = os.getenv("ROUTER_ALIAS", "modelscope-router")

        # ---- 多提供商轮换配置（新路由） ----
        # 每个提供商配置连续成功服务多少次后切换到下一个
        self.ROTATION_QUOTA = int(os.getenv("ROTATION_QUOTA", "5"))
        # 被限流(429)后多少秒允许再试；老路由无此机制
        self.LIMITED_COOLDOWN = int(os.getenv("LIMITED_COOLDOWN", "300"))
        # 启动健康探测开关：默认本地开、Vercel 关（冷启动探测会消耗免费额度）
        probe_env = os.getenv("HEALTH_PROBE", "").strip().lower()
        if probe_env in ("1", "true", "on", "yes"):
            self.HEALTH_PROBE = True
        elif probe_env in ("0", "false", "off", "no"):
            self.HEALTH_PROBE = False
        else:
            self.HEALTH_PROBE = not os.environ.get("VERCEL")

        self.MODELS = self._load_models()
        self.PROVIDERS = self._load_providers()

    def _load_env(self):
        """简单的 .env 解析器，避免引入 python-dotenv 依赖"""
        if not self.ENV_FILE.exists():
            return
        with open(self.ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    def _load_models(self) -> List[Dict]:
        if not self.CONFIG_FILE.exists():
            return []
        with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_providers(self) -> List[Dict]:
        """加载多提供商配置；文件缺失/损坏时降级为空列表（请求将返回 503）"""
        if not self.PROVIDERS_FILE.exists():
            return []
        try:
            with open(self.PROVIDERS_FILE, "r", encoding="utf-8") as f:
                providers = json.load(f)
        except Exception as e:
            print(f"[settings] providers.json 解析失败: {e}")
            return []

        valid = []
        seen = set()
        for p in providers:
            missing = [
                k for k in ("name", "base_url", "model_id", "api_key_env") if not p.get(k)
            ]
            if missing:
                print(f"[settings] 提供商配置缺少字段 {missing}，已跳过: {p.get('name', '?')}")
                continue
            if p["name"] in seen:
                print(
                    f"[settings] 提供商名称重复，已跳过: {p['name']}"
                    "（熔断/限流/轮换均按名称记账，名称必须唯一，同模型多 key 请用不同名称）"
                )
                continue
            seen.add(p["name"])
            p.setdefault("quota", self.ROTATION_QUOTA)
            if not os.getenv(p["api_key_env"]):
                print(
                    f"[settings] 警告: 提供商 {p['name']} 的环境变量 {p['api_key_env']} 未设置，该配置暂不可用"
                )
            valid.append(p)
        return valid


# 单例模式
config = Settings()
