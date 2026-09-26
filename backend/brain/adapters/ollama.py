"""本地 Ollama 适配器（原生 /api/chat 接口）"""

from __future__ import annotations
import httpx
from brain.base import BaseBrain, BrainConfig, BrainResponse


class OllamaBrain(BaseBrain):
    """Ollama 本地模型适配器"""

    def __init__(self, config: BrainConfig):
        self._config = config
        base = config.base_url.rstrip("/") if config.base_url else "http://localhost:11434"
        self._chat_url = f"{base}/api/chat"
        self._tags_url = f"{base}/api/tags"

    # ── BaseBrain ────────────────────────────────────
    @property
    def config(self) -> BrainConfig:
        return self._config

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1) -> BrainResponse:
        payload = {
            "model": self._config.model or "qwen2.5",
            "messages": messages,
            "options": {"temperature": temperature},
            "stream": False,
        }
        last_error = None
        for attempt in range(3):
            try:
                resp = httpx.post(self._chat_url, json=payload, timeout=120.0)
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                return BrainResponse(content=msg.get("content", ""))
            except Exception as e:
                last_error = str(e)
        return BrainResponse(content=f"[Ollama Error] {last_error}")

    def test_connection(self) -> tuple[bool, str]:
        try:
            resp = httpx.get(self._tags_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models", [])
            if models:
                names = [m.get("name", "") for m in models[:8]]
                return True, f"已连接，可用模型: {', '.join(names)}"
            return True, "Ollama 已连接（未找到模型，可先 pull）"
        except httpx.RequestError as e:
            return False, f"无法连接 Ollama: {e}"
        except Exception as e:
            return False, str(e)
