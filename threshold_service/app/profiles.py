from dataclasses import dataclass

@dataclass(frozen=True)
class Profile:
    q_high: float = 0.95
    q_low: float = 0.05
    w_long: float = 0.7         # long/short融合权重
    smooth_beta: float = 0.2     # 阈值平滑
    short_window: int = 60
    long_window: int = 720
    long_recompute_every: int = 60  # 每60条重算一次长期阈值（≈1小时）

PROFILES = {
    "enterprise":  Profile(q_high=0.93, w_long=0.6, smooth_beta=0.15),
    "residential": Profile(q_high=0.95, w_long=0.7, smooth_beta=0.25),
    "trunk":       Profile(q_high=0.98, w_long=0.8, smooth_beta=0.20),
    "pump":        Profile(q_high=0.97, w_long=0.8, smooth_beta=0.25),
}
DEFAULT_PROFILE = Profile()
