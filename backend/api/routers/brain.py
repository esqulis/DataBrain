"""大脑配置管理 API"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from brain.base import BrainConfig
from brain.registry import PROVIDER_PRESETS
from shared_state import get_state

router = APIRouter(tags=["brain"])


# ── Schema ─────────────────────────────────────────
class BrainAddRequest(BaseModel):
    name: str
    adapter_type: str = "openai_compatible"
    provider: str = "custom"
    api_key: str = ""
    secret_key: str = ""
    base_url: str = ""
    model: str = ""
    chat_url: str = ""


class BrainSwitchRequest(BaseModel):
    brain_id: str


class BrainTestRequest(BaseModel):
    adapter_type: str = "openai_compatible"
    api_key: str = ""
    secret_key: str = ""
    base_url: str = ""
    model: str = ""
    chat_url: str = ""


class BrainOut(BaseModel):
    id: str
    name: str
    adapter_type: str
    provider: str
    base_url: str
    model: str
    api_key: str = ""
    secret_key: str = ""


# ── 端点 ───────────────────────────────────────────
@router.get("/providers")
def list_providers():
    """列出支持的厂商及预设"""
    items = []
    for key, preset in PROVIDER_PRESETS.items():
        items.append({"key": key, **preset})
    return {"providers": items}


@router.get("/list")
def list_brains():
    """列出已配置的大脑"""
    state = get_state()
    configs = state.brain_manager.list_configs()
    return {"brains": [c.to_dict() for c in configs], "count": len(configs)}


@router.get("/current")
def current_brain():
    """获取当前激活的大脑信息"""
    state = get_state()
    cfg = state.brain_manager.get_current_config()
    if cfg:
        return {"brain": cfg.to_dict(), "active": True}
    return {"brain": None, "active": False}


@router.post("/add")
def add_brain(req: BrainAddRequest):
    """新增大脑配置"""
    state = get_state()
    extra = {}
    if req.chat_url:
        extra["chat_url"] = req.chat_url
    config = BrainConfig(
        name=req.name,
        adapter_type=req.adapter_type,
        provider=req.provider,
        api_key=req.api_key,
        secret_key=req.secret_key,
        base_url=req.base_url,
        model=req.model,
        extra_params=extra,
    )
    brain_id = state.brain_manager.add_config(config)
    return {"brain_id": brain_id, "message": f"已添加大脑「{config.name}」"}


@router.delete("/{brain_id}")
def remove_brain(brain_id: str):
    """删除大脑配置"""
    state = get_state()
    if state.brain_manager.remove_config(brain_id):
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="大脑配置不存在")


@router.post("/switch")
def switch_brain(req: BrainSwitchRequest):
    """切换当前使用的大脑"""
    state = get_state()
    ok = state.brain_manager.switch_to(req.brain_id)
    if not ok:
        raise HTTPException(status_code=400, detail="切换失败，请检查大脑配置是否正确。")
    cfg = state.brain_manager.get_current_config()
    return {"message": f"已切换至「{cfg.name if cfg else ''}」", "brain": cfg.to_dict() if cfg else None}


@router.post("/test")
def test_brain(req: BrainTestRequest):
    """测试指定配置的连通性"""
    extra = {}
    if req.chat_url:
        extra["chat_url"] = req.chat_url
    config = BrainConfig(
        adapter_type=req.adapter_type,
        api_key=req.api_key,
        secret_key=req.secret_key,
        base_url=req.base_url,
        model=req.model,
        extra_params=extra,
    )
    state = get_state()
    ok, msg = state.brain_manager.test_config(config)
    return {"success": ok, "message": msg}
