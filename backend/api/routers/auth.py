"""auth API 路由"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from auth import register as do_register, login as do_login, check_token, logout as do_logout, list_users, reset_password as do_reset_password

router = APIRouter(prefix="/auth", tags=["auth"])

class AuthPost(BaseModel):
    username: str
    password: str

class ResetPwPost(BaseModel):
    user_id: int
    new_password: str = "123456"

def _get_token(req: Request) -> str:
    """从 query 或 header 获取 token"""
    token = req.query_params.get("token", "")
    if not token:
        auth = req.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token

def _require_admin(req: Request):
    """检查当前会话是否为 admin，返回 user dict"""
    token = _get_token(req)
    u = check_token(token)
    if not u:
        raise HTTPException(401, "未登录或会话已过期")
    if u["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return u

@router.post("/register")
def register(req: AuthPost):
    r = do_register(req.username, req.password)
    if not r["success"]:
        raise HTTPException(400, r["error"])
    return r

@router.post("/login")
def login(req: AuthPost):
    r = do_login(req.username, req.password)
    if not r["success"]:
        raise HTTPException(401, r["error"])
    return r

@router.get("/me")
def me(token: str = ""):
    u = check_token(token)
    if not u:
        # 默认免登录：未携带有效 token 时返回访客（普通用户）身份，
        # 前端据此直接进入系统；需要管理员权限时再走 /auth/login。
        return {"user": {"id": 0, "username": "guest", "role": "user"}}
    return {"user": u}

@router.post("/logout")
def logout(token: str = ""):
    do_logout(token)
    return {"success": True}

@router.get("/users")
def users(request: Request):
    u = _require_admin(request)
    r = list_users(u)
    return r

@router.post("/reset-password")
def reset_password(request: Request, req: ResetPwPost):
    """管理员重置用户密码（默认 123456）"""
    u = _require_admin(request)
    r = do_reset_password(u, req.user_id, req.new_password)
    if not r["success"]:
        raise HTTPException(400, r["error"])
    return r
