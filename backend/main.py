"""DataBrain — 智能数据分析系统  后端入口 (FastAPI + React SPA)"""

from __future__ import annotations
import os
import sys
import math
import json
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


class SafeEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，自动处理 NaN/Infinity"""
    def default(self, obj):
        return None  # 不可序列化的返回 null

    def encode(self, o):
        return super().encode(self._clean(o))

    def _clean(self, o):
        if isinstance(o, float):
            if math.isinf(o) or math.isnan(o):
                return None
            return o
        if isinstance(o, dict):
            return {k: self._clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [self._clean(v) for v in o]
        return o

# 将 backend/ 加入 sys.path 以支持相对导入
_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

# 加载 .env
_env_path = os.path.join(_this_dir, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.replace("export ", "").strip()
                v = v.strip().strip("\"'")
                os.environ.setdefault(k, v)

# ── 创建应用 ─────────────────────────────────────
app = FastAPI(
    title="DataBrain API",
    version="3.0.0",
    description="DataBrain 智能数据分析系统 · 可切换大脑 · RESTful API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
# 全局 JSON 编码器，防止 NaN/Inf 导致 500
from fastapi.responses import JSONResponse
from starlette.responses import Response
import math

_encoder = SafeEncoder()

@app.middleware("http")
async def safe_json_middleware(request, call_next):
    response = await call_next(request)
    if isinstance(response, JSONResponse) and response.status_code < 500:
        try:
            body = response.body
            if b"NaN" in body or b"Infinity" in body or b"-Infinity" in body:
                import json as _json
                safe_body = _encoder.encode(_json.loads(body))
                return Response(content=safe_body, status_code=response.status_code,
                               media_type="application/json", headers=dict(response.headers))
        except:
            pass
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册 API 路由 ─────────────────────────────────
from api.routers import data, brain, auth
from shared_state import get_state
app.include_router(data.router, prefix="/api")
app.include_router(brain.router, prefix="/api/brain")
app.include_router(auth.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    """健康检查"""
    state = get_state()
    cfg = state.brain_manager.get_current_config()
    return {
        "status": "ok",
        "tables_loaded": state.data_engine.table_count,
        "current_brain": cfg.name if cfg else None,
    }


# ── 静态文件（React SPA 构建产物） ─────────────────
_frontend_dist = os.path.join(_this_dir, "..", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="spa")


def main():
    """入口：启动 uvicorn 服务器"""
    port = int(os.environ.get("PORT", 8502))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        timeout_keep_alive=300,
    )


if __name__ == "__main__":
    main()
