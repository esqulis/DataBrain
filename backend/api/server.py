"""FastAPI 应用工厂与启动辅助"""

from __future__ import annotations
import asyncio
import threading
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

_start_attempted = False
_start_lock = threading.Lock()


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="DataBrain API",
        version="2.0.0",
        description="DataBrain 智能数据分析系统 REST API。\n"
                    "切换大脑后，/api/chat 等端点的行为会随之改变。",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.routers import data, brain, auth
    app.include_router(data.router, prefix="/api")
    app.include_router(brain.router, prefix="/api/brain")
    app.include_router(auth.router, prefix="/api")

    @app.get("/api/health", tags=["system"])
    def health():
        """健康检查"""
        from shared_state import get_state
        state = get_state()
        cfg = state.brain_manager.get_current_config()
        return {
            "status": "ok",
            "tables_loaded": state.data_engine.table_count,
            "current_brain": cfg.name if cfg else None,
        }

    return app


def start_api_server(host: str = "127.0.0.1", port: int = 8503):
    """在后台线程启动 Uvicorn（共享同一进程内存）"""
    global _start_attempted
    if _start_attempted:
        return
    with _start_lock:
        if _start_attempted:
            return
        _start_attempted = True

    def _run():
        import uvicorn
        app = create_app()
        # 使用 config + server 手工启动，避免 asyncio.run 冲突
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        try:
            asyncio.run(server.serve())
        except RuntimeError:
            # 如果已有事件循环，用 run_until_complete
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(server.serve())
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"uvicorn serve crashed: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info(f"API server starting on http://{host}:{port}")
    import sys; sys.stderr.write(f"[DataBrain] API server thread started on {host}:{port}\n")
