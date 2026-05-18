"""Cheap visual-motion score = mean inter-frame mean-abs-diff over sampled JPEGs.

Output is normalized 0..1 (clipped). Static shots (wall, ceiling, parked car)
score near 0; lively shots > 0.05 typically.
"""
from __future__ import annotations

import io


def motion_score(jpegs: list[bytes], down: int = 96) -> float:
    if len(jpegs) < 2:
        return 0.0
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return 0.0

    grays = []
    for j in jpegs:
        try:
            img = Image.open(io.BytesIO(j)).convert("L")
            img = img.resize((down, down), Image.BILINEAR)
            grays.append(np.asarray(img, dtype=np.float32))
        except Exception:
            continue
    if len(grays) < 2:
        return 0.0

    diffs = []
    for a, b in zip(grays[:-1], grays[1:]):
        d = np.abs(a - b).mean() / 255.0
        diffs.append(float(d))
    if not diffs:
        return 0.0
    return min(1.0, sum(diffs) / len(diffs))
