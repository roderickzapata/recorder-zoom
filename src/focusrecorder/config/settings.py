from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RecordingSettings:
    """Settings for a recording session."""
    zoom: float
    suavidad: float
    fps: int
    output_dir: Path
    custom_name: str = ""
    audio: bool = False
    audio_device: int | None = None
    audio_mode: str = "mic"
    system_audio_device: int | None = None


@dataclass(frozen=True)
class UISettings:
    """Settings for the user interface state."""
    export_mode: str  # "full", "tiktok", "both"


@dataclass(frozen=True)
class UserPreferences:
    """Complete user preferences combining recording and UI settings."""
    recording: RecordingSettings
    ui: UISettings
