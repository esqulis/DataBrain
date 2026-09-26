# -*- coding: utf-8 -*-
"""Task5 回归：异步 chat task_id 轮询"""
import os
import sys
import time
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import memory.data_engine as de
tmpdir = tempfile.mkdtemp(prefix="enginetest5_")
de._DB_PATH = os.path.join(tmpdir, "engine.db")
de._DATA_DIR = tmpdir
de._pragma_applied.clear()

from fastapi import FastAPI
from fastapi.testclient import TestClient

import shared_state
from memory.data_engine import DataEngine

state = shared_state.AppState()
state.data_engine = DataEngine()
shared_state._STATE = state

# Mock brain manager
class FakeCfg:
    id = "b1"
    model = "fake"
    base_url = "http://local"

class FakeBrain:
    pass

class FakeMgr:
    def get_current_config(self):
        return FakeCfg()
    def get_current_brain(self):
        return FakeBrain()

state.brain_manager = FakeMgr()

# Mock AgentService
class FakeAgent:
    def __init__(self, *a, **k):
        self.history = []
        self._last_sql = None
        self._pending_charts = []
    def process_query(self, msg):
        time.sleep(0.15)  # 模拟耗时
        return {"response": f"回答:{msg}", "sql": "SELECT 1", "charts": [{"type": "bar"}]}

import api.routers.data as data_router
# 直接 mock _get_agent
data_router._get_agent = lambda state: (FakeAgent(), FakeBrain())

from api.routers import data as dr
app = FastAPI()
app.include_router(dr.router, prefix="/api")
client = TestClient(app)

errors = []

# --- async 提交 ---
r = client.post("/api/chat/async", json={"message": "统计销售额"})
if r.status_code != 200:
    errors.append(f"async submit: {r.status_code} {r.text}")
    print("FAIL early")
    sys.exit(1)
tid = r.json()["task_id"]
print("OK submit task_id=", tid)

# 立即查状态应 processing/queued
s0 = client.get(f"/api/chat/status/{tid}").json()
print("OK immediate status=", s0.get("status"), s0.get("message"))
if s0.get("status") not in ("queued", "processing", "done"):
    errors.append(f"bad status {s0}")

# 轮询直到 done
final = None
for i in range(40):
    s = client.get(f"/api/chat/status/{tid}").json()
    if s.get("status") == "done":
        final = s
        break
    if s.get("status") == "error":
        errors.append(f"error status: {s}")
        break
    time.sleep(0.05)
else:
    errors.append("timeout polling")

if final:
    if final.get("response") != "回答:统计销售额":
        errors.append(f"response={final.get('response')}")
    if not final.get("has_charts"):
        errors.append(f"charts missing {final}")
    if final.get("sql") != "SELECT 1":
        errors.append(f"sql={final.get('sql')}")
    print("OK final", final["response"], "charts", final["has_charts"])

# --- 未知任务 ---
u = client.get("/api/chat/status/nope").json()
if u.get("status") != "unknown":
    errors.append(f"unknown={u}")
else:
    print("OK unknown task")

# --- 无大脑时 400（恢复真实判定逻辑）---
def _real_get_agent(st):
    cfg = st.brain_manager.get_current_config()
    brain = st.brain_manager.get_current_brain()
    if not cfg or not brain:
        return None, None
    return FakeAgent(), brain

class EmptyMgr:
    def get_current_config(self):
        return None
    def get_current_brain(self):
        return None
state.brain_manager = EmptyMgr()
data_router._get_agent = _real_get_agent
r = client.post("/api/chat/async", json={"message": "x"})
if r.status_code != 400:
    errors.append(f"no brain expect 400 got {r.status_code} {r.text}")
else:
    print("OK no-brain 400")

# --- 同步 /chat 仍可用 ---
state.brain_manager = FakeMgr()
data_router._get_agent = lambda state: (FakeAgent(), FakeBrain())
r = client.post("/api/chat", json={"message": "hello"})
if r.status_code != 200 or "回答:hello" not in r.json().get("response", ""):
    errors.append(f"sync chat {r.status_code} {r.text[:200]}")
else:
    print("OK sync chat still works")

print("---")
if errors:
    print("FAIL", len(errors))
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("ALL PASS")
