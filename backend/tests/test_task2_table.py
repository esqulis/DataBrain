# -*- coding: utf-8 -*-
"""Task2 回归：REST analyze/visualize 支持 table 参数"""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import memory.data_engine as de
tmpdir = tempfile.mkdtemp(prefix="enginetest2_")
de._DB_PATH = os.path.join(tmpdir, "engine.db")
de._DATA_DIR = tmpdir
de._pragma_applied.clear()

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memory.data_engine import DataEngine
from shared_state import AppState

# 注入测试引擎
state = AppState()
state.data_engine = DataEngine()
eng = state.data_engine

# 两张表，故意让第一张不是目标表
eng.add_table("aaa_first", pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}), {"type": "file"})
eng.add_table(
    "monthly_bills",
    pd.DataFrame({
        "billing_month": [f"2024-{m:02d}-01" for m in range(1, 13)] * 5,
        "amount": list(range(60)),
        "customer_id": [f"c{i%5}" for i in range(60)],
    }),
    {"type": "file"},
)

# monkeypatch shared_state
import shared_state
shared_state._STATE = state

from api.routers import data as data_router

app = FastAPI()
app.include_router(data_router.router, prefix="/api")
client = TestClient(app)

errors = []

# --- analyze 默认第一张表 ---
r = client.post("/api/analyze", json={"action": "describe", "columns": ["x"]})
if r.status_code != 200:
    errors.append(f"describe default: {r.status_code} {r.text[:200]}")
elif r.json().get("table") != "aaa_first":
    errors.append(f"describe default table={r.json().get('table')}")
else:
    print("OK describe default ->", r.json()["table"])

# --- analyze 指定 monthly_bills ---
r = client.post("/api/analyze", json={
    "action": "describe",
    "columns": ["amount"],
    "table": "monthly_bills",
})
if r.status_code != 200:
    errors.append(f"describe table: {r.status_code} {r.text[:200]}")
elif r.json().get("table") != "monthly_bills":
    errors.append(f"describe table got {r.json().get('table')}")
else:
    print("OK describe table=monthly_bills")

# --- analyze forecast 指定表 ---
r = client.post("/api/analyze", json={
    "action": "forecast",
    "columns": ["amount"],
    "table": "monthly_bills",
    "params": {"date_col": "billing_month", "target_col": "amount", "periods": 5},
})
if r.status_code != 200:
    errors.append(f"forecast: {r.status_code} {r.text[:300]}")
else:
    body = r.json()
    rows = body.get("results", {}).get("rows") or []
    if body.get("table") != "monthly_bills":
        errors.append(f"forecast table={body.get('table')}")
    elif len(rows) != 5:
        errors.append(f"forecast periods rows={len(rows)}")
    else:
        print("OK forecast", rows[0], "...", rows[-1])

# --- 不存在的表 ---
r = client.post("/api/analyze", json={"action": "describe", "columns": [], "table": "nope"})
if r.status_code != 404:
    errors.append(f"missing table expect 404 got {r.status_code}")
else:
    print("OK missing table 404")

# --- visualize 指定表 ---
r = client.post("/api/visualize", json={
    "data_description": "amount 按月",
    "title": "账单趋势",
    "chart_type": "line",
    "table": "monthly_bills",
})
if r.status_code != 200:
    errors.append(f"visualize: {r.status_code} {r.text[:300]}")
elif r.json().get("table") != "monthly_bills":
    errors.append(f"visualize table={r.json().get('table')}")
elif not r.json().get("option") and not r.json().get("chart_html"):
    errors.append("visualize 无图表")
else:
    print("OK visualize table=monthly_bills chart_type=", r.json().get("chart_type"))

# --- visualize 默认表 ---
r = client.post("/api/visualize", json={"data_description": "x", "title": "t"})
if r.status_code != 200:
    errors.append(f"visualize default: {r.status_code} {r.text[:200]}")
else:
    print("OK visualize default ->", r.json().get("table"))

print("---")
if errors:
    print("FAIL", len(errors))
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("ALL PASS")
