"""LLMClient: 大模型 API 封装（兼容 OpenAI 格式）"""

import os
import json
import httpx
from typing import Any


class LLMResponse:
    """模型返回的统一封装"""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.has_tool_calls = len(self.tool_calls) > 0


class LLMClient:
    """大模型 API 封装 —— 兼容 OpenAI / DeepSeek / 通义千问 等"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: float = 60.0,
        chat_url: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # chat_url 可显式指定；相对路径自动拼 base_url
        if chat_url:
            self.chat_url = chat_url if chat_url.startswith("http") else f"{self.base_url.rstrip('/')}{chat_url}"
        else:
            self.chat_url = f"{self.base_url}/v1/chat/completions"

    # ----------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.1,
        max_retries: int = 3,
    ) -> LLMResponse:
        """调用模型并解析返回"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = httpx.post(
                    self.chat_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._parse_choice(data["choices"][0]["message"])
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            except httpx.RequestError as e:
                last_error = f"网络错误: {e}"
            except (KeyError, json.JSONDecodeError) as e:
                last_error = f"返回解析错误: {e}"

        return LLMResponse(content=f"[API Error] {last_error}")

    # ----------------------------------------------------------------
    def _parse_choice(self, msg: dict) -> LLMResponse:
        content = msg.get("content") or ""
        tool_calls_raw = msg.get("tool_calls")
        tcs = []
        if tool_calls_raw:
            for tc in tool_calls_raw:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tcs.append({
                    "id": tc.get("id", ""),
                    "name": tc["function"]["name"],
                    "args": args,
                })
        return LLMResponse(content=content, tool_calls=tcs)
