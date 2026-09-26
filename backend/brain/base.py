"""大脑适配器基类与统一数据结构"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainConfig:
    """一份大脑配置"""
    id: str = ""
    name: str = "未命名"
    adapter_type: str = "openai_compatible"   # 对应注册中心的 key
    provider: str = "custom"                  # UI 展示用
    api_key: str = ""
    secret_key: str = ""                      # 用于文心等需要双重密钥的厂商
    base_url: str = ""
    model: str = ""
    extra_params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> BrainConfig:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", "未命名"),
            adapter_type=d.get("adapter_type", "openai_compatible"),
            provider=d.get("provider", "custom"),
            api_key=d.get("api_key", ""),
            secret_key=d.get("secret_key", ""),
            base_url=d.get("base_url", ""),
            model=d.get("model", ""),
            extra_params=d.get("extra_params", {}),
        )


class BrainResponse:
    """统一响应 —— 与 core.llm_client.LLMResponse 兼容"""

    def __init__(self, content: str = "", tool_calls: list | None = None, reasoning_content: str = ""):
        self.content = content
        self.tool_calls = tool_calls or []
        self.has_tool_calls = len(self.tool_calls) > 0
        self.reasoning_content = reasoning_content


class BaseBrain(ABC):
    """大脑适配器基类 —— 所有模型适配器必须实现"""

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1) -> BrainResponse:
        ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        ...

    @property
    @abstractmethod
    def config(self) -> BrainConfig:
        ...
