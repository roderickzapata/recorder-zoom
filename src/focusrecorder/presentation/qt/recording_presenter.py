import os
from dataclasses import dataclass, replace
from pathlib import Path

from ...config.config import (
    get_app_config,
    save_user_preferences_from_settings,
    with_recording_overrides,
)
from ...config.settings import UISettings, UserPreferences
from ...application.dto import StopRecordingResult
from ...application.use_cases.start_recording import StartRecordingUseCase
from ...application.use_cases.stop_recording import StopRecordingUseCase
from ...infrastructure.system.file_explorer import open_folder_in_explorer
from .ui_conversions import (
    recording_suavidad_to_ui,
    recording_zoom_to_ui,
    ui_suavidad_to_recording,
    ui_zoom_to_recording,
)


DEFAULT_START_BUTTON_TEXT = "INICIAR GRABACIÓN"
DEFAULT_START_BUTTON_STYLE = "background: #28a745; color: white; font-weight: bold;"
STOP_BUTTON_TEXT = "DETENER Y PROCESAR"
STOP_BUTTON_STYLE = "background: #dc3545; color: white; font-weight: bold;"


@dataclass(frozen=True)
class StartRecordingViewModel:
    status_text: str
    button_text: str = STOP_BUTTON_TEXT
    button_style: str = STOP_BUTTON_STYLE


@dataclass(frozen=True)
class RenderRecordingViewModel:
    status_text: str


@dataclass(frozen=True)
class FinishedRecordingViewModel:
    status_text: str
    button_text: str = DEFAULT_START_BUTTON_TEXT
    button_style: str = DEFAULT_START_BUTTON_STYLE


class RecordingPresenter:
    def __init__(self, app_config=None, start_recording_use_case=None, stop_recording_use_case=None):
        self.app_config = app_config or get_app_config()
        self.start_recording_use_case = start_recording_use_case or StartRecordingUseCase()
        self.stop_recording_use_case = stop_recording_use_case or StopRecordingUseCase()
        self.recorder = None

    @property
    def default_recording_settings(self):
        return self.app_config.user_preferences.recording

    def get_output_dir_display(self):
        return str(self.default_recording_settings.output_dir)

    def get_default_ui_state(self):
        recording = self.app_config.user_preferences.recording
        return {
            "zoom": recording_zoom_to_ui(recording.zoom),
            "suavidad": recording_suavidad_to_ui(recording.suavidad),
            "fps": recording.fps,
            "export_mode": self.app_config.user_preferences.ui.export_mode,
            "audio": recording.audio,
            "audio_mode": getattr(recording, "audio_mode", "mic"),
        }

    def has_active_recording(self):
        return self.recorder is not None and self.recorder.is_recording

    def start_recording(self, *, zoom, suavidad, fps, custom_name="", audio=False, audio_device=None, audio_mode="mic", system_audio_device=None):
        self.save_current_preferences(zoom=zoom, suavidad=suavidad, fps=fps, audio=audio, audio_mode=audio_mode)
        settings = replace(
            self.app_config.user_preferences.recording,
            custom_name=custom_name,
            audio_device=audio_device,
            audio_mode=audio_mode,
            system_audio_device=system_audio_device,
        )
        result = self.start_recording_use_case.execute(settings)
        self.recorder = result.recorder
        filename = os.path.basename(result.filename)
        return StartRecordingViewModel(status_text=f"🔴 Grabando...\n{filename}")

    def build_rendering_view_model(self, export_mode):
        label = {
            "full": "pantalla completa",
            "tiktok": "TikTok 9:16",
            "both": "ambos formatos",
        }[export_mode]
        return RenderRecordingViewModel(status_text=f"⚙️ Renderizando {label}...")

    def stop_recording(self, export_mode, callback_progress=None):
        if self.recorder is None:
            raise RuntimeError("No active recording to stop")

        result = self.stop_recording_use_case.execute(
            self.recorder,
            callback_progress=callback_progress,
            export_mode=export_mode,
        )
        self.recorder = None
        return result

    def build_finished_view_model(self, result: StopRecordingResult):
        lines = ["✅ Guardado:"]
        if result.full_path:
            lines.append(f"📺 {os.path.basename(result.full_path)}")
        if result.tiktok_path:
            lines.append(f"📱 {os.path.basename(result.tiktok_path)}")
        return FinishedRecordingViewModel(status_text="\n".join(lines))

    def save_current_preferences(self, *, zoom, suavidad, fps, export_mode=None, audio=None, audio_mode=None):
        updated_recording = with_recording_overrides(
            self.app_config.user_preferences.recording,
            zoom=ui_zoom_to_recording(zoom),
            suavidad=ui_suavidad_to_recording(suavidad),
            fps=fps,
            audio=audio,
            audio_mode=audio_mode,
        )
        updated_ui = UISettings(
            export_mode=export_mode or self.app_config.user_preferences.ui.export_mode
        )
        self._save_preferences(UserPreferences(recording=updated_recording, ui=updated_ui))

    def update_output_directory(self, output_dir: str | Path):
        updated_recording = replace(
            self.app_config.user_preferences.recording,
            output_dir=Path(output_dir),
        )
        self._save_preferences(
            UserPreferences(
                recording=updated_recording,
                ui=self.app_config.user_preferences.ui,
            )
        )

    def reveal_output_directory(self):
        open_folder_in_explorer(self.app_config.user_preferences.recording.output_dir)

    def _save_preferences(self, preferences: UserPreferences):
        save_user_preferences_from_settings(preferences)
        self.app_config = replace(self.app_config, user_preferences=preferences)
