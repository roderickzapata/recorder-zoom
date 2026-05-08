import wave

import numpy as np

HAS_AUDIO = False
try:
    import sounddevice as sd
    HAS_AUDIO = True
except ImportError:
    pass


class SounddeviceAudioRecorder:
    def __init__(self, device=None):
        self.device = device
        self._frames = []
        self._level = 0
        self._stream = None
        self._actual_samplerate = 44100
        self._actual_channels = 1

    @property
    def level(self) -> int:
        return self._level

    def start(self):
        if not HAS_AUDIO:
            return
        
        # Detectar capacidades del dispositivo
        try:
            device_info = sd.query_devices(self.device, 'input')
            self._actual_samplerate = int(device_info['default_samplerate'])
            self._actual_channels = min(device_info['max_input_channels'], 2)
        except Exception:
            self._actual_samplerate = 48000
            self._actual_channels = 1

        self._frames = []
        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self._actual_samplerate,
            channels=self._actual_channels,
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
            wf.setnchannels(self._actual_channels)
            wf.setsampwidth(2)
            wf.setframerate(self._actual_samplerate)
            wf.writeframes(audio_data.tobytes())

        return output_path

    def _callback(self, indata, frames, time, status):
        self._frames.append(indata.copy())
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        self._level = min(int(rms / 32768 * 1000), 100)
