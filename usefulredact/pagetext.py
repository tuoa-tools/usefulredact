"""One page as a string plus the tokens it was built from, each with its box.

Detectors work on the string and return character spans; `boxes_for_span` maps
a span back to where it sits on the page. A token is a word from the PDF text
layer, or a whole line from OCR (the engine reports boxes per line, so a span
inside an OCR line gets its share of the line's width).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from usefulredact.models import OCR, TEXT_LAYER, Box, union


@dataclass
class Token:
    text: str
    bbox: Box
    start: int = 0
    end: int = 0
    line: int = 0
    conf: float | None = None
    hidden: bool = False  # extractable, but the page does not show it (see pdf_checks)
    mark: str = ""  # the kind of mark this word sits under, if any (see pdf_checks)
    is_line: bool = False  # an OCR line: a span inside it takes a proportional slice


@dataclass
class PageText:
    text: str = ""
    tokens: list[Token] = field(default_factory=list)
    source: str = TEXT_LAYER

    # ------------------------------------------------------------------ build
    @classmethod
    def from_words(cls, words: list[tuple]) -> PageText:
        """From PyMuPDF `page.get_text("words")` tuples:
        (x0, y0, x1, y1, word, block_no, line_no, word_no)."""
        ordered = sorted(words, key=lambda w: (w[5], w[6], w[7]))
        page = cls(source=TEXT_LAYER)
        parts: list[str] = []
        pos = 0
        line_id = -1
        last_key = None
        for w in ordered:
            key = (w[5], w[6])
            if key != last_key:
                if last_key is not None:
                    parts.append("\n")
                    pos += 1
                line_id += 1
                last_key = key
            elif parts:
                parts.append(" ")
                pos += 1
            word = str(w[4])
            page.tokens.append(
                Token(
                    text=word,
                    bbox=(float(w[0]), float(w[1]), float(w[2]), float(w[3])),
                    start=pos,
                    end=pos + len(word),
                    line=line_id,
                )
            )
            parts.append(word)
            pos += len(word)
        page.text = "".join(parts)
        return page

    @classmethod
    def from_ocr_regions(cls, regions, scale: float = 1.0, source: str = OCR) -> PageText:
        """From ocr.OcrRegion objects. `scale` turns the engine's pixels into page
        units (72 / dpi for a rendered PDF page, 1 for a standalone image).

        Regions that share a row are joined with a space, so a label and the
        value beside it ("Date of birth:" and "12/03/1985") read as one line
        even when the engine boxed them separately."""
        page = cls(source=source)
        if not regions:
            return page
        row_height = median(r.height for r in regions) or 1.0
        rows: list[list] = []
        for region in sorted(regions, key=lambda r: r.cy):
            if rows and abs(region.cy - _row_cy(rows[-1])) <= 0.6 * row_height:
                rows[-1].append(region)
            else:
                rows.append([region])
        parts: list[str] = []
        pos = 0
        for line_id, row in enumerate(rows):
            if line_id:
                parts.append("\n")
                pos += 1
            for i, region in enumerate(sorted(row, key=lambda r: r.bbox[0])):
                if i:
                    parts.append(" ")
                    pos += 1
                x0, y0, x1, y1 = region.bbox
                page.tokens.append(
                    Token(
                        text=region.text,
                        bbox=(x0 * scale, y0 * scale, x1 * scale, y1 * scale),
                        start=pos,
                        end=pos + len(region.text),
                        line=line_id,
                        conf=region.conf,
                        is_line=True,
                    )
                )
                parts.append(region.text)
                pos += len(region.text)
        page.text = "".join(parts)
        return page

    # ------------------------------------------------------------------ query
    def tokens_in_span(self, start: int, end: int) -> list[Token]:
        return [t for t in self.tokens if t.start < end and t.end > start]

    def boxes_for_span(self, start: int, end: int) -> list[Box]:
        """One box per line the span touches."""
        by_line: dict[int, list[Box]] = {}
        for token in self.tokens_in_span(start, end):
            by_line.setdefault(token.line, []).append(_slice(token, start, end))
        return [box for boxes in by_line.values() if (box := union(boxes)) is not None]

    def span_marked(self, start: int, end: int) -> bool:
        """True when every token the span touches sits under a mark or is hidden."""
        tokens = self.tokens_in_span(start, end)
        return bool(tokens) and all(t.mark or t.hidden for t in tokens)


def _row_cy(row: list) -> float:
    return sum(r.cy for r in row) / len(row)


def _slice(token: Token, start: int, end: int) -> Box:
    """The part of a token's box that a span covers. Words are taken whole; an
    OCR line is cut in proportion to the characters, which is close enough to
    point a person at the right place."""
    if not token.is_line or not token.text:
        return token.bbox
    x0, y0, x1, y1 = token.bbox
    length = len(token.text)
    lo = max(0, start - token.start) / length
    hi = min(length, end - token.start) / length
    return (x0 + lo * (x1 - x0), y0, x0 + hi * (x1 - x0), y1)
