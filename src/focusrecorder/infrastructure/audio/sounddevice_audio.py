import wave

import numpy as np

HAS_AUDIO = False
try:
    import sounddevice as sd
    HAS_AUDIO = True
except ImportError:
    pass


class SounddeviceAudioRecorder:
    SAMPLERATE = 48000
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
