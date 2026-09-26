"""跨模块共享的应用状态 —— 连接 Streamlit 与 FastAPI"""

from __future__ import annotations
from memory.data_engine import DataEngine
from brain.manager import BrainManager


class AppState:
    """应用全局状态（模块级单例）"""

    def __init__(self):
        self.data_engine = DataEngine()
        self.brain_manager = BrainManager()
        self.api_server_started = False


_STATE = AppState()


def get_state() -> AppState:
    """获取全局状态"""
    return _STATE
