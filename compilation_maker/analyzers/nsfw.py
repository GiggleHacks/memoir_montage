"""NudeNet wrapper. Lazy singleton with GPU support and batch inference."""
from __future__ import annotations

import threading
from typing import Optional


NSFW_LABELS = frozenset({
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
})


class NudityModel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detector = None

    def _load(self) -> None:
        if self._detector is not None:
            return
        with self._lock:
            if self._detector is not None:
                return
            from nudenet import NudeDetector  # type: ignore
            from .device import get_onnx_providers
            self._detector = NudeDetector(providers=get_onnx_providers())

    def score_jpeg(self, jpeg_bytes: bytes) -> float:
        self._load()
        assert self._detector is not None
        detections = self._detector.detect(jpeg_bytes)
        if not detections:
            return 0.0
        scores = [d["score"] for d in detections if d.get("class") in NSFW_LABELS]
        return max(scores) if scores else 0.0

    def score_batch(self, jpegs: list[bytes]) -> list[float]:
        self._load()
        assert self._detector is not None
        results: list[float] = []
        for jpeg in jpegs:
            try:
                detections = self._detector.detect(jpeg)
                if not detections:
                    results.append(0.0)
                else:
                    scores = [d["score"] for d in detections if d.get("class") in NSFW_LABELS]
                    results.append(max(scores) if scores else 0.0)
            except Exception:
                results.append(0.0)
        return results


_singleton_lock = threading.Lock()
_singleton: Optional[NudityModel] = None


def get_model() -> NudityModel:
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = NudityModel()
    return _singleton


def reduce_nsfw(scores: list[float], soft_threshold: float = 0.5) -> tuple[float, int]:
    """Return (peak, soft_count) across a list of per-frame scores."""
    if not scores:
        return 0.0, 0
    peak = max(scores)
    soft = sum(1 for s in scores if s >= soft_threshold)
    return peak, soft
