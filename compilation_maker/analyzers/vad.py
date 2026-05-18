"""Voice activity detection via Silero VAD.

Pulls 16kHz mono PCM via ffmpeg, runs the silero-vad ONNX model, returns the
fraction of audio classified as speech (0.0..1.0).

If the file has no audio track, returns 0.0 and sets `had_audio` to False.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG = "ffmpeg"


_SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


class VADModel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._get_speech_timestamps = None
        self._device: str = "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from .device import get_torch_device
            self._device = get_torch_device()
            try:
                from silero_vad import load_silero_vad, get_speech_timestamps  # type: ignore
                self._model = load_silero_vad(onnx=True)
                self._get_speech_timestamps = get_speech_timestamps
            except Exception as e:
                raise RuntimeError(f"silero-vad not available: {e}")

    def speech_fraction(self, path: Path) -> tuple[float, bool]:
        """Return (fraction_of_audio_with_speech, had_audio)."""
        pcm = _extract_pcm(path)
        if pcm is None or len(pcm) < 16000 * 2:
            return 0.0, pcm is not None and len(pcm) > 0

        self._load()
        try:
            import numpy as np
            import torch
        except ImportError:
            return 0.0, True

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio).to(self._device)
        try:
            stamps = self._get_speech_timestamps(tensor, self._model, sampling_rate=16000)  # type: ignore
        except Exception:
            return 0.0, True
        speech_samples = sum(s["end"] - s["start"] for s in stamps)
        total_samples = audio.shape[0]
        if total_samples == 0:
            return 0.0, True
        return min(1.0, speech_samples / total_samples), True


def _extract_pcm(path: Path) -> Optional[bytes]:
    """16 kHz, mono, signed 16-bit little-endian PCM via ffmpeg."""
    cmd = [
        _FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(path),
        "-vn",
        "-ac", "1", "-ar", "16000",
        "-f", "s16le",
        "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=_SUBPROCESS_FLAGS)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


_lock = threading.Lock()
_singleton: Optional[VADModel] = None


def get_model() -> VADModel:
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is None:
            _singleton = VADModel()
    return _singleton
