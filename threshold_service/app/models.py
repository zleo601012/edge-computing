from typing import Dict, Optional, Any, List
from pydantic import BaseModel, Field

class Observation(BaseModel):
    node_id: str = Field(..., examples=["ENT_1"])
    ts: Optional[Any] = None  # 可选：int/str都行
    values: Dict[str, float]

class IngestResponse(BaseModel):
    node_id: str
    node_type: str
    counter: int
    thresholds: Dict[str, Dict[str, Optional[float]]]

class BatchIngestResponse(BaseModel):
    ingested: int
    nodes: Dict[str, int]  # node_id -> count
