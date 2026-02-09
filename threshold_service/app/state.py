def infer_node_type(node_id: str) -> str:
    nid = node_id.upper()
    if nid.startswith("ENT"):
        return "enterprise"
    if nid.startswith("RES"):
        return "residential"
    if nid.startswith("TRUNK"):
        return "trunk"
    if nid.startswith("PUMP"):
        return "pump"
    return "default"
