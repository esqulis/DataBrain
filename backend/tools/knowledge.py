"""knowledge 工具：非结构化数据检索模块

支持三种检索方式：
1. 按 ID 直接查（Table_Query + Table_Domain）
2. 语义检索（Multi-step_Retrieval 11MB 大文件）
3. 全部匹配（返回多个候选）
"""
import os
import re
import json
import hashlib
import numpy as np

# 数据文件路径
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..",
                         "赛题1：智能数据分析系统", "非结构化数据")
if not os.path.exists(_DATA_DIR):
    _DATA_DIR = r"D:\Hermes_work\ai赛\赛题1：智能数据分析系统\非结构化数据"

# 全局缓存
_knowledge_cache = {}
_embedding_cache = {}
_embedder = None


def _parse_md_file(filepath):
    """解析 MD 文件（=== ID === 分隔格式），返回 {id: text}"""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # 按 === ID === 分割
    parts = re.split(r"^=== (.+?) ===$", content, flags=re.MULTILINE)
    result = {}
    current_id = None
    for i, part in enumerate(parts):
        part = part.strip()
        if i % 2 == 1:  # 奇数位是 ID
            current_id = part
        elif current_id and part:
            result[current_id] = part
    return result


def _knowledge_db_path():
    """knowledge 持久库路径: backend/data/engine.db"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "engine.db")


def _load_from_db():
    """从 SQLite knowledge_chunks 表加载，成功返回 dict，失败返回 None"""
    import sqlite3
    try:
        db = _knowledge_db_path()
        if not os.path.exists(db):
            return None
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "knowledge_chunks" not in tables:
            conn.close()
            return None
        data = {"Table_Query": {}, "Table_Domain": {}, "Multi_step": {}}
        for kid, source, content in conn.execute("SELECT id, source, content FROM knowledge_chunks"):
            if source in data:
                data[source][kid] = content
        conn.close()
        if not any(data.values()):
            return None
        return data
    except Exception as e:
        print(f"[knowledge] SQLite 加载失败，回退到 MD 文件: {e}")
        return None


def _save_to_db(data):
    """把解析结果写入 SQLite knowledge_chunks 表（幂等：先删后插）"""
    import sqlite3
    try:
        db = _knowledge_db_path()
        os.makedirs(os.path.dirname(db), exist_ok=True)
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id TEXT NOT NULL,
            source TEXT NOT NULL,
            content TEXT NOT NULL,
            total_chars INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, source))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kc_source ON knowledge_chunks(source)")
        rows = [(kid, src, content, len(content))
                for src, items in data.items() for kid, content in items.items()]
        conn.execute("DELETE FROM knowledge_chunks")
        conn.executemany("INSERT INTO knowledge_chunks (id, source, content, total_chars) VALUES (?,?,?,?)", rows)
        conn.commit()
        conn.close()
        print(f"[knowledge] 已持久化 {len(rows)} 条到 {db}")
        return True
    except Exception as e:
        print(f"[knowledge] SQLite 写入失败（不影响内存运行）: {e}")
        return False


def _get_or_load_knowledge():
    """加载所有非结构化数据（懒加载，SQLite 持久层优先）"""
    if _knowledge_cache:
        return _knowledge_cache

    # 1) 优先从 SQLite 持久层加载
    data = _load_from_db()
    if data is not None:
        for k, v in data.items():
            print(f"[knowledge] {k}: 从 SQLite 加载 {len(v)} 条")
        _knowledge_cache.update(data)
        return data

    # 2) 回退：解析 MD 文件
    base = _DATA_DIR
    data = {"Table_Query": {}, "Table_Domain": {}, "Multi_step": {}}

    # 1) Table_Query
    qd = _parse_md_file(os.path.join(base, "Table_Query-数据.md"))
    data["Table_Query"] = qd
    print(f"[knowledge] Table_Query: 加载 {len(qd)} 条")

    # 2) Table_Domain-specific_Operations
    dd = _parse_md_file(os.path.join(base, "Table_Domain-specific_Operations-数据.md"))
    data["Table_Domain"] = dd
    print(f"[knowledge] Table_Domain: 加载 {len(dd)} 条")

    # 3) Multi-step_Retrieval
    md = _parse_md_file(os.path.join(base, "Multi-step_Retrieval-数据.md"))
    data["Multi_step"] = md
    print(f"[knowledge] Multi_step: 加载 {len(md)} 条")

    # 3) 首次解析后写入 SQLite 持久层
    if any(data.values()):
        _save_to_db(data)

    _knowledge_cache.update(data)
    return data



def _get_embedder():
    """获取文本嵌入器（第一次调用时初始化）"""
    global _embedder
    if _embedder is not None:
        return _embedder

    try:
        from sentence_transformers import SentenceTransformer
        # 用小模型，轻量快速
        _embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        print(f"[knowledge] 嵌入器已加载: paraphrase-multilingual-MiniLM-L12-v2")
    except ImportError:
        print("[knowledge] sentence-transformers 未安装，用简单 TF-IDF 替代")
        _embedder = "simple"
    return _embedder


def _simple_embed(texts):
    """简单的词袋嵌入（无 sentence-transformers 时的替代）"""
    import hashlib
    vecs = []
    for t in texts:
        words = set(t.lower().split())
        # 用 hash 模拟 128 维向量
        v = np.zeros(128)
        for w in words:
            h = hashlib.md5(w.encode()).hexdigest()
            idx = int(h[:4], 16) % 128
            v[idx] += 1
        vecs.append(v / (np.linalg.norm(v) + 1e-10))
    return np.array(vecs)


def _build_multi_step_index():
    """为 Multi-step 数据建立向量索引"""
    data = _get_or_load_knowledge()
    md = data.get("Multi_step", {})
    if not md:
        return {}, np.array([])
    if "index" in _embedding_cache:
        return _embedding_cache["index"]

    texts = list(md.values())
    ids = list(md.keys())
    embedder = _get_embedder()

    if embedder == "simple":
        vecs = _simple_embed(texts)
    else:
        vecs = embedder.encode(texts, show_progress_bar=False)

    _embedding_cache["index"] = (ids, vecs)
    print(f"[knowledge] Multi-step 索引: {len(ids)} 条")
    return ids, vecs


def retrieve(question_id=None, query=None, k=3, offset=0, length=2000):
    """知识检索入口（支持分段读取长文本）

    Args:
        question_id: 问题 ID（优先精确匹配）
        query: 搜索文本（语义检索）
        k: 返回 top-k 条
        offset: 分段读取起始位置（字符数，默认 0）
        length: 每段读取长度（字符数，默认 2000）

    Returns:
        list of dict: [{"id":..., "content":..., "source":..., "total_length":...,
                        "offset":..., "has_more":...}, ...]
        当内容被分段时，content 后会追加提示：
        [内容分段 0-2000/共N字符，如需后续内容请用 offset=2000 再次调用]
    """
    data = _get_or_load_knowledge()

    # 1) 如果提供了 ID，在所有源中精确匹配
    if question_id:
        for source, items in data.items():
            if question_id in items:
                full = items[question_id]
                total = len(full)
                off = max(0, int(offset or 0))
                seg = full[off:off + int(length or 2000)]
                has_more = off + len(seg) < total
                item = {
                    "id": question_id,
                    "content": seg,
                    "source": source,
                    "total_length": total,
                    "offset": off,
                    "has_more": has_more,
                }
                if has_more:
                    nxt = off + len(seg)
                    item["content"] += (
                        f"\n[内容分段 {off}-{nxt}/共{total}字符，"
                        f"如需后续内容请用 offset={nxt} 再次调用本工具]"
                    )
                return [item]
        return [{"id": question_id, "content": "", "source": "not_found"}]

    # 2) 如果没有 ID，用语义检索（仅 Multi-step）
    if query:
        ids, vecs = _build_multi_step_index()
        if len(ids) == 0:
            return []

        embedder = _get_embedder()
        if embedder == "simple":
            qv = _simple_embed([query])[0]
        else:
            qv = embedder.encode([query], show_progress_bar=False)[0]

        # 余弦相似度
        sims = np.dot(vecs, qv) / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(qv) + 1e-10)
        top_indices = np.argsort(sims)[-k:][::-1]

        results = []
        for idx in top_indices:
            if sims[idx] > 0.1:  # 阈值过滤
                results.append({
                    "id": ids[idx],
                    "content": _knowledge_cache.get("Multi_step", {}).get(ids[idx], ""),
                    "source": "Multi_step",
                    "score": float(sims[idx]),
                })
        return results

    return []


def get_stats():
    """获取索引统计信息"""
    data = _get_or_load_knowledge()
    return {
        "Table_Query": len(data.get("Table_Query", {})),
        "Table_Domain": len(data.get("Table_Domain", {})),
        "Multi_step": len(data.get("Multi_step", {})),
    }
