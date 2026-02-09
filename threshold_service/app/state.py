import json
import os
from typing import Dict

_NODE_TYPE_MAP: Dict[str, str] | None = None

def _load_node_type_map() -> Dict[str, str]:
    global _NODE_TYPE_MAP
    if _NODE_TYPE_MAP is not None:
        return _NODE_TYPE_MAP
    raw = os.getenv("NODE_TYPE_MAP", "")
    if not raw:
        _NODE_TYPE_MAP = {}
        return _NODE_TYPE_MAP
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            _NODE_TYPE_MAP = {str(k): str(v) for k, v in data.items()}
        else:
            _NODE_TYPE_MAP = {}
    except json.JSONDecodeError:
        _NODE_TYPE_MAP = {}
    return _NODE_TYPE_MAP

def infer_node_type(node_id: str) -> str:
    node_map = _load_node_type_map()
    if node_id in node_map:
        return node_map[node_id]

    nid = node_id.upper()
    if nid.startswith("ENT"):
        return "enterprise"
    if nid.startswith("RES"):
        return "residential"
    if nid.startswith("TRUNK"):
        return "trunk"
    if nid.startswith("PUMP"):
        return "pump"
    return os.getenv("NODE_TYPE_DEFAULT", "default")
