"""auth 工具：用户注册/登录/JWT 会话"""
import os, sqlite3, hashlib, secrets, time, hmac

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "users.db")

def _conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'user',created_at INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER,username TEXT,role TEXT,created_at INTEGER,expires_at INTEGER,FOREIGN KEY(user_id) REFERENCES users(id))")
    c.commit()
    # seed admin if not exists
    row = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not row:
        c.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                  ("admin", hash_pw("123"), "admin", int(time.time())))
        c.commit()
    return c

def hash_pw(pw: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"

def verify_pw(pw: str, stored: str) -> bool:
    salt, h = stored.split("$", 1)
    return hmac.compare_digest(h, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex())

def register(username: str, password: str) -> dict:
    if not username or not password or len(password) < 3:
        return {"success": False, "error": "用户名不能为空，密码至少3位"}
    c = _conn()
    try:
        c.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                  (username, hash_pw(password), "user", int(time.time())))
        c.commit()
        return {"success": True, "message": "注册成功"}
    except sqlite3.IntegrityError:
        return {"success": False, "error": "用户名已存在"}
    finally:
        c.close()

def login(username: str, password: str) -> dict:
    c = _conn()
    row = c.execute("SELECT id,username,password_hash,role FROM users WHERE username=?", (username,)).fetchone()
    if not row or not verify_pw(password, row[2]):
        c.close()
        return {"success": False, "error": "用户名或密码错误"}
    token = secrets.token_urlsafe(48)
    now = int(time.time())
    c.execute("INSERT INTO sessions(token,user_id,username,role,created_at,expires_at) VALUES(?,?,?,?,?,?)",
              (token, row[0], row[1], row[3], now, now + 86400 * 7))
    c.commit()
    c.close()
    return {"success": True, "token": token, "user": {"id": row[0], "username": row[1], "role": row[3]}}

def check_token(token: str) -> dict | None:
    if not token:
        return None
    c = _conn()
    row = c.execute("SELECT user_id,username,role,expires_at FROM sessions WHERE token=? AND expires_at>?",
                    (token, int(time.time()))).fetchone()
    c.close()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "role": row[2]}

def logout(token: str):
    c = _conn()
    c.execute("DELETE FROM sessions WHERE token=?", (token,))
    c.commit()
    c.close()

def list_users(admin_user: dict | None = None) -> dict:
    if not admin_user or admin_user.get("role") != "admin":
        return {"success": False, "error": "无权限"}
    c = _conn()
    rows = c.execute("SELECT id,username,role,created_at FROM users ORDER BY id").fetchall()
    c.close()
    return {"success": True, "users": [{"id": r[0], "username": r[1], "role": r[2], "created_at": r[3]} for r in rows]}

def reset_password(admin_user: dict | None, target_user_id: int, new_password: str = "123456") -> dict:
    """管理员重置指定用户的密码（默认 123456）"""
    if not admin_user or admin_user.get("role") != "admin":
        return {"success": False, "error": "无权限"}
    if not new_password or len(new_password) < 3:
        return {"success": False, "error": "密码至少3位"}
    c = _conn()
    row = c.execute("SELECT id,role FROM users WHERE id=?", (target_user_id,)).fetchone()
    if not row:
        c.close()
        return {"success": False, "error": "用户不存在"}
    if row[1] == "admin":
        c.close()
        return {"success": False, "error": "不能重置管理员的密码"}
    c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(new_password), target_user_id))
    c.commit()
    c.close()
    return {"success": True, "message": f"用户密码已重置为 {new_password}"}
