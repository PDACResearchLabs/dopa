"""dopa sensor daemon configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path.home() / ".dopa"


@dataclass
class Config:
    # Capture
    capture_interval_seconds: int = 300  # 5 min between frames
    deep_analysis_every_n: int = 3       # vision model every Nth frame (every ~15 min)
    camera_index: int = 0
    jpeg_quality: int = 70
    max_image_dimension: int = 1024

    # Storage  (only derived features/metrics are persisted — never raw images)
    db_path: str = field(default_factory=lambda: str(DATA_DIR / "sensor.db"))

    # Cloud vision (OPT-IN, default OFF). When False, dopa runs fully local:
    # no webcam frame ever leaves the machine. Enable only with explicit consent
    # via DOPA_CLOUD_VISION=1 (and a GEMINI_API_KEY). See PRIVACY.md.
    cloud_vision_enabled: bool = field(default_factory=lambda: os.environ.get(
        "DOPA_CLOUD_VISION", ""
    ).strip().lower() in ("1", "true", "yes", "on"))

    # (Git sensor scope is configured via DOPA_GIT_ROOT / DOPA_GIT_SCAN_DIRS —
    #  see sensors/git_sensor.py and PRIVACY.md.)

    # Baseline & detection
    baseline_window_days: int = 14
    deviation_threshold_std: float = 2.0
    min_observations_for_baseline: int = 50

    # Gemini Vision API (used only when cloud_vision_enabled)
    gemini_model: str = field(default_factory=lambda: os.environ.get(
        "GEMINI_MODEL", "gemini-2.5-flash"
    ))
    gemini_max_tokens: int = 4096
    vision_timeout_seconds: int = 15

    # Notifications
    notification_cooldown_minutes: int = 30
    notification_enabled: bool = True

    # Derived
    def __post_init__(self):
        os.makedirs(str(Path(self.db_path).parent), exist_ok=True)

    @property
    def gemini_api_key(self) -> str | None:
        return os.environ.get("GEMINI_API_KEY")

    @property
    def deep_analysis_interval_seconds(self) -> int:
        return self.capture_interval_seconds * self.deep_analysis_every_n
