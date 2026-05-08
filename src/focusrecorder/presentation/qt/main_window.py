import os
import shutil
import time
from pathlib import Path

import cv2
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...application.errors import RecordingEnvironmentError
from ...config.constants import (
    UI_MAX_FPS,
    UI_MAX_SUAVIDAD,
    UI_MAX_ZOOM,
    UI_MIN_FPS,
    UI_MIN_SUAVIDAD,
    UI_MIN_ZOOM,
)
from ...infrastructure.audio.sounddevice_audio import HAS_AUDIO, get_system_audio_devices
from .recording_presenter import RecordingPresenter
from .render_thread import RenderThread

if HAS_AUDIO:
    import sounddevice as sd


class FocusApp(QWidget):
    def __init__(self):
        super().__init__()
        self.presenter = RecordingPresenter()
        self.recording_start_time = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_recording_time)
        self.preview_timer = QTimer()
        self.preview_timer.setInterval(50)
        self.preview_timer.timeout.connect(self._update_preview)
        self._disk_tick = 0
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("FocusSee Control Panel")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(360)
        self.setMaximumWidth(360)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        dest_label = QLabel("📁 Carpeta de destino")
        dest_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(dest_label)
        dir_container = QHBoxLayout()
        self.dir_label = QLabel(self._get_video_directory_display())
        self.dir_label.setWordWrap(True)
        self.dir_label.setStyleSheet(
            """
            color: #555;
            font-size: 11px;
            padding: 8px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            """
        )
        dir_container.addWidget(self.dir_label, 1)
        self.change_dir_btn = QPushButton("📂")
        self.change_dir_btn.setFixedWidth(40)
        self.change_dir_btn.setFixedHeight(34)
        self.change_dir_btn.setStyleSheet(
            """
            QPushButton {
                background: #ffc107;
                border: none;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton:hover {
                background: #ffca28;
            }
            QPushButton:disabled {
                background: #e0e0e0;
            }
            """
        )
        self.change_dir_btn.clicked.connect(self._change_output_directory)
        dir_container.addWidget(self.change_dir_btn)
        layout.addLayout(dir_container)

        name_label = QLabel("📝 Nombre del video (opcional)")
        name_label.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 5px;")
        layout.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ej: demo_bot  (vacío = auto)")
        self.name_input.setStyleSheet(
            """
            QLineEdit {
                padding: 8px;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
            }
            QLineEdit:disabled {
                background: #f5f5f5;
                color: #999;
            }
            """
        )
        layout.addWidget(self.name_input)

        export_label = QLabel("🎬 Exportar como")
        export_label.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 5px;")
        layout.addWidget(export_label)

        self.export_group = QButtonGroup(self)
        radio_layout = QHBoxLayout()
        radio_layout.setSpacing(8)

        self.radio_full = QRadioButton("🖥️ Pantalla\ncompleta")
        self.radio_tiktok = QRadioButton("📱 TikTok\n9:16")
        self.radio_both = QRadioButton("📦 Ambos")

        radio_style = """
            QRadioButton {
                font-size: 10px;
                background: white;
                border: 2px solid #ddd;
                border-radius: 6px;
                padding: 10px 8px;
                text-align: center;
            }
            QRadioButton:checked {
                background: #e3f2fd;
                border: 2px solid #2196F3;
                font-weight: bold;
            }
            QRadioButton:hover {
                border-color: #90caf9;
            }
            QRadioButton:disabled {
                background: #f5f5f5;
                color: #999;
            }
            QRadioButton::indicator {
                width: 0px;
                height: 0px;
            }
        """
        self.radio_full.setStyleSheet(radio_style)
        self.radio_tiktok.setStyleSheet(radio_style)
        self.radio_both.setStyleSheet(radio_style)

        self.export_group.addButton(self.radio_full, 0)
        self.export_group.addButton(self.radio_tiktok, 1)
        self.export_group.addButton(self.radio_both, 2)

        ui_state = self.presenter.get_default_ui_state()
        if ui_state["export_mode"] == "full":
            self.radio_full.setChecked(True)
        elif ui_state["export_mode"] == "tiktok":
            self.radio_tiktok.setChecked(True)
        else:
            self.radio_both.setChecked(True)

        radio_layout.addWidget(self.radio_full)
        radio_layout.addWidget(self.radio_tiktok)
        radio_layout.addWidget(self.radio_both)
        layout.addLayout(radio_layout)

        zoom_label = QLabel("🔍 Nivel de Zoom")
        zoom_label.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 5px;")
        layout.addWidget(zoom_label)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(UI_MIN_ZOOM, UI_MAX_ZOOM)
        self.zoom_spin.setValue(ui_state["zoom"])
        self.zoom_spin.setPrefix("x ")
        self.zoom_spin.setSingleStep(2)
        self.zoom_spin.setStyleSheet(
            """
            QSpinBox {
                padding: 8px;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
            }
            QSpinBox:disabled {
                background: #f5f5f5;
                color: #999;
            }
            """
        )
        layout.addWidget(self.zoom_spin)

        smooth_label = QLabel("⚡ Suavidad de Cámara")
        smooth_label.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 5px;")
        layout.addWidget(smooth_label)
        self.smooth_slider = QSlider(Qt.Orientation.Horizontal)
        self.smooth_slider.setRange(UI_MIN_SUAVIDAD, UI_MAX_SUAVIDAD)
        self.smooth_slider.setValue(ui_state["suavidad"])
        self.smooth_slider.setStyleSheet(
            """
            QSlider::groove:horizontal {
                background: #e0e0e0;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #2196F3;
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #1976D2;
            }
            QSlider::sub-page:horizontal {
                background: #90caf9;
                border-radius: 4px;
            }
            """
        )
        layout.addWidget(self.smooth_slider)

        fps_label = QLabel("🎥 FPS del Video")
        fps_label.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 5px;")
        layout.addWidget(fps_label)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(UI_MIN_FPS, UI_MAX_FPS)
        self.fps_spin.setValue(ui_state["fps"])
        self.fps_spin.setStyleSheet(
            """
            QSpinBox {
                padding: 8px;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
            }
            QSpinBox:disabled {
                background: #f5f5f5;
                color: #999;
            }
            """
        )
        layout.addWidget(self.fps_spin)

        audio_label = QLabel("🎙️ Audio")
        audio_label.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 5px;")
        layout.addWidget(audio_label)

        self.audio_mode_combo = QComboBox()
        self.audio_mode_combo.setEnabled(HAS_AUDIO)
        self.audio_mode_combo.addItem("Desactivado", "off")
        self.audio_mode_combo.addItem("Micrófono", "mic")
        self.audio_mode_combo.addItem("Audio del sistema", "system")
        self.audio_mode_combo.addItem("Micrófono + Sistema", "both")
        self.audio_mode_combo.setStyleSheet(
            """
            QComboBox {
                padding: 8px;
                font-size: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
            }
            QComboBox:disabled {
                background: #f5f5f5;
                color: #999;
            }
            """
        )
        if not HAS_AUDIO:
            self.audio_mode_combo.setEnabled(False)
            self.audio_mode_combo.setToolTip("Instala sounddevice para habilitar audio")
        layout.addWidget(self.audio_mode_combo)

        self.mic_device_combo = QComboBox()
        self.mic_device_combo.setVisible(False)
        if HAS_AUDIO:
            self.mic_device_combo.addItem("Mic por defecto", None)
            try:
                for i, d in enumerate(sd.query_devices()):
                    if d["max_input_channels"] > 0:
                        self.mic_device_combo.addItem(d["name"], i)
            except Exception:
                pass
        layout.addWidget(self.mic_device_combo)

        self.sys_device_combo = QComboBox()
        self.sys_device_combo.setVisible(False)
        if HAS_AUDIO:
            sys_devs = get_system_audio_devices()
            if sys_devs:
                self.sys_device_combo.addItem("Sistema por defecto", None)
                for idx, name in sys_devs:
                    self.sys_device_combo.addItem(name, idx)
            else:
                self.sys_device_combo.addItem("No disponible", None)
                self.sys_device_combo.setEnabled(False)
        layout.addWidget(self.sys_device_combo)

        self.audio_mode_combo.currentIndexChanged.connect(self._on_audio_mode_changed)
        saved_audio_mode = ui_state.get("audio_mode", "mic")
        if saved_audio_mode == "off" or (not ui_state.get("audio", False) and saved_audio_mode == "mic"):
            saved_audio_mode = "off"
        mode_index = self.audio_mode_combo.findData(saved_audio_mode)
        if mode_index >= 0:
            self.audio_mode_combo.setCurrentIndex(mode_index)
        self._on_audio_mode_changed()

        self.vu_meter = QProgressBar()
        self.vu_meter.setRange(0, 100)
        self.vu_meter.setValue(0)
        self.vu_meter.setTextVisible(False)
        self.vu_meter.setFixedHeight(10)
        self.vu_meter.setVisible(False)
        self.vu_meter.setStyleSheet(
            """
            QProgressBar { background: #222; border: 1px solid #444; border-radius: 4px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #28a745, stop:0.6 #ffc107, stop:0.85 #dc3545); border-radius: 3px; }
            """
        )
        layout.addWidget(self.vu_meter)

        self.disk_label = QLabel()
        self.disk_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.disk_label.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self.disk_label)
        self._update_disk_info()

        self.preview_label = QLabel("Sin señal")
        self.preview_label.setFixedHeight(180)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "background: #111; color: #666; border: 1px solid #333; border-radius: 4px;"
        )
        layout.addWidget(self.preview_label)

        self.time_counter = QLabel("00:00:00")
        self.time_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_counter.setStyleSheet(
            """
            background: #ffebee;
            color: #c62828;
            font-size: 24px;
            font-weight: bold;
            padding: 10px;
            border-radius: 6px;
            font-family: monospace;
            """
        )
        self.time_counter.setVisible(False)
        layout.addWidget(self.time_counter)

        self.status = QLabel("✓ Listo para grabar")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(50)
        self.status.setStyleSheet(
            """
            color: #4caf50;
            font-size: 12px;
            padding: 10px;
            background: #f1f8f4;
            border-radius: 6px;
            """
        )
        layout.addWidget(self.status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.btn = QPushButton("INICIAR GRABACIÓN")
        self.btn.clicked.connect(self.toggle)
        self.btn.setFixedHeight(50)
        self.btn.setStyleSheet(self._start_button_style())
        layout.addWidget(self.btn)

        scroll = QScrollArea()
        scroll.setWidget(content_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.setLayout(outer)

        screen = QApplication.primaryScreen()
        if screen:
            max_h = int(screen.availableGeometry().height() * 0.9)
            self.setMaximumHeight(max_h)

        self.adjustSize()
        self._center_on_screen()

    def _on_audio_mode_changed(self):
        mode = self.audio_mode_combo.currentData()
        show_mic = mode in ("mic", "both")
        show_sys = mode in ("system", "both")
        self.mic_device_combo.setVisible(show_mic)
        self.sys_device_combo.setVisible(show_sys)

    def _get_video_directory_display(self):
        return self.presenter.get_output_dir_display()

    def _get_export_mode(self):
        return {0: "full", 1: "tiktok", 2: "both"}[self.export_group.checkedId()]

    def _set_controls_enabled(self, enabled):
        for widget in (
            self.zoom_spin,
            self.smooth_slider,
            self.fps_spin,
            self.radio_full,
            self.radio_tiktok,
            self.radio_both,
            self.change_dir_btn,
            self.name_input,
            self.audio_mode_combo,
            self.mic_device_combo,
            self.sys_device_combo,
        ):
            widget.setEnabled(enabled)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            window_geometry = self.frameGeometry()
            window_geometry.moveCenter(screen_geometry.center())
            self.move(window_geometry.topLeft())

    def _update_recording_time(self):
        if self.recording_start_time:
            elapsed = time.time() - self.recording_start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.time_counter.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def _change_output_directory(self):
        current_dir = self.presenter.get_output_dir_display()
        new_dir = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta de destino para videos",
            current_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if new_dir:
            self.presenter.update_output_directory(Path(new_dir))
            self.dir_label.setText(self.presenter.get_output_dir_display())
            self.status.setText(f"✅ Carpeta actualizada:\n{Path(new_dir).name}")
            self.status.setStyleSheet(self._success_status_style())

    def toggle(self):
        if not self.presenter.has_active_recording():
            self._set_controls_enabled(False)

            try:
                audio_mode = self.audio_mode_combo.currentData()
                audio_enabled = audio_mode != "off"
                view_model = self.presenter.start_recording(
                    zoom=self.zoom_spin.value(),
                    suavidad=self.smooth_slider.value(),
                    fps=self.fps_spin.value(),
                    custom_name=self.name_input.text().strip(),
                    audio=audio_enabled,
                    audio_device=self.mic_device_combo.currentData() if audio_mode in ("mic", "both") else None,
                    audio_mode=audio_mode if audio_enabled else "mic",
                    system_audio_device=self.sys_device_combo.currentData() if audio_mode in ("system", "both") else None,
                )
            except RecordingEnvironmentError as exc:
                self._set_controls_enabled(True)
                self.status.setText(f"❌ {exc}")
                self.status.setStyleSheet(self._error_status_style())
                return
            except Exception as exc:
                self._set_controls_enabled(True)
                self.status.setText(f"❌ Error inesperado al iniciar: {exc}")
                self.status.setStyleSheet(self._error_status_style())
                return

            self.recording_start_time = time.time()
            self.timer.start(100)
            self.preview_timer.start()
            if audio_enabled:
                self.vu_meter.setVisible(True)
            self.time_counter.setVisible(True)
            self.time_counter.setText("00:00:00")
            self.btn.setText(view_model.button_text)
            self.btn.setStyleSheet(self._stop_button_style())
            self.status.setText(view_model.status_text)
            self.status.setStyleSheet(self._recording_status_style())
            return

        self.timer.stop()
        self.preview_timer.stop()
        self.vu_meter.setVisible(False)
        self.preview_label.setText("Procesando...")
        self.time_counter.setVisible(False)
        self.recording_start_time = None
        self.btn.setEnabled(False)
        mode = self._get_export_mode()
        self.presenter.save_current_preferences(
            zoom=self.zoom_spin.value(),
            suavidad=self.smooth_slider.value(),
            fps=self.fps_spin.value(),
            export_mode=mode,
        )
        render_view_model = self.presenter.build_rendering_view_model(mode)
        self.status.setText(render_view_model.status_text)
        self.status.setStyleSheet(self._rendering_status_style())
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.render_thread = RenderThread(self.presenter, export_mode=mode)
        self.render_thread.progress.connect(self.progress_bar.setValue)
        self.render_thread.finished.connect(self.on_finished)
        self.render_thread.start()

    def on_finished(self, result):
        self.timer.stop()
        self.time_counter.setVisible(False)
        self.recording_start_time = None
        self.btn.setEnabled(True)
        view_model = self.presenter.build_finished_view_model(result)
        self.btn.setText(view_model.button_text)
        self.btn.setStyleSheet(self._start_button_style())
        self.status.setText(view_model.status_text)
        self.status.setStyleSheet(self._success_status_style())

        self.progress_bar.setVisible(False)
        self.preview_label.setText("Sin señal")
        self._update_disk_info()
        self._set_controls_enabled(True)
        self.presenter.reveal_output_directory()

    def _update_preview(self):
        recorder = self.presenter.recorder
        if recorder is None:
            return
        mode = self._get_export_mode()
        frame = recorder.preview_frame_tiktok if mode == "tiktok" else recorder.preview_frame
        if frame is not None:
            h, w, ch = frame.shape
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = QImage(frame_rgb.data, w, h, w * ch, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(img).scaled(
                self.preview_label.width(),
                self.preview_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self.preview_label.setPixmap(pixmap)

        audio_mode = self.audio_mode_combo.currentData()
        if audio_mode and audio_mode != "off":
            self.vu_meter.setValue(recorder.audio_level)

        self._disk_tick += 1
        if self._disk_tick >= 20:
            self._disk_tick = 0
            self._update_disk_info()

    def _update_disk_info(self):
        output_dir = self.presenter.get_output_dir_display()
        drive = os.path.splitdrive(output_dir)[0] or "/"
        try:
            free_gb = shutil.disk_usage(drive).free / 1024 ** 3
        except OSError:
            free_gb = 0.0

        temp_mb = 0.0
        recorder = self.presenter.recorder
        if recorder is not None and recorder._temp_path:
            try:
                temp_mb = os.path.getsize(recorder._temp_path) / 1024 ** 2
            except OSError:
                pass

        if free_gb < 0.5:
            color = "#dc3545"
        elif free_gb < 2.0:
            color = "#ffc107"
        else:
            color = "#888"

        self.disk_label.setStyleSheet(f"font-size: 11px; color: {color};")
        if temp_mb > 0:
            self.disk_label.setText(f"💾 Temp: {temp_mb:.0f} MB  |  Libre: {free_gb:.1f} GB")
        else:
            self.disk_label.setText(f"💾 Disco libre: {free_gb:.1f} GB")

    @staticmethod
    def _start_button_style():
        return """
            QPushButton {
                background: #4caf50;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #45a049;
            }
            QPushButton:pressed {
                background: #3d8b40;
            }
            QPushButton:disabled {
                background: #cccccc;
            }
        """

    @staticmethod
    def _stop_button_style():
        return """
            QPushButton {
                background: #f44336;
                color: white;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #d32f2f;
            }
            QPushButton:pressed {
                background: #b71c1c;
            }
            QPushButton:disabled {
                background: #cccccc;
            }
        """

    @staticmethod
    def _error_status_style():
        return """
            color: #d32f2f;
            font-size: 11px;
            padding: 10px;
            background: #ffebee;
            border-radius: 6px;
        """

    @staticmethod
    def _recording_status_style():
        return """
            color: #d32f2f;
            font-size: 11px;
            padding: 10px;
            background: white;
            border-radius: 6px;
        """

    @staticmethod
    def _rendering_status_style():
        return """
            color: #1976d2;
            font-size: 11px;
            padding: 10px;
            background: #e3f2fd;
            border-radius: 6px;
        """

    @staticmethod
    def _success_status_style():
        return """
            color: #2e7d32;
            font-size: 11px;
            padding: 10px;
            background: #e8f5e9;
            border-radius: 6px;
        """
