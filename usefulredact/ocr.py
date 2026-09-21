"""ocr.py — OCR backend (RapidOCR / ONNX Runtime, CPU).

Taken from UsefulText (tuoa-tools/usefultext, same author, MIT) and kept in
step with it; only the environment variable name differs. The API:

  available() / import_error()      lazy singleton engine, never crashes
  OcrRegion(text, conf, quad)       one detected line, with its box
  OcrPageResult(text, mean_conf, n_regions, regions, dropped_regions)
                                    with .low_confidence
  ocr_image(img) / ocr_pdf_page(page) / ocr_image_file(path)

Design:
  - Models load once per process, on first use.
  - Every result carries a mean confidence so callers can gate on quality.
    Confidence is the engine's certainty ("read quality"), never "accuracy".
  - Regions under OCR_REGION_MIN_CONF are dropped and counted, not silently
    lost: text under a marker stroke often reads as low-confidence garbage.
  - Fully offline: the default models ship inside the rapidocr wheel; nothing
    is fetched at run time. USEFULREDACT_MODEL_DIR overrides the model folder
    (the hook a packaged build would use).

Tuning:
  OCR_DPI              render resolution for PDF pages (200 = speed/quality
                       sweet spot; raise to 300 if small print misses)
  OCR_MIN_CONF         per-page mean confidence below which the page is treated
                       as unreliably read (silent-failure gate)
  OCR_REGION_MIN_CONF  per-region confidence below which a region is dropped
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

OCR_DPI = 200
OCR_MIN_CONF = 0.70
OCR_REGION_MIN_CONF = 0.5

_engine = None
_import_error: str | None = None
_lock = threading.Lock()


def _engine_params() -> dict[str, Any]:
    params: dict[str, Any] = {
        "Global.use_cls": True,  # per-line 180° flips
        "Global.log_level": "warning",
    }
    model_dir = os.environ.get("USEFULREDACT_MODEL_DIR")
    if model_dir:
        params["Global.model_root_dir"] = model_dir
    return params


def available() -> bool:
    """Load the engine on first call. False (never raises) if it can't."""
    global _engine, _import_error
    if _engine is not None:
        return True
    if _import_error is not None:
        return False
    with _lock:
        if _engine is not None:
            return True
        try:
            from rapidocr import RapidOCR

            _engine = RapidOCR(params=_engine_params())
            return True
        except Exception as exc:  # not installed, or model load failed
            _import_error = repr(exc)
            return False


def import_error() -> str | None:
    return _import_error


def _ensure_engine():
    if not available():
        raise RuntimeError(f"OCR engine unavailable: {_import_error}")
    return _engine


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class OcrRegion:
    """One detected text line. `quad` is [tl, tr, br, bl] in pixel coordinates
    of the image handed to the engine (RapidOCR maps boxes back to the input)."""

    text: str
    conf: float
    quad: list[list[float]]
    flipped: bool = False  # the angle classifier turned this line 180°

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.quad]
        ys = [p[1] for p in self.quad]
        return (min(xs), min(ys), max(xs), max(ys))

    def _edge_pair_lengths(self) -> tuple[float, float]:
        """(horizontal-ish edge length, vertical-ish edge length).

        RapidOCR's corner order is [tl, tr, br, bl] for horizontal lines but
        flips for tilted vertical ones, so width/height are chosen by which
        edge pair lies closer to the x-axis rather than by corner index."""
        q = self.quad
        a_len = (_dist(q[0], q[1]) + _dist(q[3], q[2])) / 2  # edges p0→p1, p3→p2
        b_len = (_dist(q[0], q[3]) + _dist(q[1], q[2])) / 2  # edges p0→p3, p1→p2
        a_dx = abs(q[1][0] - q[0][0]) + abs(q[2][0] - q[3][0])
        b_dx = abs(q[3][0] - q[0][0]) + abs(q[2][0] - q[1][0])
        # Compare |cos| of each edge pair with the x-axis.
        a_horiz = a_dx / (2 * a_len) if a_len else 0.0
        b_horiz = b_dx / (2 * b_len) if b_len else 0.0
        return (a_len, b_len) if a_horiz >= b_horiz else (b_len, a_len)

    @property
    def width(self) -> float:  # extent along the text direction (horizontal-ish)
        return self._edge_pair_lengths()[0]

    @property
    def height(self) -> float:  # extent across the text (vertical-ish) — tilt-tolerant
        return self._edge_pair_lengths()[1]

    @property
    def cx(self) -> float:
        return sum(p[0] for p in self.quad) / 4

    @property
    def cy(self) -> float:
        return sum(p[1] for p in self.quad) / 4

    @property
    def area(self) -> float:
        return self.width * self.height

    def scaled(self, factor: float) -> OcrRegion:
        return OcrRegion(
            self.text, self.conf, [[x * factor, y * factor] for x, y in self.quad], self.flipped
        )

    def to_dict(self) -> dict:
        x0, y0, x1, y1 = self.bbox
        return {
            "text": self.text,
            "conf": round(self.conf, 4),
            "bbox": [round(x0), round(y0), round(x1), round(y1)],
            "quad": [[round(x, 1), round(y, 1)] for x, y in self.quad],
        }

    @classmethod
    def from_dict(cls, d: dict) -> OcrRegion:
        return cls(
            text=d["text"], conf=float(d["conf"]), quad=[list(map(float, p)) for p in d["quad"]]
        )


@dataclass
class OcrPageResult:
    text: str
    mean_conf: float
    n_regions: int
    regions: list[OcrRegion] = field(default_factory=list)
    dropped_regions: int = 0  # below OCR_REGION_MIN_CONF (or caller's value)
    elapsed: float = 0.0
    flipped_fraction: float = 0.0  # share of lines the angle classifier turned 180°
    # (≈0 on an upright page, ≈0.9 on an upside-down one)

    @property
    def low_confidence(self) -> bool:
        # No regions on a page we believed held content is itself suspect;
        # the caller decides whether blank-is-plausible.
        return self.n_regions > 0 and self.mean_conf < OCR_MIN_CONF

    @property
    def score(self) -> float:
        """How much the engine read: regions × mean confidence."""
        return self.n_regions * self.mean_conf


# --------------------------------------------------------------------------- #
# Running the engine
# --------------------------------------------------------------------------- #
def _to_engine_input(source):
    """PIL images become BGR arrays (what RapidOCR expects for ndarrays);
    ndarrays are passed through and assumed BGR; paths/bytes go straight in."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        Image = None
    if Image is not None and isinstance(source, Image.Image):
        rgb = np.asarray(source.convert("RGB"))
        return np.ascontiguousarray(rgb[:, :, ::-1])
    return source


CLS_THRESH = 0.9  # RapidOCR only applies a 180° flip above this classifier score


def _call_engine(engine, img, kwargs: dict):
    """Run the engine and also return the per-line angle-classifier labels,
    aligned with the returned boxes.

    RapidOCR's public __call__ discards the classifier output, but its steps
    are ordinary methods, so run them here and keep cls_res. The labels tell
    whether the whole page is upside down (most lines flipped) at zero extra
    cost, and which single lines were flipped (occasionally wrongly). Falls
    back to the plain call if a future version renames things."""
    needed = ("update_params", "load_img", "preprocess_img", "run_ocr_steps", "build_final_output")
    if not all(hasattr(engine, n) for n in needed):
        return engine(img, **kwargs), None
    try:
        engine.update_params(**kwargs)
        ori_img = engine.load_img(img)
        pre_img, op_record = engine.preprocess_img(ori_img)
        det_res, cls_res, rec_res, crops = engine.run_ocr_steps(pre_img, op_record)
        labels = list(getattr(cls_res, "cls_res", None) or [])
        # build_final_output drops empty-text lines; keep labels aligned by
        # pairing them with the recogniser output before that filter.
        txts_before = list(getattr(rec_res, "txts", None) or [])
        result = engine.build_final_output(ori_img, det_res, cls_res, rec_res, crops, op_record)
        if labels and len(labels) == len(txts_before):
            labels = [
                lbl for lbl, txt in zip(labels, txts_before, strict=True) if txt and txt.strip()
            ]
            if len(labels) != len(getattr(result, "txts", None) or []):
                labels = None
        else:
            labels = None
        return result, labels
    except Exception:
        return engine(img, **kwargs), None


def _flipped_fraction(cls_labels) -> float:
    if not cls_labels:
        return 0.0
    decided = [(str(lbl), float(score)) for lbl, score in cls_labels if float(score) >= CLS_THRESH]
    if not decided:
        return 0.0
    return sum(1 for lbl, _ in decided if lbl == "180") / len(decided)


def _is_flip(label) -> bool:
    try:
        return str(label[0]) == "180" and float(label[1]) >= CLS_THRESH
    except Exception:
        return False


def _second_opinion(engine, source, region: OcrRegion, kwargs: dict) -> OcrRegion:
    """Re-read one line's crop with the angle classifier off; return whichever
    read the recogniser is more confident about."""
    try:
        from PIL import Image

        if isinstance(source, Image.Image):
            img = source
        elif isinstance(source, np.ndarray):
            img = Image.fromarray(np.ascontiguousarray(source[:, :, ::-1]))
        else:
            return region
        x0, y0, x1, y1 = region.bbox
        pad = max(4.0, 0.3 * region.height)
        crop = img.crop(
            (
                max(0, int(x0 - pad)),
                max(0, int(y0 - pad)),
                min(img.width, int(x1 + pad)),
                min(img.height, int(y1 + pad)),
            )
        )
        alt = engine(_to_engine_input(crop), **dict(kwargs, use_cls=False))
        txts = list(getattr(alt, "txts", None) or [])
        scores = list(getattr(alt, "scores", None) or [])
        if not txts:
            return region
        best = max(range(len(txts)), key=lambda i: scores[i])
        if scores[best] > region.conf and txts[best].strip():
            return OcrRegion(
                text=txts[best].strip(), conf=float(scores[best]), quad=region.quad, flipped=False
            )
    except Exception:
        pass
    return region


def _run(
    source,
    *,
    use_cls: bool = True,
    min_region_conf: float = OCR_REGION_MIN_CONF,
    box_thresh: float | None = None,
    second_opinion: bool = True,
) -> OcrPageResult:
    engine = _ensure_engine()
    # Every flag is passed explicitly: RapidOCR keeps per-call flags from one
    # call to the next, so an omitted flag silently inherits the last value.
    # text_score=0 so the region filter happens here, where it can be counted.
    kwargs = dict(use_det=True, use_cls=use_cls, use_rec=True, text_score=0.0)
    if box_thresh is not None:
        kwargs["box_thresh"] = box_thresh
    result, cls_labels = _call_engine(engine, _to_engine_input(source), kwargs)
    boxes = getattr(result, "boxes", None)
    txts = list(getattr(result, "txts", None) or [])
    scores = list(getattr(result, "scores", None) or [])
    boxes = list(boxes) if boxes is not None else [None] * len(txts)

    flags = [_is_flip(lbl) for lbl in cls_labels] if cls_labels else [False] * len(txts)
    flipped_fraction = _flipped_fraction(cls_labels) if use_cls else 0.0

    candidates: list[OcrRegion] = []
    # Lengths were reconciled above; a mismatch must never raise mid-page.
    for box, txt, score, flipped in zip(boxes, txts, scores, flags, strict=False):
        if not txt or not txt.strip():
            continue
        quad = [[float(x), float(y)] for x, y in box] if box is not None else [[0.0, 0.0]] * 4
        candidates.append(
            OcrRegion(text=txt.strip(), conf=float(score), quad=quad, flipped=flipped)
        )

    if second_opinion and use_cls and 0 < flipped_fraction < 0.5:
        # A few lines flipped on an otherwise upright page are usually the
        # classifier's mistake, which turns a clean line into garbage. Re-read
        # just those lines with the classifier off and keep the better read.
        for i, r in enumerate(candidates):
            if r.flipped:
                candidates[i] = _second_opinion(engine, source, r, kwargs)

    regions: list[OcrRegion] = []
    dropped = 0
    for r in candidates:
        if r.conf < min_region_conf:
            dropped += 1
        else:
            regions.append(r)

    text = "\n".join(r.text for r in regions)
    mean_conf = (sum(r.conf for r in regions) / len(regions)) if regions else 0.0
    elapsed = getattr(result, "elapse", 0.0) or 0.0
    return OcrPageResult(
        text=text,
        mean_conf=mean_conf,
        n_regions=len(regions),
        regions=regions,
        dropped_regions=dropped,
        elapsed=float(elapsed),
        flipped_fraction=flipped_fraction,
    )


def ocr_image(
    img,
    *,
    use_cls: bool = True,
    min_region_conf: float = OCR_REGION_MIN_CONF,
    box_thresh: float | None = None,
) -> OcrPageResult:
    """OCR an in-memory image (PIL.Image, or an ndarray in BGR order).

    box_thresh overrides the detector's box threshold (engine default 0.5);
    curved lines near a book's gutter/top need ~0.4 to be found at all."""
    return _run(img, use_cls=use_cls, min_region_conf=min_region_conf, box_thresh=box_thresh)


def ocr_pdf_page(page) -> OcrPageResult:
    """OCR a PyMuPDF page by rendering it to an image first."""
    pix = page.get_pixmap(dpi=OCR_DPI)
    return _run(pix.tobytes("png"), box_thresh=0.5)


def ocr_image_file(path) -> OcrPageResult:
    """OCR a standalone image file (png/jpg/tiff/...)."""
    return _run(str(path), box_thresh=0.5)
