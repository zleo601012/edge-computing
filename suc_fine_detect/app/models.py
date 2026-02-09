from typing import Dict, List, Optional, Union, Tuple
from pydantic import BaseModel, Field

MetricValue = Union[float, int]
ThresholdValue = Union[float, Tuple[float, float]]

class FineRequest(BaseModel):
    # 来自阈值检测服务的事件ID（用于关联）
    event_id: str
    node_type: str = Field(description="enterprise/residential/trunk/pump")
    slot_id: Optional[str] = None
    ts: Optional[float] = None

    # 当前点（至少要有）
    values: Dict[str, MetricValue]

    # 阈值检测阶段算出的 exceed_ratio（建议传，fine 会用来评分）
    exceed_ratio: Dict[str, float] = Field(default_factory=dict)

    # 可选：短窗口序列（用于“持续性/变化点”更可靠）
    # 每个元素与 values 同结构，如 [{"COD":..,"pH":..}, ...]
    series: Optional[List[Dict[str, MetricValue]]] = None

class FineResponse(BaseModel):
    event_id: str
    slot_id: Optional[str]
    is_confirmed_event: bool
    severity_score: float  # 0~1
    pollution_level: str   # LIGHT/MEDIUM/HEAVY
    pollution_type: str
    confidence: float      # 0~1
    evidence: Dict[str, object]
