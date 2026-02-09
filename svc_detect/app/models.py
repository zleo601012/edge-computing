from typing import Dict, Optional, Union, Tuple
from pydantic import BaseModel, Field

MetricValue = Union[float, int]
ThresholdValue = Union[float, Tuple[float, float]]

class DetectRequest(BaseModel):
    node_id: str = Field(..., description="数据来源节点ID（用于拉取阈值）")
    slot_id: Optional[str] = Field(default=None, description="当前时隙ID，例如 t_101（用于精确取阈值）")
    ts: Optional[float] = Field(default=None, description="时间戳（可选）")
    values: Dict[str, MetricValue] = Field(description="水质观测值，例如 {'COD':80,'pH':7.1}")

class DetectResponse(BaseModel):
    event_id: str
    slot_id: Optional[str]
    level: str
    any_exceed: bool
    exceed: Dict[str, bool]
    exceed_ratio: Dict[str, float]
    threshold_ref: Dict[str, object]
    evidence: Dict[str, object]
    fine: Optional[Dict[str, object]] = None
