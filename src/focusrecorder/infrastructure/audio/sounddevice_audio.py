import wave

import numpy as np

HAS_AUDIO = False
try:
    import sounddevice as sd
    HAS_AUDIO = True
except ImportError:
    pass


def get_mic_devices() -> list[tuple[int, str]]:
    if not HAS_AUDIO:
        return []
    devices = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append((i, d["name"]))
    except Exception:
        pass
    return devices


def get_system_audio_devices() -> list[tuple[int, str]]:
    if not HAS_AUDIO:
        return []
    wasapi_idx = None
    try:
        for i, api in enumerate(sd.query_hostapis()):
            if "wasapi" in api["name"].lower():
                wasapi_idx = i
                break
    except Exception:
        return []
    if wasapi_idx is None:
        return []
    devices = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
                devices.append((i, d["name"]))
    except Exception:
        pass
    return devices


def mix_wav_files(path_a: str, path_b: str, output_path: str) -> str:
    data_a, sr_a, ch_a = _read_wav(path_a)
    data_b, sr_b, ch_b = _read_wav(path_b)
    sr = sr_a or sr_b or 44100
    if data_a is None and data_b is None:
        raise ValueError("Both WAV files are empty")
    if data_a is None:
        _write_wav(output_path, data_b, sr)
        return output_path
    if data_b is None:
        _write_wav(output_path, data_a, sr)
        return output_path
    max_len = max(len(data_a), len(data_b))
    if len(data_a) < max_len:
        data_a = np.pad(data_a, (0, max_len - len(data_a)))
    if len(data_b) < max_len:
        data_b = np.pad(data_b, (0, max_len - len(data_b)))
    mixed = data_a.astype(np.float64) + data_b.astype(np.float64)
    peak = np.max(np.abs(mixed))
    if peak > 32767:
        mixed = mixed * (32767.0 / peak)
    mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
    _write_wav(output_path, mixed, sr)
    return output_path


def _read_wav(path: str) -> tuple[np.ndarray | None, int, int]:
    try:
        with wave.open(path, "r") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
        if ch > 1:
            data = data.reshape(-1, ch).mean(axis=1)
        return data, sr, ch
    except Exception:
        return None, 0, 0


def _write_wav(path: str, data: np.ndarray, samplerate: int) -> None:
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(data.astype(np.int16).tobytes())


class SounddeviceAudioRecorder:
    SAMPLERATE = 44100
    CHANNELS = 1

    def __init__(self, device=None):
        self.device = device
        self._frames = []
        self._level = 0
        self._stream = None

    @property
    def level(self) -> int:
        return self._level

    def start(self):
        if not HAS_AUDIO:
            return
        self._frames = []
        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.SAMPLERATE,
            channels=self.CHANNELS,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self, output_path: str) -> str | None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return None

        audio_data = np.concatenate(self._frames, axis=0)
        with wave.open(output_path, "w") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(self.SAMPLERATE)
            wf.writeframes(audio_data.tobytes())

        return output_path

    def _callback(self, indata, frames, time, status):
        self._frames.append(indata.copy())
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        self._level = min(int(rms / 32768 * 1000), 100)
