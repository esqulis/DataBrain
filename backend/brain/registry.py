"""适配器注册中心 —— 厂商预设 + 动态创建"""

from brain.base import BaseBrain, BrainConfig
from brain.adapters.openai_compatible import OpenAICompatibleBrain
from brain.adapters.wenxin import WenxinBrain
from brain.adapters.ollama import OllamaBrain

# ── 适配器类注册表 ────────────────────────────────
ADAPTER_REGISTRY: dict[str, type[BaseBrain]] = {
    "openai_compatible": OpenAICompatibleBrain,
    "wenxin": WenxinBrain,
    "ollama": OllamaBrain,
}

# ── 厂商预设（UI 下拉菜单用） ─────────────────────
PROVIDER_PRESETS: dict[str, dict] = {
    "deepseek": {
        "adapter_type": "openai_compatible",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "openai": {
        "adapter_type": "openai_compatible",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "tongyi": {
        "adapter_type": "openai_compatible",
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "wenxin": {
        "adapter_type": "wenxin",
        "name": "文心一言",
        "base_url": "",
        "model": "ernie-4.0",
    },
    "ollama": {
        "adapter_type": "ollama",
        "name": "Ollama（本地）",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5",
    },
    "custom": {
        "adapter_type": "openai_compatible",
        "name": "自定义（OpenAI 兼容）",
        "base_url": "",
        "model": "",
    },
}


def create_brain(config: BrainConfig) -> BaseBrain:
    """根据配置创建大脑实例"""
    cls = ADAPTER_REGISTRY.get(config.adapter_type)
    if not cls:
        raise ValueError(f"未知适配器类型: {config.adapter_type}")
    return cls(config)


def get_preset(preset_key: str) -> dict:
    """获取厂商预设（安全拷贝）"""
    return dict(PROVIDER_PRESETS.get(preset_key, {}))
