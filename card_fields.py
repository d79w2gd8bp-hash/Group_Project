"""Locate and crop the handwritten fields (name / father's name / NRC number) on an old-style
Myanmar NRC card, without any trained model.

The printed label "ဖခင်အမည်" is found by multi-scale template matching. Every other field sits at a
fixed offset from that label (measured in label widths), so the crops follow the card's scale and
position in the photo.
"""
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "label_father.png"
CHECK_PATH = Path(__file__).resolve().parent / "assets" / "label_birth.png"   # second label, used to confirm the layout
CHECK_OFFSET = (5, 115)   # check-label position relative to the father label, in template pixels
CHECK_MIN_SCORE = 0.35
WORK_SIZE = 1400          # longest image side used for matching
MIN_SCORE = 0.5           # below this the label was not found reliably
ROW_PITCH = 0.41          # distance between field rows, in label widths

_template_cache: Optional[np.ndarray] = None


def _enhance(gray: np.ndarray) -> np.ndarray:
    """Dark-stroke map that is robust to uneven light and the pink guilloche pattern."""
    gray = cv2.createCLAHE(3.0, (4, 4)).apply(gray)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    return cv2.GaussianBlur(cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel), (3, 3), 0)


def _template() -> Optional[np.ndarray]:
    global _template_cache
    if _template_cache is None and TEMPLATE_PATH.exists():
        _template_cache = cv2.imread(str(TEMPLATE_PATH), cv2.IMREAD_GRAYSCALE)
    return _template_cache


def _confirm_layout(work_map: np.ndarray, x: int, y: int, scale: float) -> bool:
    """A second printed label ("မွေးသက္ကရာဇ်") must sit just below the first one, at the same scale."""
    check = cv2.imread(str(CHECK_PATH), cv2.IMREAD_GRAYSCALE) if CHECK_PATH.exists() else None
    if check is None:
        return True
    resized = cv2.resize(check, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = resized.shape
    margin = max(8, int(40 * scale))
    ex, ey = x + int(CHECK_OFFSET[0] * scale), y + int(CHECK_OFFSET[1] * scale)
    x0, y0 = max(0, ex - margin), max(0, ey - margin)
    window = work_map[y0:ey + h + margin, x0:ex + w + margin]
    if window.shape[0] <= h or window.shape[1] <= w:
        return False
    result = cv2.matchTemplate(window, _enhance(resized), cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1]) >= CHECK_MIN_SCORE


def find_father_label(image: np.ndarray) -> Optional[Tuple[float, Tuple[float, float, float, float]]]:
    """Return (score, (x, y, w, h)) of the "ဖခင်အမည်" label in original-image pixels, or None."""
    template = _template()
    if template is None or image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    ratio = WORK_SIZE / max(gray.shape)
    work = cv2.resize(gray, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA)
    work_map = _enhance(work)

    best = None
    for scale in np.geomspace(0.25, 1.6, 40):
        resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        h, w = resized.shape
        if h < 12 or h >= work_map.shape[0] or w >= work_map.shape[1]:
            continue
        result = cv2.matchTemplate(work_map, _enhance(resized), cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if best is None or score > best[0]:
            best = (float(score), loc, (w, h), float(scale))
    if best is None:
        return None
    score, (x, y), (w, h), scale = best
    if not _confirm_layout(work_map, x, y, scale):
        return None
    return score, (x / ratio, y / ratio, w / ratio, h / ratio)

def crop_fields(image: np.ndarray) -> Dict[str, np.ndarray]:
    """Crops keyed by "name", "father_name", "id_number". Empty dict if the card layout isn't found."""
    found = find_father_label(image)
    if not found or found[0] < MIN_SCORE:
        return {}
    _, (lx, ly, lw, lh) = found
    pitch = ROW_PITCH * lw
    father_center = ly + lh / 2
    height, width = image.shape[:2]

    # (row offset in pitches, start x, label widths from label.left)
    layout = {
        "id_number": (-3, 0.58),
        "name": (-1, 1.05),
        "father_name": (0, 1.10),
    }
    crops: Dict[str, np.ndarray] = {}
    for key, (row, x_start) in layout.items():
        center = father_center + row * pitch
        x0 = int(max(0, lx + x_start * lw))
        x1 = int(min(width, lx + 4.4 * lw))
        y0 = int(max(0, center - 0.62 * pitch))
        y1 = int(min(height, center + 0.62 * pitch))
        if x1 - x0 > 20 and y1 - y0 > 10:
            crops[key] = image[y0:y1, x0:x1].copy()
    return crops


def ink_view(crop: np.ndarray) -> np.ndarray:
    """High-contrast black-on-white version of a crop (handwriting only) for OCR/preview."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(2.0, (4, 4)).apply(gray)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(9, crop.shape[0] // 3) | 1,) * 2)
    strokes = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    _, binary = cv2.threshold(strokes, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return 255 - binary
