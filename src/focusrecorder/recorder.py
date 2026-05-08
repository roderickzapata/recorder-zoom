import threading
import time
import os
from pathlib import Path
import cv2
from .config.config import coerce_recording_settings
from .app.factories.capture_backend_factory import create_capture_backend
from .app.factories.mouse_provider_factory import create_mouse_provider
from .app.factories.renderer_factory import create_renderer
from .application.errors import RecordingEnvironmentError
from .domain.ports.capture_backend import CaptureBackend
from .domain.ports.mouse_provider import MouseProvider
from .domain.models.recording_session import FrameSample, RecordingSessionState
from .config.settings import RecordingSettings
from .infrastructure.filesystem.file_naming import get_next_filename
from .infrastructure.audio.sounddevice_audio import SounddeviceAudioRecorder, HAS_AUDIO, mix_wav_files

import platform
IS_WINDOWS = platform.system() == "Windows"



class FocusRecorder:
    def __init__(self, config=None):
        self.is_windows = IS_WINDOWS
        self.settings = coerce_recording_settings(config)
        self.capture_backend = self._build_capture_backend()
        self.mouse_provider = self._build_mouse_provider()
        self.renderer = self._build_renderer()
        self.session = RecordingSessionState()
        self.sw, self.sh = self._get_screen_size()

        self.output_dir = self._get_video_directory()
        os.makedirs(self.output_dir, exist_ok=True)
        self.filename = get_next_filename(
            self.output_dir, prefix="video", custom_name=self.settings.custom_name
        )

        self._audio_recorder = None
        self._system_audio_recorder = None
        if self.settings.audio and HAS_AUDIO:
            mode = getattr(self.settings, "audio_mode", "mic")
            if mode in ("mic", "both"):
                self._audio_recorder = SounddeviceAudioRecorder(device=self.settings.audio_device)
            if mode in ("system", "both"):
                sys_dev = getattr(self.settings, "system_audio_device", None)
                self._system_audio_recorder = SounddeviceAudioRecorder(device=sys_dev)

        self._temp_writer = None
        self._temp_path = ""
        self._injected_raw_data = []  # solo usado por tests

    def _get_video_directory(self):
        """
        Obtiene la carpeta de videos apropiada según la plataforma.
        Guarda en una carpeta compartida del workspace para que los archivos sean
        accesibles también desde Windows cuando se trabaja sobre /d.
        """
        return str(self.settings.output_dir)

    def _on_click(self, x, y, button, pressed):
        self.session.set_clicking(pressed)

    def _build_capture_backend(self) -> CaptureBackend:
        return create_capture_backend(is_windows=self.is_windows)

    def _build_mouse_provider(self) -> MouseProvider:
        return create_mouse_provider()

    def _build_renderer(self):
        return create_renderer()

    def _get_screen_size(self):
        return self.capture_backend.get_screen_size()

    def _get_mouse_position(self):
        return self.mouse_provider.get_position()

    def _validate_capture_backend(self):
        try:
            self.capture_backend.validate()
        except Exception as exc:
            backend_name = type(self.capture_backend).__name__
            message = (
                f"No se pudo iniciar la captura de pantalla con {backend_name}. "
                "El entorno actual no parece ser compatible con el backend de captura seleccionado."
            )
            raise RecordingEnvironmentError(message) from exc

    def start(self):
        self._validate_capture_backend()
        self.session.reset(time.perf_counter())
        self.mouse_provider.start_listener(self._on_click)
        if self._audio_recorder is not None:
            self._audio_recorder.start()
        if self._system_audio_recorder is not None:
            self._system_audio_recorder.start()

        self._temp_path = self.filename.replace(".mp4", "_temp_raw.avi")
        fourcc = cv2.VideoWriter_fourcc(*"XVID")  # type: ignore[attr-defined]
        self._temp_writer = cv2.VideoWriter(
            self._temp_path, fourcc, self.settings.fps, (self.sw, self.sh)
        )
        if not self._temp_writer.isOpened():
            self._temp_writer = None
            self._temp_path = ""

        self.thread = threading.Thread(target=self._record_loop)
        self.thread.start()

    def stop(self, callback_progress=None, export_mode="full"):
        self.session.stop()
        self.mouse_provider.stop_listener()
        self.thread.join()

        audio_wav = None
        mic_wav = None
        sys_wav = None
        if self._audio_recorder is not None:
            wav_path = self.filename.replace(".mp4", "_mic.wav")
            mic_wav = self._audio_recorder.stop(wav_path)
        if self._system_audio_recorder is not None:
            wav_path = self.filename.replace(".mp4", "_sys.wav")
            sys_wav = self._system_audio_recorder.stop(wav_path)

        if mic_wav and sys_wav:
            mixed_path = self.filename.replace(".mp4", "_audio.wav")
            try:
                audio_wav = mix_wav_files(mic_wav, sys_wav, mixed_path)
            finally:
                for p in (mic_wav, sys_wav):
                    if p and os.path.exists(p):
                        os.remove(p)
        elif mic_wav:
            audio_wav = mic_wav
        elif sys_wav:
            audio_wav = sys_wav

        self._render_adaptive_video(callback_progress, export_mode)

        if audio_wav and os.path.exists(audio_wav):
            from .infrastructure.encoding.h264_encoder import add_audio_to_video
            if export_mode in ("full", "both"):
                add_audio_to_video(self.filename, audio_wav)
            if export_mode in ("tiktok", "both"):
                tiktok_path = self.filename.replace(".mp4", "_tiktok.mp4")
                if os.path.exists(tiktok_path):
                    add_audio_to_video(tiktok_path, audio_wav)
            os.remove(audio_wav)

    def _record_loop(self):
        frame_interval = 1.0 / self.settings.fps
        self.capture_backend.start()
        try:
            last_capture = time.perf_counter()
            while self.session.is_recording:
                now = time.perf_counter()
                elapsed = now - last_capture
                if elapsed < frame_interval:
                    time.sleep(max(frame_interval - elapsed - 0.001, 0.001))
                    continue

                frame = self.capture_backend.capture_frame()
                if frame is None:
                    continue

                last_capture = time.perf_counter()
                mx, my = self._get_mouse_position()
                ts = last_capture - self.session.start_time

                if self._temp_writer is not None:
                    self._temp_writer.write(frame)
                else:
                    # fallback RAM (tests o si XVID no está disponible)
                    self._injected_raw_data.append(
                        (frame.copy(), mx, my, self.session.is_clicking, ts)
                    )

                self.session.append_sample(
                    FrameSample(
                        frame=frame,  # referencia temporal solo para preview
                        mouse_x=mx,
                        mouse_y=my,
                        is_clicking=self.session.is_clicking,
                        timestamp=ts,
                    )
                )
        finally:
            self.capture_backend.stop()
            if self._temp_writer is not None:
                self._temp_writer.release()
                self._temp_writer = None

    def _render_adaptive_video(self, callback_progress, export_mode):
        if self._injected_raw_data:
            self.renderer.render(
                raw_data=self._injected_raw_data,
                settings=self.settings,
                screen_size=(self.sw, self.sh),
                output_filename=self.filename,
                callback_progress=callback_progress,
                export_mode=export_mode,
            )
        elif self._temp_path and os.path.exists(self._temp_path):
            self.renderer.render_from_file(
                temp_path=self._temp_path,
                mouse_data=self.session.mouse_data,
                settings=self.settings,
                screen_size=(self.sw, self.sh),
                output_filename=self.filename,
                callback_progress=callback_progress,
                export_mode=export_mode,
            )
            os.remove(self._temp_path)
            self._temp_path = ""

    def _zoomed_crop(self, tiktok: bool = False):
        import numpy as np
        frame = self.session.latest_frame
        if frame is None:
            return None
        sh, sw = frame.shape[:2]
        mx = self.session.latest_mx
        my = self.session.latest_my
        zn = self.settings.zoom
        if tiktok:
            z_h = int(sh / zn)
            z_w = min(int(z_h * 9 / 16), sw)
            z_h = min(z_h, sh)
        else:
            z_w = int(sw / zn)
            z_h = int(sh / zn)
        x1 = int(np.clip(mx - z_w // 2, 0, sw - z_w))
        y1 = int(np.clip(my - z_h // 2, 0, sh - z_h))
        return frame[y1:y1 + z_h, x1:x1 + z_w]

    @property
    def preview_frame(self):
        return self._zoomed_crop(tiktok=False)

    @property
    def preview_frame_tiktok(self):
        return self._zoomed_crop(tiktok=True)

    @property
    def audio_level(self) -> int:
        levels = []
        if self._audio_recorder is not None:
            levels.append(self._audio_recorder.level)
        if self._system_audio_recorder is not None:
            levels.append(self._system_audio_recorder.level)
        if not levels:
            return 0
        return max(levels)

    @property
    def is_recording(self):
        return self.session.is_recording

    @is_recording.setter
    def is_recording(self, value):
        self.session.is_recording = value

    @property
    def is_clicking(self):
        return self.session.is_clicking

    @is_clicking.setter
    def is_clicking(self, value):
        self.session.is_clicking = value

    @property
    def start_time(self):
        return self.session.start_time

    @start_time.setter
    def start_time(self, value):
        self.session.start_time = value

    @property
    def raw_data(self):
        return self._injected_raw_data

    @raw_data.setter
    def raw_data(self, value):
        self._injected_raw_data = value
