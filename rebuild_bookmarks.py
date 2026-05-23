#!/usr/bin/env python3
"""Rebuild PDF bookmarks for STA Core Primer using heading style rules.

Rules implemented:
1) Chapter headings are level 1.
2) Chapter subsections (CHAPTER X.Y pages) are level 2.
3) Level 3 headings are all-caps black headings, commonly with a small glyph.
4) Level 4 headings are entries prefixed with '.:' (or '. ' fallback observed in source).

Usage:
    python rebuild_bookmarks.py "01 STA2e Core Primer.pdf"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass

import fitz


CHAPTER_RE = re.compile(r"^CHAPTER\s+(\d+)(?:\.(\d+))?$", re.IGNORECASE)


@dataclass
class Line:
    page_index: int
    x0: float
    y0: float
    y1: float
    size: float
    font: str
    text: str


@dataclass
class Bookmark:
    level: int
    title: str
    page_1_based: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild bookmarks from heading styles.")
    parser.add_argument("pdf_path", help="Path to source PDF")
    parser.add_argument(
        "-o",
        "--output",
        help="Output PDF path (default: <input>.bookmarked.pdf)",
    )
    return parser.parse_args()


def default_output_path(pdf_path: str) -> str:
    base, ext = os.path.splitext(pdf_path)
    if base.endswith(".bookmarked"):
        return f"{base}{ext}"
    return f"{base}.bookmarked{ext}"


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.85


def smart_title_case(text: str) -> str:
    text = normalize_whitespace(text)
    if not text:
        return text

    # Keep strong acronyms as uppercase.
    force_upper = {
        "U.S.S.",
        "USS",
        "NCC",
        "IDIC",
        "Q",
        "DS9",
    }

    small_words = {
        "a",
        "an",
        "and",
        "as",
        "at",
        "but",
        "by",
        "for",
        "from",
        "in",
        "into",
        "nor",
        "of",
        "on",
        "onto",
        "or",
        "per",
        "the",
        "to",
        "up",
        "via",
        "vs",
        "with",
    }

    words = text.split(" ")
    out: list[str] = []

    for i, word in enumerate(words):
        raw = word
        lead = re.match(r"^[^A-Za-z0-9]*", raw).group(0)
        tail = re.search(r"[^A-Za-z0-9.']*$", raw).group(0)
        core = raw[len(lead) : len(raw) - len(tail) if tail else len(raw)]

        if not core:
            out.append(raw)
            continue

        core_upper = core.upper()
        if core_upper in force_upper or re.fullmatch(r"[IVXLCDM]+", core_upper):
            cased = core_upper
        elif core.isupper() or is_mostly_upper(core):
            cased = core.lower().title()
        else:
            cased = core

        if i not in (0, len(words) - 1) and cased.lower() in small_words:
            cased = cased.lower()

        out.append(f"{lead}{cased}{tail}")

    result = " ".join(out)
    # Fix possessive artifacts from title-casing all-caps words.
    result = re.sub(r"'S\b", "'s", result)
    return result


def clean_heading_text(text: str) -> str:
    text = normalize_whitespace(text)
    # Level-4 marker cleanup.
    text = re.sub(r"^\.\s*:?\s*", "", text)
    # Remove leading glyph/symbol markers often present before level-3 headings.
    text = re.sub(r"^[^A-Za-z0-9]+\s*", "", text)
    return normalize_whitespace(text)


def extract_lines(page: fitz.Page, page_index: int) -> list[Line]:
    data = page.get_text("dict")
    lines: list[Line] = []

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for row in block.get("lines", []):
            spans = row.get("spans", [])
            if not spans:
                continue
            text = normalize_whitespace("".join(s.get("text", "") for s in spans))
            if not text:
                continue

            y0 = min(s.get("bbox", [0, 0, 0, 0])[1] for s in spans)
            y1 = max(s.get("bbox", [0, 0, 0, 0])[3] for s in spans)
            x0 = min(s.get("bbox", [0, 0, 0, 0])[0] for s in spans)
            size = max(float(s.get("size", 0)) for s in spans)
            font = "|".join(sorted({str(s.get("font", "")) for s in spans}))

            lines.append(Line(page_index, x0, y0, y1, size, font, text))

    lines.sort(key=lambda ln: (ln.y0, ln.x0))
    return lines


def looks_like_running_header_or_footer(line: Line, page_height: float) -> bool:
    txt = line.text.strip().upper()
    if line.size <= 8.6 and (line.y0 < 65 or line.y0 > page_height - 80):
        return True
    if txt.startswith("CHAPTER ") and line.size <= 9.2:
        return True
    return False


def extract_page_title(lines: list[Line]) -> str:
    # Large decorative chapter/subsection titles use this font and appear near top.
    caps = [
        ln
        for ln in lines
        if ln.size >= 30
        and "FinalFrontierOldStyle" in ln.font
        and ln.y0 < 230
        and len(ln.text) <= 80
    ]

    if not caps:
        return ""

    merged: list[list[Line]] = []
    for ln in caps:
        if not merged or abs(ln.y0 - merged[-1][-1].y0) > 55:
            merged.append([ln])
        else:
            merged[-1].append(ln)

    best = max(merged, key=lambda group: (len(group), max(x.size for x in group)))
    raw_title = " ".join(x.text for x in best)
    return smart_title_case(clean_heading_text(raw_title))


def chapter_marker(lines: list[Line]) -> tuple[int, int | None] | None:
    for ln in lines:
        if ln.y0 > 240 or ln.size < 9.5:
            continue
        m = CHAPTER_RE.match(ln.text.strip())
        if not m:
            continue
        major = int(m.group(1))
        minor = int(m.group(2)) if m.group(2) else None
        return (major, minor)
    return None


def is_level3_heading(line: Line, page_height: float) -> bool:
    txt = line.text.strip()
    if len(txt) < 3 or len(txt) > 90:
        return False
    if looks_like_running_header_or_footer(line, page_height):
        return False

    has_glyph = "Wingdings" in line.font or bool(re.match(r"^[^A-Za-z0-9]+", txt))
    if has_glyph and line.size >= 10.5 and is_mostly_upper(clean_heading_text(txt)):
        return True

    # Non-glyph level-3 headings: all-caps black headings in the body.
    if (
        line.size >= 14.5
        and "StrangeSansExtBold" in line.font
        and is_mostly_upper(txt)
        and line.y0 > 55
        and line.y0 < page_height - 80
    ):
        return True

    return False


def has_leading_glyph(line: Line) -> bool:
    return "Wingdings" in line.font or bool(re.match(r"^[^A-Za-z0-9]+", line.text.strip()))


def is_level4_heading(line: Line, page_height: float) -> bool:
    txt = line.text.strip()
    if looks_like_running_header_or_footer(line, page_height):
        return False
    if line.y0 < 100 or line.y0 > page_height - 90:
        return False
    return bool(re.match(r"^\.\s*:?\s*\S+", txt))


def dedupe_bookmarks(bookmarks: list[Bookmark]) -> list[Bookmark]:
    out: list[Bookmark] = []
    seen = set()
    for bm in bookmarks:
        key = (bm.level, bm.title.lower(), bm.page_1_based)
        if key in seen:
            continue
        seen.add(key)
        out.append(bm)
    return out


def normalize_levels(bookmarks: list[Bookmark]) -> list[Bookmark]:
    if not bookmarks:
        return []

    normalized: list[Bookmark] = []
    prev_level = 1

    for i, bm in enumerate(bookmarks):
        level = bm.level
        if i == 0:
            level = 1
        else:
            if level > prev_level + 1:
                level = prev_level + 1
            if level < 1:
                level = 1
        normalized.append(Bookmark(level, bm.title, bm.page_1_based))
        prev_level = level

    return normalized


def build_bookmarks(doc: fitz.Document) -> list[Bookmark]:
    bookmarks: list[Bookmark] = []

    for i in range(doc.page_count):
        page = doc[i]
        page_height = page.rect.height
        lines = extract_lines(page, i)
        last_l3_index: int | None = None
        last_l3_y = -9999.0

        marker = chapter_marker(lines)
        title = extract_page_title(lines)

        if marker:
            major, minor = marker
            if minor is None:
                # Level 1 chapter.
                chapter_title = title if title else f"Chapter {major}"
                bookmarks.append(Bookmark(1, chapter_title, i + 1))
            else:
                # Level 2 subsection.
                subsection_title = title if title else f"Chapter {major}.{minor}"
                bookmarks.append(Bookmark(2, subsection_title, i + 1))

        for ln in lines:
            if is_level4_heading(ln, page_height):
                raw = clean_heading_text(ln.text)
                if not raw:
                    continue
                bookmarks.append(Bookmark(4, smart_title_case(raw), i + 1))
                continue

            if is_level3_heading(ln, page_height):
                raw = clean_heading_text(ln.text)
                if not raw:
                    continue
                title3 = smart_title_case(raw)
                if (
                    last_l3_index is not None
                    and bookmarks[last_l3_index].level == 3
                    and bookmarks[last_l3_index].page_1_based == i + 1
                    and (ln.y0 - last_l3_y) <= 18
                    and not has_leading_glyph(ln)
                ):
                    merged = normalize_whitespace(f"{bookmarks[last_l3_index].title} {title3}")
                    bookmarks[last_l3_index] = Bookmark(3, merged, i + 1)
                    last_l3_y = ln.y0
                else:
                    bookmarks.append(Bookmark(3, title3, i + 1))
                    last_l3_index = len(bookmarks) - 1
                    last_l3_y = ln.y0

    bookmarks = dedupe_bookmarks(bookmarks)
    bookmarks = normalize_levels(bookmarks)
    return bookmarks


def write_pdf_with_bookmarks(input_pdf: str, output_pdf: str) -> int:
    doc = fitz.open(input_pdf)
    try:
        bookmarks = build_bookmarks(doc)
        if not bookmarks:
            print("No bookmarks detected; no output written.", file=sys.stderr)
            return 2

        toc = [[bm.level, bm.title, bm.page_1_based] for bm in bookmarks]

        # Explicitly clear existing TOC, then set the rebuilt one.
        doc.set_toc([])
        doc.set_toc(toc)
        doc.save(output_pdf, garbage=3, deflate=True)

        print(f"Wrote: {output_pdf}")
        print(f"Bookmarks: {len(toc)}")
        for idx, (lvl, title, page) in enumerate(toc[:60], start=1):
            print(f"{idx:02d}. L{lvl} p{page} {title}")
        if len(toc) > 60:
            print(f"... ({len(toc) - 60} more)")
        return 0
    finally:
        doc.close()


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"Input PDF not found: {args.pdf_path}", file=sys.stderr)
        return 1

    output = args.output or default_output_path(args.pdf_path)
    return write_pdf_with_bookmarks(args.pdf_path, output)


if __name__ == "__main__":
    raise SystemExit(main())
