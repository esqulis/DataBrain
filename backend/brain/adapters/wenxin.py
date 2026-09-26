"""百度文心一言适配器（ERNIE Bot 原生 API）"""

from __future__ import annotations
import httpx
from brain.base import BaseBrain, BrainConfig, BrainResponse


class WenxinBrain(BaseBrain):
    """文心一言适配器 —— 使用 access_token 鉴权"""

    def __init__(self, config: BrainConfig):
        self._config = config
        self._access_token: str | None = None
        self._token_url = "https://aip.baidubce.com/oauth/2.0/token"

    # ── 鉴权 ─────────────────────────────────────────
    def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token
        resp = httpx.post(
            self._token_url,
            params={
                "grant_type": "client_credentials",
                "client_id": self._config.api_key,
                "client_secret": self._config.secret_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]
        return self._access_token

    # ── BaseBrain ────────────────────────────────────
    @property
    def config(self) -> BrainConfig:
        return self._config

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.1) -> BrainResponse:
        last_error = None
        for attempt in range(3):
            try:
                token = self._ensure_token()
                model = self._config.model or "ernie-4.0"
                url = (
                    f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{model}"
                    f"?access_token={token}"
                )
                payload = {
                    "messages": messages,
                    "temperature": temperature,
                }
                resp = httpx.post(url, json=payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                return BrainResponse(content=data.get("result", ""))
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
                # token 过期则刷新
                if e.response.status_code in (401, 403):
                    self._access_token = None
            except Exception as e:
                last_error = str(e)
        return BrainResponse(content=f"[文心 Error] {last_error}")

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._ensure_token()
            return True, "连接成功！Token 获取正常。"
        except Exception as e:
            return False, str(e)
