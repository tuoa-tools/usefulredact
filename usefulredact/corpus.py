"""A synthetic, labelled corpus: `python -m usefulredact.corpus --n 60 --seed 42`.

Every document is invented (Faker, en_AU, plus checksummed Medicare and tax file
numbers made here). Each gets one redaction method, and the labels follow from
how the file was made, not from anyone's judgement:

  labels.csv          file, method, variant, style, expected verdict
  pi_items.csv        file, page, PI type, value, box: every piece of PI put on the page
  sender_details.csv  file, detail: the sending organisation's own name, address and
                      phone, which are not PI (what a user would put on an ignore list)

The same generator makes the small fixtures the tests use.

Letters carry things that look like PI and are not, in every method, so that the
controls mean something: an organisation's own address and phone number, a shared
mailbox, dates that are not birth dates, nine-digit reference numbers that fail
the TFN checksum, white text on a dark banner, a yellow highlight, firms named
after people. Nobody signs a letter by name; a named signatory would be PI.

Those look-alikes are stratified, not random (see Traits): in every method, one
document in four carries the sender's street address, one in four its landline,
one in four a firm named after people. Dates are fixed too, so a seed gives the
same files on any day.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

from usefulredact.detectors import MEDICARE_WEIGHTS, tfn_valid
from usefulredact.models import FAIL_RECOVERABLE, NO_ISSUES_FOUND, PI_VISIBLE

# method -> (expected verdict, what was done)
METHODS: dict[str, tuple[str, str]] = {
    "m1_none": (PI_VISIBLE, "no redaction: the PI is in plain view"),
    "m2_proper": (NO_ISSUES_FOUND, "redaction annotations, applied: the text is gone"),
    "m3_drawn_box": (FAIL_RECOVERABLE, "black rectangle drawn over live text"),
    "m4_annotation": (
        FAIL_RECOVERABLE,
        "black annotation over live text, never applied",
    ),
    "m5_see_through": (
        FAIL_RECOVERABLE,
        "dark see-through fill or highlight over live text",
    ),
    "m6_scan_marker_60": (
        PI_VISIBLE,
        "scan, marker stroke at opacity 0.60: readable through it",
    ),
    "m6_scan_marker_85": (
        PI_VISIBLE,
        "scan, marker stroke at opacity 0.85: readable with effort",
    ),
    "m6_scan_marker_100": (
        NO_ISSUES_FOUND,
        "scan, marker stroke fully opaque: nothing to read",
    ),
    "m7_control": (NO_ISSUES_FOUND, "control: the document never held any PI"),
    "m8_pasted_image": (FAIL_RECOVERABLE, "black image pasted over live text"),
}
CONTROLS = ("m2_proper", "m6_scan_marker_100", "m7_control")
STYLES = (
    "account_letter",
    "appointment_letter",
    "application_form",
    "reference_letter",
)

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN = 64.0
SCAN_DPI = 200

# Organisations are picked from pools wider than anything the detectors know about.
_ORG_FIRST = (
    "Harbourline Northgate Meridian Ironbark Bluewren Saltbush Kestrel Wattlebrook Redgum "
    "Tidewater Clearview Summit Greenfield Lakeside Riverbend Southern Coastal Highland"
).split()
_ORG_SECOND = (
    "Water|Energy|Community Health|Dental|Property Management|Credit Union|Insurance|"
    "Physiotherapy|Family Practice|Leisure Centre|Housing Co-operative|Veterinary Hospital|"
    "Removals|Broadband|Strata|Motors|Optical|Legal|Tutoring|Storage"
).split("|")
_CITIES = (
    "Melbourne Sydney Brisbane Adelaide Perth Hobart Geelong Newcastle Ballarat Cairns".split()
)
_STREET_TYPES = (
    ["Street"] * 7
    + ["Road"] * 5
    + ["Avenue"] * 3
    + ["Drive"] * 2
    + [
        "Court",
        "Crescent",
        "Place",
        "Lane",
        "Parade",
        "Grove",
        "Close",
        "Terrace",
        "Rise",
        "Circuit",
        "Boulevard",
        "Way",
        "Esplanade",
        "Chase",
        "Outlook",
        "Nook",
    ]
)


@dataclass
class Traits:
    """The things in a letter that look like PI and are not. In the corpus they are set
    by a document's position within its method group, not drawn at random: with six
    documents per method, chance alone would hand one method most of the street
    addresses and make the methods incomparable."""

    sender_street: bool = False  # the sender's own street address, not a PO box
    sender_landline: bool = False  # the sender's own landline, not a 1300 number
    firm_named_after_people: bool = False
    dark_banner: bool = False
    yellow_highlight: bool = False

    @classmethod
    def for_position(cls, position: int) -> Traits:
        return cls(
            sender_street=position % 4 == 1,
            sender_landline=position % 4 == 2,
            firm_named_after_people=position % 4 == 3,
            dark_banner=position % 2 == 0,
            yellow_highlight=position % 3 == 0,
        )

    @classmethod
    def random(cls, rng: random.Random) -> Traits:
        return cls(*(rng.random() < p for p in (0.25, 0.25, 0.25, 0.5, 0.25)))


# Fixed, so that a seed gives the same corpus whatever day it is generated.
TODAY = date(2026, 6, 30)


@dataclass
class PiItem:
    type: str
    value: str
    page: int = 1
    rects: list[pymupdf.Rect] = field(default_factory=list)


@dataclass
class Letter:
    doc: pymupdf.Document
    items: list[PiItem]
    style: str
    org: list[str] = field(default_factory=list)  # the sender's own name, address, phone


# ------------------------------------------------------------------ fake values
def medicare_number(rng: random.Random) -> str:
    first8 = [rng.randint(2, 6)] + [rng.randint(0, 9) for _ in range(7)]
    check = sum(d * w for d, w in zip(first8, MEDICARE_WEIGHTS, strict=True)) % 10
    digits = "".join(map(str, first8)) + str(check) + str(rng.randint(1, 9))
    if rng.random() < 0.7:
        return f"{digits[:4]} {digits[4:9]} {digits[9]}"
    return digits


def tfn_number(rng: random.Random) -> str:
    while True:
        first8 = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(7)]
        weights = (1, 4, 3, 7, 5, 8, 6, 9)
        last = sum(d * w for d, w in zip(first8, weights, strict=True)) % 11  # 10 = -1 (mod 11)
        if last < 10:
            digits = "".join(map(str, first8)) + str(last)
            assert tfn_valid(digits)
            return f"{digits[:3]} {digits[3:6]} {digits[6:]}" if rng.random() < 0.7 else digits


def reference_number(rng: random.Random) -> str:
    """Nine digits that fail the TFN checksum: looks like one, is not."""
    while True:
        digits = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if not tfn_valid(digits) and digits[0] != "0":
            return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def _dob(rng: random.Random, fake) -> str:
    born = date(1938, 1, 1) + timedelta(days=rng.randint(0, 25_000))  # aged about 20 to 88
    return rng.choice(
        [
            f"{born.day:02d}/{born.month:02d}/{born.year}",
            f"{born.day} {born.strftime('%B')} {born.year}",
            f"{born.day}/{born.month}/{born.year}",
            born.isoformat(),
        ]
    )


def _street_address(rng: random.Random, fake) -> tuple[str, str]:
    unit = rng.choice(["", "", "", f"Unit {rng.randint(1, 40)}, ", f"{rng.randint(1, 30)}/"])
    street = f"{unit}{rng.randint(1, 480)} {fake.last_name()} {rng.choice(_STREET_TYPES)}"
    locality = f"{fake.city()} {fake.state_abbr()} {fake.postcode()}"
    return street, locality


def _organisation(rng: random.Random, fake, named_after_people: bool) -> str:
    if named_after_people:  # a fair trap for a name model
        return rng.choice(
            [
                f"{fake.last_name()} & {fake.last_name()} "
                f"{rng.choice(['Legal', 'Partners', 'Conveyancing'])}",
                f"{fake.last_name()} {rng.choice(['Motors', 'Optical', 'Removals', 'Plumbing'])}",
            ]
        )
    return f"{rng.choice(_ORG_FIRST)} {rng.choice(_ORG_SECOND)}"


# --------------------------------------------------------------------- writing
class _Writer:
    """Lays lines down the page and remembers where the PI went."""

    def __init__(self, rng: random.Random):
        self.doc = pymupdf.open()
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.font = rng.choice(["helv", "tiro"])
        self.size = rng.choice([10.5, 11, 11.5])
        self.y = MARGIN
        self.pending: list[PiItem] = []

    def banner(self, title: str, subtitle: str, dark: bool) -> None:
        if dark:
            self.page.draw_rect(pymupdf.Rect(0, 0, PAGE_W, 74), color=None, fill=(0.12, 0.17, 0.30))
            self.page.insert_text(
                (MARGIN, 40), title, fontsize=17, fontname="hebo", color=(1, 1, 1)
            )
            self.page.insert_text(
                (MARGIN, 58), subtitle, fontsize=8.5, fontname="helv", color=(1, 1, 1)
            )
        else:
            self.page.insert_text(
                (MARGIN, 44), title, fontsize=17, fontname="hebo", color=(0.1, 0.1, 0.1)
            )
            self.page.insert_text(
                (MARGIN, 60), subtitle, fontsize=8.5, fontname="helv", color=(0.3, 0.3, 0.3)
            )
            self.page.draw_line(
                (MARGIN, 68), (PAGE_W - MARGIN, 68), color=(0.6, 0.6, 0.6), width=0.7
            )
        self.y = 108.0

    def line(self, text: str = "", *, bold: bool = False, gap: float = 1.45) -> None:
        if text:
            font = "hebo" if bold else self.font
            self.page.insert_text((MARGIN, self.y), text, fontsize=self.size, fontname=font)
        self.y += self.size * gap

    def paragraph(self, text: str, atoms: list[str] = ()) -> None:
        """Wrap to the measure. `atoms` (PI values) are never split across lines."""
        shield = {a: a.replace(" ", " ") for a in atoms}
        for a, s in shield.items():
            text = text.replace(a, s)
        width = PAGE_W - 2 * MARGIN
        line = ""
        for word in text.split(" "):
            trial = f"{line} {word}".strip()
            if pymupdf.get_text_length(trial, fontname=self.font, fontsize=self.size) > width:
                self.line(line.replace(" ", " "))
                line = word
            else:
                line = trial
        if line:
            self.line(line.replace(" ", " "))
        self.y += self.size * 0.6

    def pi(self, kind: str, value: str) -> str:
        self.pending.append(PiItem(kind, value))
        return value

    def finish(self) -> list[PiItem]:
        words = self.page.get_text("words")
        for item in self.pending:
            hits = self.page.search_for(item.value)
            if " " not in item.value and "@" not in item.value:
                # a bare first name: keep the hits that are a word of their own, not the
                # "Ann" inside "Annual"
                hits = [
                    h
                    for h in hits
                    if any(
                        pymupdf.Rect(w[:4]).intersects(h)
                        and w[4].strip(",.;:").lower() == item.value.lower()
                        for w in words
                    )
                ]
            item.rects = [r + (-1.5, -1.0, 1.5, 1.0) for r in hits]
            if not item.rects:
                raise RuntimeError(f"could not place {item.type} {item.value!r}")
        return self.pending


def build_letter(
    rng: random.Random, fake, style: str, with_pi: bool = True, traits: Traits | None = None
) -> Letter:
    """One page in the given style. `with_pi=False` gives the control: the same
    furniture and traps, and no person anywhere in it."""
    traits = traits or Traits.random(rng)
    w = _Writer(rng)
    org = _organisation(rng, fake, traits.firm_named_after_people)
    city = rng.choice(_CITIES)
    if traits.sender_street:
        street, locality = _street_address(rng, fake)
        where = f"{street}, {locality}"
    else:
        where = f"PO Box {rng.randint(10, 990)}, {city} {fake.state_abbr()} {fake.postcode()}"
    phone = (
        f"(0{rng.choice('2378')}) {rng.randint(9000, 9999)} {rng.randint(1000, 9999)}"
        if traits.sender_landline
        else f"1300 {rng.randint(100, 999)} {rng.randint(100, 999)}"
    )
    domain = "".join(ch for ch in org.lower() if ch.isalpha())[:18] + ".example"
    mailbox = rng.choice(["enquiries", "info", "accounts", "reception", "hello"])
    w.banner(org, f"{where}   |   {phone}   |   {mailbox}@{domain}", dark=traits.dark_banner)

    issued = TODAY - timedelta(days=rng.randint(0, 200))
    due = TODAY + timedelta(days=rng.randint(1, 60))
    w.line(f"Issued: {issued.day} {issued.strftime('%B')} {issued.year}")
    w.line(
        f"Reference: {reference_number(rng)}     "
        f"Customer no. {rng.randint(7, 9)}{rng.randint(10**8, 10**9 - 1)}"
    )
    w.line()

    first, last = fake.first_name(), fake.last_name()
    name = f"{first} {last}"
    titled = f"{rng.choice(['Mr', 'Ms', 'Dr', 'Mrs'])} {name}" if rng.random() < 0.2 else name
    street, locality = _street_address(rng, fake)
    email = f"{first}.{last}{rng.randint(1, 99)}@{fake.free_email_domain()}".lower().replace(
        "'", ""
    )
    optional = ["dob", "email", "phone", "medicare", "tfn", "address"]
    chosen = set(rng.sample(optional, rng.randint(3, 6))) if with_pi else set()

    def field_lines() -> None:
        if "dob" in chosen:
            w.line(
                f"{rng.choice(['Date of birth', 'DOB', 'Date of Birth'])}: "
                f"{w.pi('dob', _dob(rng, fake))}"
            )
        if "address" in chosen:
            w.line(f"Address: {w.pi('address', street)}")
            w.line(f"               {w.pi('address', locality)}")
        if "email" in chosen:
            w.line(f"Email: {w.pi('email', email)}")
        if "phone" in chosen:
            w.line(
                f"{rng.choice(['Phone', 'Mobile', 'Contact number'])}: "
                f"{w.pi('phone', fake.phone_number())}"
            )
        if "medicare" in chosen:
            w.line(f"Medicare number: {w.pi('medicare', medicare_number(rng))}")
        if "tfn" in chosen:
            w.line(f"{rng.choice(['Tax file number', 'TFN'])}: {w.pi('tfn', tfn_number(rng))}")

    if style == "application_form":
        w.line("Membership application", bold=True, gap=2.0)
        if with_pi:
            w.line(f"Full name: {w.pi('name', titled)}")
            field_lines()
        else:  # a blank form: every label, no answers
            for label in (
                "Full name",
                "Date of birth",
                "Address",
                "Email",
                "Phone",
                "Medicare number",
                "Tax file number",
            ):
                w.line(f"{label}: ____________________________")
        w.line()
        w.paragraph(
            f"Applications are processed at our {city} office within ten working days. "
            f"Fees are due by {due.day:02d}/{due.month:02d}/{due.year}. Keep a copy of this form."
        )
    elif style == "reference_letter":
        w.line("To whom it may concern", gap=2.0)
        if with_pi:
            w.paragraph(
                f"We confirm that {w.pi('name', name)} has held an account with us since "
                f"{issued.year - rng.randint(2, 9)} and has met every payment on time. "
                f"We have no hesitation in recommending {w.pi('name', first)} as a reliable "
                "customer.",
                atoms=[name],
            )
            field_lines()
        else:
            w.paragraph(
                f"We confirm that this organisation has traded from its {city} premises since "
                f"{issued.year - rng.randint(2, 9)} and holds all licences required in the state."
            )
        w.line()
        w.paragraph("This letter is issued on request and does not constitute a guarantee.")
    else:
        if with_pi:
            w.line(w.pi("name", titled))
            if "address" in chosen:
                w.line(w.pi("address", street))
                w.line(w.pi("address", locality))
                chosen.discard("address")
            w.line()
            w.line(f"Dear {w.pi('name', first)},")
        else:
            w.line(f"Dear {rng.choice(['Customer', 'Resident', 'Member'])},")
        w.line()
        if style == "appointment_letter":
            w.paragraph(
                f"Your appointment at our {city} rooms is confirmed for "
                f"{due.day} {due.strftime('%B')} {due.year} at "
                f"{rng.randint(8, 16)}:{rng.choice(['00', '15', '30'])}. "
                "Please arrive ten minutes early and bring any referral paperwork."
            )
        else:
            w.paragraph(
                f"Your account was reviewed on {issued.day} {issued.strftime('%B')} {issued.year}. "
                f"The balance of ${rng.randint(40, 900)}.{rng.randint(10, 99)} is due by "
                f"{due.day:02d}/{due.month:02d}/{due.year}. "
                f"Payments can be made at any {city} branch."
            )
        if with_pi:
            w.line("Our records show:", gap=1.8)
            field_lines()
            w.line()
        w.paragraph(
            f"If any detail is wrong, call {phone} between 9 am and 5 pm, or write to "
            f"{mailbox}@{domain}."
        )
    w.line()
    w.line("Yours sincerely,")
    w.line(
        rng.choice(
            ["Customer Accounts Team", "Client Services", "The Front Desk", "Member Support"]
        )
    )
    items = w.finish()

    if traits.yellow_highlight:  # on something harmless
        for rect in w.page.search_for("Yours sincerely")[:1]:
            w.page.add_highlight_annot(rect).update()
    w.doc.set_metadata(
        {
            "title": f"{org} correspondence",
            "author": "",
            "creationDate": "D:20260101000000Z",
            "modDate": "D:20260101000000Z",
            "producer": "usefulredact corpus",
            "creator": "",
        }
    )
    return Letter(w.doc, items, style, org=[org, where, phone])


# ------------------------------------------------------------ redaction methods
def _rects(letter: Letter) -> list[pymupdf.Rect]:
    return [r for item in letter.items for r in item.rects]


def redact_properly(letter: Letter) -> None:
    page = letter.doc[0]
    for rect in _rects(letter):
        page.add_redact_annot(rect, fill=(0, 0, 0))
    page.apply_redactions()


def draw_boxes(letter: Letter) -> None:
    page = letter.doc[0]
    for rect in _rects(letter):
        page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))


def annotate(letter: Letter, variant: str) -> None:
    page = letter.doc[0]
    for rect in _rects(letter):
        if variant == "unapplied_redaction":
            page.add_redact_annot(rect, fill=(0, 0, 0))
        else:
            annot = page.add_rect_annot(rect)
            annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
            annot.update()


def see_through(letter: Letter, variant: str, opacity: float) -> None:
    page = letter.doc[0]
    for rect in _rects(letter):
        if variant == "dark_highlight":
            annot = page.add_highlight_annot(rect)
            annot.set_colors(stroke=(0.08, 0.08, 0.08))
            annot.set_opacity(opacity)
            annot.update()
        else:
            page.draw_rect(rect, color=None, fill=(0, 0, 0), fill_opacity=opacity)


def paste_images(letter: Letter) -> None:
    page = letter.doc[0]
    black = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
    black.clear_with(0)
    for rect in _rects(letter):
        page.insert_image(rect, pixmap=black, keep_proportion=False)


def scan_with_marker(letter: Letter, opacity: float, rng: random.Random) -> Image.Image:
    """Render the page as a scanner would see it after someone went over the PI with
    a marker: strokes a little uneven, the sheet a little crooked, the sensor noisy."""
    page = letter.doc[0]
    pix = page.get_pixmap(dpi=SCAN_DPI, alpha=False, annots=False)
    sheet = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    ink = Image.new("RGBA", sheet.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ink)
    k = SCAN_DPI / 72.0
    for rect in _rects(letter):
        pad_x, pad_y = rng.uniform(4, 10), rng.uniform(2, 5)
        box = [
            rect.x0 * k - pad_x,
            rect.y0 * k - pad_y,
            rect.x1 * k + pad_x,
            rect.y1 * k + pad_y,
        ]
        draw.rounded_rectangle(box, radius=rng.uniform(3, 8), fill=(0, 0, 0, round(255 * opacity)))
    sheet = Image.alpha_composite(sheet, ink).convert("RGB")
    sheet = sheet.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(
        0, rng.uniform(4, 8), (sheet.height, sheet.width, 1)
    )
    pixels = np.clip(np.asarray(sheet).astype(np.float32) * rng.uniform(0.94, 1.0) + noise, 0, 255)
    return Image.fromarray(pixels.astype(np.uint8))


def _save_pdf(doc: pymupdf.Document, path: Path) -> None:
    doc.save(path, garbage=3, deflate=True, no_new_id=True)


def make_document(
    method: str,
    style: str,
    rng: random.Random,
    fake,
    out: Path,
    stem: str,
    traits: Traits | None = None,
):
    """Build one corpus file. Returns (file name, variant, the letter it was made from)."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}")
    letter = build_letter(rng, fake, style, with_pi=method != "m7_control", traits=traits)
    variant = ""
    if method.startswith("m6_scan"):
        opacity = int(method.rsplit("_", 1)[1]) / 100.0
        image = scan_with_marker(letter, opacity, rng)
        variant = rng.choice(["png", "jpg", "pdf"])
        name = f"{stem}.{variant}"
        if variant == "png":
            image.save(out / name)
        elif variant == "jpg":
            image.save(out / name, quality=88)
        else:  # an image-only PDF, as a scanner's "save as PDF" makes
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
            scanned = pymupdf.open()
            sheet = scanned.new_page(width=PAGE_W, height=PAGE_H)
            sheet.insert_image(sheet.rect, stream=buffer.getvalue())
            _save_pdf(scanned, out / name)
        return name, variant, letter
    if method == "m2_proper":
        redact_properly(letter)
    elif method == "m3_drawn_box":
        draw_boxes(letter)
    elif method == "m4_annotation":
        variant = rng.choice(["filled_square", "unapplied_redaction"])
        annotate(letter, variant)
    elif method == "m5_see_through":
        variant = rng.choice(["fill_opacity", "dark_highlight"])
        see_through(letter, variant, rng.uniform(0.5, 0.8))
    elif method == "m8_pasted_image":
        paste_images(letter)
    name = f"{stem}.pdf"
    _save_pdf(letter.doc, out / name)
    return name, variant, letter


def generate(n: int, seed: int, out: Path) -> Path:
    from faker import Faker

    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    fake = Faker("en_AU")
    fake.seed_instance(seed)
    methods = list(METHODS)
    labels, items, senders = [], [], []
    for index in range(n):
        method = methods[index % len(methods)]
        style = STYLES[(index // len(methods) + index) % len(STYLES)]
        stem = f"doc_{index + 1:03d}_{method}"
        traits = Traits.for_position(index // len(methods))
        name, variant, letter = make_document(method, style, rng, fake, out, stem, traits)
        labels.append([name, method, variant, style, METHODS[method][0], METHODS[method][1]])
        senders += [[name, detail] for detail in letter.org]
        for item in letter.items:
            for rect in item.rects:
                items.append(
                    [
                        name,
                        item.page,
                        item.type,
                        item.value,
                        *(round(v, 1) for v in rect),
                    ]
                )
    with open(out / "labels.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "method", "variant", "style", "expected_verdict", "what_was_done"])
        writer.writerows(labels)
    with open(out / "pi_items.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "page", "type", "value", "x0", "y0", "x1", "y1"])
        writer.writerows(items)
    with open(out / "sender_details.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "detail"])
        writer.writerows(senders)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m usefulredact.corpus",
        description="Generate the synthetic labelled corpus. Every person in it is invented.",
    )
    parser.add_argument("--n", type=int, default=60, help="number of documents (default 60)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("corpus"))
    args = parser.parse_args(argv)
    out = generate(args.n, args.seed, args.out)
    print(f"{args.n} documents and their labels written to {out}/ (seed {args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
