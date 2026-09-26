"""OpenAI 兼容适配器 —— 适用于 DeepSeek / OpenAI / 通义千问 / 本地 Qwen / ChatGLM 等"""

from __future__ import annotations
import json
import httpx
from brain.base import BaseBrain, BrainConfig, BrainResponse


class OpenAICompatibleBrain(BaseBrain):
    """通用 OpenAI 格式 API 适配器"""

    def __init__(self, config: BrainConfig):
        self._config = config
        # 优先使用 extra_params 中的 chat_url（兼容火山引擎等自定义路径）
        custom_url = (config.extra_params or {}).get("chat_url", "")
        if custom_url:
            self._chat_url = custom_url if custom_url.startswith("http") else f"{config.base_url.rstrip('/')}{custom_url}"
        else:
            base = config.base_url.rstrip("/") if config.base_url else "https://api.deepseek.com"
            # 构建 chat completions URL
            if not base.endswith("/chat/completions"):
                if "/v1" in base:
                    base += "/chat/completions"
                else:
                    base += "/v1/chat/completions"
            self._chat_url = base

    # ── BaseBrain ────────────────────────────────────
    @property
    def config(self) -> BrainConfig:
        return self._config

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1) -> BrainResponse:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model or "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_error = None
        for attempt in range(3):
            try:
                resp = httpx.post(self._chat_url, headers=headers, json=payload, timeout=120.0)
                resp.raise_for_status()
                data = resp.json()
                return self._parse_choice(data["choices"][0]["message"])
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                if e.response.status_code == 401:
                    break  # 认证失败无需重试
            except httpx.RequestError as e:
                last_error = f"网络错误: {e}"
            except (KeyError, json.JSONDecodeError) as e:
                last_error = f"返回解析失败: {e}"

        return BrainResponse(content=f"[API Error] {last_error}")

    def test_connection(self) -> tuple[bool, str]:
        try:
            resp = self.chat([{"role": "user", "content": "ping"}], temperature=0)
            if resp.content and not resp.content.startswith("[API Error"):
                return True, "连接成功！模型已响应。"
            return False, resp.content
        except Exception as e:
            return False, str(e)

    def test_connection_quick(self) -> tuple[bool, str]:
        """快速测试 —— 短超时、不重试"""
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model or "deepseek-chat",
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 5,
        }
        try:
            import httpx
            resp = httpx.post(self._chat_url, headers=headers, json=payload, timeout=8.0)
            resp.raise_for_status()
            return True, "连接成功！模型已响应。"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return False, f"认证失败：API Key 无效 (401)"
            return False, f"HTTP {e.response.status_code}: {e.response.text[:100]}"
        except httpx.TimeoutException:
            return False, "连接超时，请检查 API 端点地址或网络"
        except Exception as e:
            return False, str(e)

    # ── 内部 ─────────────────────────────────────────
    @staticmethod
    def _parse_choice(msg: dict) -> BrainResponse:
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        tcs = []
        for tc in (msg.get("tool_calls") or []):
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            tcs.append({
                "id": tc.get("id", ""),
                "name": tc["function"]["name"],
                "args": args,
            })
        return BrainResponse(content=content, tool_calls=tcs, reasoning_content=reasoning)
