"""Face presence via MediaPipe's lightweight face detector.

Returns the count of faces detected on a single JPEG. Lazy singleton.
"""
from __future__ import annotations

import io
import os
import threading
import urllib.request
from pathlib import Path
from typing import Optional

_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"


def _model_path() -> Path:
    from ..paths import models_dir
    return models_dir() / "blaze_face_short_range.tflite"


def _ensure_model() -> str:
    p = _model_path()
    if p.exists():
        return str(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(_MODEL_URL, str(p))
    return str(p)


class FaceModel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detector = None

    def _load(self) -> None:
        if self._detector is not None:
            return
        with self._lock:
            if self._detector is not None:
                return
            import mediapipe as mp
            model_file = _ensure_model()
            base_options = mp.tasks.BaseOptions(model_asset_path=model_file)
            options = mp.tasks.vision.FaceDetectorOptions(
                base_options=base_options,
                min_detection_confidence=0.5,
            )
            self._detector = mp.tasks.vision.FaceDetector.create_from_options(options)

    def detect_count(self, jpeg_bytes: bytes) -> int:
        self._load()
        assert self._detector is not None
        try:
            import numpy as np
            import mediapipe as mp
            from PIL import Image
        except ImportError:
            return 0
        try:
            img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
            arr = np.asarray(img)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
        except Exception:
            return 0
        result = self._detector.detect(mp_image)
        if not result or not result.detections:
            return 0
        return len(result.detections)


_lock = threading.Lock()
_singleton: Optional[FaceModel] = None


def get_model() -> FaceModel:
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is None:
            _singleton = FaceModel()
    return _singleton


def max_face_count(jpegs: list[bytes]) -> int:
    m = get_model()
    best = 0
    for j in jpegs:
        try:
            n = m.detect_count(j)
        except Exception:
            n = 0
        if n > best:
            best = n
    return best
