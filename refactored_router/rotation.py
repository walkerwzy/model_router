import json
from datetime import date
from typing import Dict, List, Optional
from .settings import config


class RotationService:
    """多提供商批量轮换。

    语义：游标指向"当前值日"的提供商，它连续成功服务 quota 次后，
    游标切到下一个提供商。失败不消耗配额（由请求级故障转移兜底）。

    状态尽力持久化到 DATA_DIR；Vercel 多实例/冷启动会丢状态，
    按约定接受近似轮换。所有操作都是同步短路径，适配单线程 asyncio。
    """

    def __init__(self):
        self.cursor = 0  # 当前值日提供商在 config.PROVIDERS 中的下标
        self.used = 0    # 当前轮次已消耗的成功调用数
        self._load()

    def _providers(self) -> List[Dict]:
        return config.PROVIDERS

    def _load(self):
        try:
            if config.ROTATION_FILE.exists():
                with open(config.ROTATION_FILE, "r") as f:
                    data = json.load(f)
                if data.get("date") == str(date.today()) and self._providers():
                    n = len(self._providers())
                    self.cursor = int(data.get("cursor", 0)) % n
                    self.used = int(data.get("used", 0))
                else:
                    self.cursor, self.used = 0, 0
            else:
                self.cursor, self.used = 0, 0
        except Exception:
            self.cursor, self.used = 0, 0

    def _save(self):
        try:
            with open(config.ROTATION_FILE, "w") as f:
                json.dump(
                    {"date": str(date.today()), "cursor": self.cursor, "used": self.used},
                    f,
                )
        except Exception:
            pass

    def current(self) -> Optional[Dict]:
        providers = self._providers()
        if not providers:
            return None
        return providers[self.cursor % len(providers)]

    def advance(self):
        """游标前进一位并开启新轮次（放弃当前轮次剩余配额）"""
        providers = self._providers()
        if not providers:
            return
        self.cursor = (self.cursor + 1) % len(providers)
        self.used = 0
        self._save()

    def record_success(self, provider_name: str):
        """成功调用记账：仅当前值日提供商消耗配额，满额则轮换。

        故障转移期间其他提供商的成功不占用当前轮次配额。
        非流式在收到完整响应后调用；流式在流正常结束后调用。
        """
        cur = self.current()
        if not cur or cur["name"] != provider_name:
            return
        quota = cur.get("quota", config.ROTATION_QUOTA)
        self.used += 1
        if self.used >= quota:
            self.advance()
        else:
            self._save()

    def get_state(self) -> Dict:
        cur = self.current()
        return {
            "current": cur["name"] if cur else None,
            "used": self.used,
            "quota": cur.get("quota", config.ROTATION_QUOTA) if cur else 0,
        }


rotation_service = RotationService()
