"""BrainManager —— 大脑配置管理与运行时切换（带持久化）"""

from __future__ import annotations
import json, os
import uuid
from typing import Optional
from brain.base import BrainConfig, BaseBrain
from brain.registry import create_brain

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "brain_configs.json")


class BrainManager:
    """管理多份大脑配置，支持运行时切换，配置自动保存到 JSON 文件"""

    def __init__(self):
        self._configs: dict[str, BrainConfig] = {}
        self._active_id: str | None = None
        self._active_brain: BaseBrain | None = None
        self._load()

    # ── 持久化 ────────────────────────────────────
    def _load(self):
        """启动时从文件加载配置"""
        if not os.path.exists(_CONFIG_FILE):
            return
        try:
            with open(_CONFIG_FILE) as f:
                data = json.load(f)
            for c in data.get("configs", []):
                cfg = BrainConfig.from_dict(c)
                self._configs[cfg.id] = cfg
            self._active_id = data.get("active_id")
            if self._active_id and self._active_id in self._configs:
                try:
                    self._active_brain = create_brain(self._configs[self._active_id])
                except Exception:
                    self._active_id = None
        except Exception:
            pass

    def _save(self):
        """配置变更时自动保存到文件"""
        configs = [c.to_dict() for c in self._configs.values()]
        data = {"configs": configs, "active_id": self._active_id}
        os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
        try:
            with open(_CONFIG_FILE, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── 配置管理 ──────────────────────────────────
    def add_config(self, config: BrainConfig) -> str:
        if not config.id:
            config.id = uuid.uuid4().hex[:8]
        self._configs[config.id] = config
        if self._active_id is None:
            self.switch_to(config.id)
        self._save()
        return config.id

    def remove_config(self, brain_id: str) -> bool:
        if brain_id not in self._configs:
            return False
        del self._configs[brain_id]
        if self._active_id == brain_id:
            self._active_id = None
            self._active_brain = None
            if self._configs:
                self.switch_to(next(iter(self._configs)))
        self._save()
        return True

    def get_config(self, brain_id: str) -> BrainConfig | None:
        return self._configs.get(brain_id)

    def list_configs(self) -> list[BrainConfig]:
        return list(self._configs.values())

    # ── 运行时切换 ────────────────────────────────
    def switch_to(self, brain_id: str) -> bool:
        config = self._configs.get(brain_id)
        if not config:
            return False
        try:
            self._active_brain = create_brain(config)
            self._active_id = brain_id
            self._save()
            return True
        except Exception:
            return False

    def get_current_brain(self) -> BaseBrain | None:
        return self._active_brain

    def get_current_config(self) -> BrainConfig | None:
        if self._active_id:
            return self._configs.get(self._active_id)
        return None

    # ── 测试连接 ──────────────────────────────────
    def test_config(self, config: BrainConfig) -> tuple[bool, str]:
        try:
            brain = create_brain(config)
            if hasattr(brain, 'test_connection_quick'):
                return brain.test_connection_quick()
            return brain.test_connection()
        except Exception as e:
            return False, str(e)
