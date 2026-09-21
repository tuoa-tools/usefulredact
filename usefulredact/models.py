"""The result model: findings, pages, documents, and how a verdict is reached.

Boxes are (x0, y0, x1, y1) in page units with the origin at the top left. For a
PDF the unit is the point; for a standalone image it is the pixel. Every page
records its own width and height in the same unit, so a viewer can scale a box
to whatever size it draws the page at.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

Box = tuple[float, float, float, float]

# Verdicts, most serious first. NOT_CHECKED is not a verdict about the document:
# it says the file could not be read, and must never be mistaken for a pass.
FAIL_RECOVERABLE = "FAIL_RECOVERABLE"
PI_VISIBLE = "PI_VISIBLE"
REVIEW_LOW_CONFIDENCE = "REVIEW_LOW_CONFIDENCE"
NO_ISSUES_FOUND = "NO_ISSUES_FOUND"
NOT_CHECKED = "NOT_CHECKED"

VERDICT_ORDER = [
    FAIL_RECOVERABLE,
    PI_VISIBLE,
    REVIEW_LOW_CONFIDENCE,
    NOT_CHECKED,
    NO_ISSUES_FOUND,
]

VERDICT_MEANING = {
    FAIL_RECOVERABLE: "Text is still extractable under a redaction mark",
    PI_VISIBLE: "Personal information detected in visible or OCR-readable text",
    REVIEW_LOW_CONFIDENCE: "OCR confidence too low to assess; needs a human look",
    NO_ISSUES_FOUND: "Nothing detected - not a guarantee",
    NOT_CHECKED: "The file could not be read, so nothing was checked",
}

# Finding kinds.
RECOVERABLE = "recoverable"  # text extractable under a mark, or extractable but not rendered
PI = "pi"  # personal information a detector matched
CONTEXT = "context"  # shown and exported, but does not change the verdict on its own
LOW_CONFIDENCE = "low_confidence"  # a page the OCR engine read poorly

# Where the text of a finding came from.
TEXT_LAYER = "text_layer"
OCR = "ocr"
OCR_ENHANCED = "ocr_enhanced"  # read only after the contrast of the scan was stretched
METADATA = "metadata"
FORM_FIELD = "form_field"


@dataclass
class Finding:
    page: int  # 1-based; 0 means the document itself (metadata)
    kind: str
    detector: str
    text: str  # what was matched, or what was recovered from under the mark
    bbox: Box | None = None  # the box round the whole finding
    boxes: list[Box] = field(default_factory=list)  # one box per line, for drawing
    source: str = TEXT_LAYER
    detail: str = ""
    score: float | None = None  # fuzzy-match score or OCR confidence, where one applies
    covered: bool = False  # PI that sits under a mark: hidden from view, still extractable

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = _round_box(self.bbox)
        d["boxes"] = [_round_box(b) for b in self.boxes]
        if self.score is not None:
            d["score"] = round(self.score, 3)
        return d


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    source: str  # text_layer | ocr | empty
    ocr_mean_conf: float | None = None
    ocr_regions: int = 0
    enhanced_pass: bool = False  # the contrast-stretched second OCR pass ran on this page

    def to_dict(self) -> dict:
        d = asdict(self)
        d["width"] = round(self.width, 1)
        d["height"] = round(self.height, 1)
        if self.ocr_mean_conf is not None:
            d["ocr_mean_conf"] = round(self.ocr_mean_conf, 3)
        return d


@dataclass
class DocResult:
    path: str
    pages: list[PageInfo] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    error: str = ""

    @property
    def verdict(self) -> str:
        if self.error:
            return NOT_CHECKED
        kinds = {f.kind for f in self.findings}
        if RECOVERABLE in kinds:
            return FAIL_RECOVERABLE
        if PI in kinds:
            return PI_VISIBLE
        if LOW_CONFIDENCE in kinds:
            return REVIEW_LOW_CONFIDENCE
        return NO_ISSUES_FOUND

    @property
    def has_issue(self) -> bool:
        """Anything other than a clean result: what the evaluation counts as flagged."""
        return self.verdict != NO_ISSUES_FOUND

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "verdict": self.verdict,
            "meaning": VERDICT_MEANING[self.verdict],
            "error": self.error,
            "pages": [p.to_dict() for p in self.pages],
            "findings": [f.to_dict() for f in self.findings],
        }


def _round_box(box: Box | None) -> list[float] | None:
    return [round(v, 1) for v in box] if box is not None else None


def union(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
