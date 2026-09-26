"""Config: 存储策略配置加载器"""
import os
import fnmatch
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "storage.yaml")

# 默认配置
DEFAULT = {
    "storage": {
        "default_strategy": "auto",
        "sqlite": {"db_path": "./data/engine.db", "max_load_rows": 1000, "agg_threshold": 5000},
        "memory_cache": {"enabled": False, "max_cache_rows": 5000, "max_tables": 3},
        "per_table": {},
    },
    "upload": {"csv_chunk_size": 5000, "excel_max_rows": 50000, "temp_dir": "./data/tmp", "cleanup_temp": True},
    "analyze": {"use_sql_aggregation": True, "max_unique_categories": 50},
}


def _merge(base: dict, override: dict) -> dict:
    """递归合并配置"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    """加载存储配置文件，不存在则返回默认"""
    if not os.path.exists(_CONFIG_PATH):
        return DEFAULT
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        overrides = yaml.safe_load(f)
    return _merge(DEFAULT, overrides if overrides else {})


def get_table_strategy(table_name: str, config: dict = None) -> dict:
    """获取某张表的存储策略"""
    if config is None:
        config = load_config()
    sc = config["storage"]

    # 1) 精确匹配
    if table_name in sc.get("per_table", {}):
        return {**sc["sqlite"], **sc["per_table"][table_name]}

    # 2) 通配符匹配（正序匹配第一个）
    for pattern, opts in sc.get("per_table", {}).items():
        if fnmatch.fnmatch(table_name, pattern) or fnmatch.fnmatch(table_name.lower(), pattern.lower()):
            return {**sc["sqlite"], **opts}

    # 3) 默认策略
    strat = sc.get("default_strategy", "auto")
    return {
        "strategy": strat,
        **sc["sqlite"],
    }
