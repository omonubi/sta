#!/usr/bin/env python3
"""Build a GitHub Pages website from the STA2e Core Rulebook PDF."""

from __future__ import annotations

import html
import os
import re
import sys

import fitz

fitz.TOOLS.mupdf_display_errors(False)

PDF_PATH = "site/01 STA2e Core Rulebook.pdf"
OUT_DIR = "site"

# ---------------------------------------------------------------------------
# LCARS colour palette (matches sta.css)
# ---------------------------------------------------------------------------
LCARS = {
    "black": "#000000",
    "orange": "#FF8800",
    "tan": "#FFCC99",
    "pink": "#CC5599",
    "blue": "#8899FF",
    "green": "#33CC99",
    "purple": "#CC99FF",
    "gold": "#FFCC33",
    "white": "#FFFFFF",
}

# Chapter accent colours cycling list
CHAPTER_COLOURS = [
    LCARS["orange"],
    LCARS["blue"],
    LCARS["pink"],
    LCARS["tan"],
    LCARS["green"],
    LCARS["gold"],
    LCARS["purple"],
    LCARS["orange"],
    LCARS["blue"],
    LCARS["pink"],
    LCARS["tan"],
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean(text: str) -> str:
    """Normalize whitespace and soft-hyphens."""
    text = text.replace("\xad", "")  # soft hyphen
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slug(title: str) -> str:
    t = clean(title).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


def is_page_header_footer(text: str, page_num: int) -> bool:
    """Heuristic: skip running headers/footers (short lines with page numbers)."""
    t = clean(text)
    if re.fullmatch(r"\d{1,3}", t):
        return True
    if re.fullmatch(r"(chapter\s+\d+\s*)?\d{1,3}", t, re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# Extract structured content per TOC entry
# ---------------------------------------------------------------------------

def extract_chapter_pages(doc: fitz.Document, toc: list, ch_index: int) -> list[dict]:
    """Return list of {page, blocks} for pages belonging to chapter ch_index."""
    level, title, start_page = toc[ch_index]
    # Find end page: next entry at same or higher level
    end_page = doc.page_count
    for j in range(ch_index + 1, len(toc)):
        if toc[j][0] <= level:
            end_page = toc[j][2] - 1  # 1-based page number
            break

    pages = []
    for pg in range(start_page - 1, end_page):  # convert to 0-based
        page = doc[pg]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        pages.append({"page_num": pg + 1, "blocks": blocks})
    return pages


def blocks_to_html(pages: list[dict], section_titles: set[str]) -> str:
    """Convert extracted page blocks to HTML paragraphs."""
    lines_html = []
    prev_was_heading = False

    for page_data in pages:
        for block in page_data["blocks"]:
            if block.get("type") != 0:  # skip image blocks
                continue
            for line_obj in block.get("lines", []):
                spans = line_obj.get("spans", [])
                if not spans:
                    continue
                text_parts = []
                max_size = 0.0
                is_bold = False
                is_all_caps_line = True
                for sp in spans:
                    t = sp.get("text", "")
                    text_parts.append(t)
                    sz = sp.get("size", 10)
                    if sz > max_size:
                        max_size = sz
                    flags = sp.get("flags", 0)
                    if flags & 16:  # bold flag
                        is_bold = True
                    if t and not t.isupper() and re.search(r"[a-z]", t):
                        is_all_caps_line = False

                raw = "".join(text_parts)
                text = clean(raw)
                if not text:
                    continue
                if is_page_header_footer(text, page_data["page_num"]):
                    continue

                # Classify line type
                escaped = html.escape(text)

                # Section heading (all-caps, larger font, bold)
                if max_size >= 11.5 and is_all_caps_line and is_bold and len(text) > 2:
                    lines_html.append(f'<h3 class="lcars-section-heading">{escaped}</h3>')
                    prev_was_heading = True
                # Sub-section heading (all-caps, normal size, bold)
                elif is_all_caps_line and is_bold and len(text) > 4 and max_size >= 9:
                    lines_html.append(f'<h4 class="lcars-sub-heading">{escaped}</h4>')
                    prev_was_heading = True
                # Quote / italic callout
                elif spans and (spans[0].get("flags", 0) & 2):  # italic flag
                    lines_html.append(f'<blockquote class="lcars-quote">{escaped}</blockquote>')
                    prev_was_heading = False
                # Regular paragraph text
                else:
                    if prev_was_heading:
                        lines_html.append(f'<p>{escaped}</p>')
                    else:
                        # Try to append to last <p> if it exists
                        if lines_html and lines_html[-1].startswith("<p>") and lines_html[-1].endswith("</p>"):
                            lines_html[-1] = lines_html[-1][:-4] + " " + escaped + "</p>"
                        else:
                            lines_html.append(f'<p>{escaped}</p>')
                    prev_was_heading = False

    return "\n".join(lines_html)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

GLOBAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Antonio:wght@400;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --lcars-black:   #000000;
  --lcars-orange:  #FF8800;
  --lcars-tan:     #FFCC99;
  --lcars-pink:    #CC5599;
  --lcars-blue:    #8899FF;
  --lcars-green:   #33CC99;
  --lcars-purple:  #CC99FF;
  --lcars-gold:    #FFCC33;
  --lcars-white:   #FFFFFF;
  --lcars-font:    'Antonio', sans-serif;
  --lcars-accent:  var(--lcars-orange);
}

html { scroll-behavior: smooth; }

body {
  background: var(--lcars-black);
  color: var(--lcars-white);
  font-family: var(--lcars-font);
  font-size: 16px;
  line-height: 1.65;
  min-height: 100vh;
}

/* ── MASTHEAD ─────────────────────────────────────── */
.lcars-masthead {
  background: var(--lcars-accent);
  padding: 16px 28px 12px;
  display: flex;
  align-items: flex-end;
  gap: 24px;
}
.lcars-masthead-logo {
  font-size: 32px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: #000;
  line-height: 1;
  white-space: nowrap;
}
.lcars-masthead-sub {
  font-size: 13px;
  letter-spacing: .35em;
  text-transform: uppercase;
  color: #000;
  opacity: .75;
}

/* ── LCARS FRAME ──────────────────────────────────── */
.lcars-frame {
  display: grid;
  grid-template-columns: 80px 1fr;
  grid-template-rows: auto 1fr 24px;
  min-height: calc(100vh - 64px);
}

.lcars-sidebar {
  grid-row: 1 / -1;
  background: var(--lcars-accent);
  display: flex;
  flex-direction: column;
  padding-top: 40px;
}
.lcars-sidebar-cap {
  width: 80px;
  height: 40px;
  background: var(--lcars-black);
  border-top-right-radius: 40px;
}
.lcars-sidebar-body {
  flex: 1;
  background: var(--lcars-accent);
}
.lcars-sidebar-foot-cap {
  width: 80px;
  height: 40px;
  background: var(--lcars-black);
  border-bottom-right-radius: 40px;
}
.lcars-sidebar-label {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .25em;
  text-transform: uppercase;
  color: #000;
  padding: 8px 4px;
  opacity: .6;
}

.lcars-topbar {
  grid-column: 2;
  height: 24px;
  background: var(--lcars-accent);
  border-bottom-left-radius: 24px;
}
.lcars-bottombar {
  grid-column: 2;
  height: 24px;
  background: var(--lcars-accent);
  border-top-left-radius: 24px;
}

.lcars-content {
  grid-column: 2;
  padding: 32px 40px;
  overflow: auto;
}

/* ── NAV ──────────────────────────────────────────── */
.lcars-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 32px;
}
.lcars-nav a {
  display: inline-block;
  background: var(--lcars-accent);
  color: #000;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .15em;
  text-transform: uppercase;
  padding: 5px 16px 5px 10px;
  border-radius: 20px;
  text-decoration: none;
  transition: filter .15s;
}
.lcars-nav a:hover { filter: brightness(1.15); }
.lcars-nav a.active { outline: 2px solid var(--lcars-white); }

/* ── CHAPTER CARDS (index) ────────────────────────── */
.chapter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 20px;
  margin-top: 24px;
}
.chapter-card {
  border: 2px solid var(--card-colour, var(--lcars-orange));
  border-radius: 4px 4px 16px 4px;
  padding: 20px;
  position: relative;
  overflow: hidden;
  text-decoration: none;
  color: var(--lcars-white);
  display: block;
  transition: background .15s;
}
.chapter-card:hover { background: rgba(255,255,255,.06); }
.chapter-card-num {
  font-size: 42px;
  font-weight: 700;
  line-height: 1;
  color: var(--card-colour, var(--lcars-orange));
  letter-spacing: -.02em;
}
.chapter-card-title {
  font-size: 16px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .1em;
  margin-top: 4px;
}
.chapter-card-sections {
  font-size: 12px;
  opacity: .6;
  margin-top: 8px;
  letter-spacing: .05em;
}
.chapter-card::after {
  content: "";
  position: absolute;
  bottom: 0; right: 0;
  width: 40px; height: 40px;
  background: var(--card-colour, var(--lcars-orange));
  border-top-left-radius: 40px;
}

/* ── CHAPTER CONTENT PAGE ─────────────────────────── */
.chapter-header {
  border-left: 6px solid var(--lcars-accent);
  padding: 8px 0 8px 20px;
  margin-bottom: 36px;
}
.chapter-header-num {
  font-size: 13px;
  letter-spacing: .3em;
  text-transform: uppercase;
  opacity: .6;
}
.chapter-header-title {
  font-size: 36px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  line-height: 1.1;
}

.chapter-section {
  margin-bottom: 48px;
}
.chapter-section-title {
  background: var(--lcars-accent);
  color: #000;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: .2em;
  text-transform: uppercase;
  padding: 5px 16px;
  border-radius: 20px;
  display: inline-block;
  margin-bottom: 20px;
}

h3.lcars-section-heading {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--lcars-accent);
  margin: 24px 0 10px;
  padding-left: 12px;
  border-left: 3px solid var(--lcars-accent);
}

h4.lcars-sub-heading {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: var(--lcars-tan);
  margin: 18px 0 6px;
}

p {
  margin-bottom: .9em;
  max-width: 720px;
  font-size: 15px;
}

blockquote.lcars-quote {
  border-left: 4px solid var(--lcars-pink);
  padding: 10px 16px;
  margin: 20px 0;
  font-style: italic;
  color: var(--lcars-tan);
  font-size: 15px;
  max-width: 660px;
}

/* ── TOC sidebar ──────────────────────────────────── */
.toc-panel {
  position: sticky;
  top: 24px;
  float: right;
  width: 220px;
  margin: 0 0 24px 32px;
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 8px;
  padding: 16px;
  font-size: 12px;
}
.toc-panel-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .25em;
  text-transform: uppercase;
  color: var(--lcars-accent);
  margin-bottom: 10px;
}
.toc-panel a {
  display: block;
  color: var(--lcars-white);
  text-decoration: none;
  padding: 3px 0;
  opacity: .75;
  transition: opacity .12s;
}
.toc-panel a:hover { opacity: 1; color: var(--lcars-accent); }

/* ── BREADCRUMB ───────────────────────────────────── */
.breadcrumb {
  font-size: 12px;
  letter-spacing: .12em;
  text-transform: uppercase;
  opacity: .6;
  margin-bottom: 24px;
}
.breadcrumb a { color: var(--lcars-accent); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }

/* ── FOOTER ───────────────────────────────────────── */
.lcars-footer {
  text-align: center;
  padding: 24px;
  font-size: 11px;
  letter-spacing: .15em;
  text-transform: uppercase;
  opacity: .4;
}

/* ── RESPONSIVE ───────────────────────────────────── */
@media (max-width: 640px) {
  .lcars-frame { grid-template-columns: 0 1fr; }
  .lcars-sidebar { display: none; }
  .lcars-content { padding: 20px 16px; }
  .toc-panel { float: none; width: 100%; margin: 0 0 24px; }
  .chapter-grid { grid-template-columns: 1fr; }
}
"""

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

def page_shell(title: str, content: str, accent: str = LCARS["orange"],
               label: str = "STA", back_href: str = "index.html") -> str:
    nav_home = f'<a href="{back_href}">&#8592; Home</a>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)} – STA2e Core Rulebook</title>
  <link rel="stylesheet" href="style.css">
  <style>:root {{ --lcars-accent: {accent}; }}</style>
</head>
<body>

<header class="lcars-masthead">
  <div class="lcars-masthead-logo">Star Trek Adventures</div>
  <div class="lcars-masthead-sub">2nd Edition · Core Rulebook</div>
</header>

<div class="lcars-frame">
  <aside class="lcars-sidebar">
    <div class="lcars-sidebar-cap"></div>
    <div class="lcars-sidebar-body">
      <div class="lcars-sidebar-label">{html.escape(label)}</div>
    </div>
    <div class="lcars-sidebar-foot-cap"></div>
  </aside>

  <div class="lcars-topbar"></div>

  <main class="lcars-content">
    <nav class="lcars-nav">
      {nav_home}
    </nav>
    {content}
  </main>

  <div class="lcars-bottombar"></div>
</div>

<footer class="lcars-footer">
  Star Trek Adventures 2nd Edition · Modiphius Entertainment · Reference Site
</footer>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Build index page
# ---------------------------------------------------------------------------

def build_index(chapters: list[dict]) -> str:
    cards = []
    for ch in chapters:
        num_str = str(ch["num"]).zfill(2)
        colour = ch["accent"]
        section_names = " · ".join(s["title"] for s in ch["sections"][:4])
        if len(ch["sections"]) > 4:
            section_names += f" · +{len(ch['sections'])-4} more"
        cards.append(f"""
  <a class="chapter-card" href="{ch['filename']}" style="--card-colour:{colour}">
    <div class="chapter-card-num">{ch['num']}</div>
    <div class="chapter-card-title">{html.escape(ch['title'])}</div>
    <div class="chapter-card-sections">{html.escape(section_names)}</div>
  </a>""")

    grid = '<div class="chapter-grid">' + "".join(cards) + "\n</div>"

    content = f"""
<h1 style="font-size:28px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px;">Core Rulebook</h1>
<p style="opacity:.6;font-size:13px;letter-spacing:.15em;text-transform:uppercase;margin-bottom:0;">Select a chapter to begin</p>
{grid}
"""
    return page_shell("Core Rulebook", content, accent=LCARS["orange"], label="INDEX")


# ---------------------------------------------------------------------------
# Build chapter page
# ---------------------------------------------------------------------------

def build_chapter_page(ch: dict) -> str:
    accent = ch["accent"]
    num_label = f"Chapter {ch['num']}"

    toc_links = "\n".join(
        f'    <a href="#{slug(s["title"])}">{html.escape(s["title"])}</a>'
        for s in ch["sections"]
    )
    toc_panel = f"""<aside class="toc-panel">
  <div class="toc-panel-title">Sections</div>
{toc_links}
</aside>""" if ch["sections"] else ""

    sections_html = []
    for sec in ch["sections"]:
        sec_id = slug(sec["title"])
        body = sec.get("html", "")
        if not body.strip():
            body = "<p><em>No textual content extracted for this section.</em></p>"
        sections_html.append(f"""
<section class="chapter-section" id="{sec_id}">
  <div class="chapter-section-title">{html.escape(sec["title"])}</div>
  {body}
</section>""")

    # If no sections, dump chapter body directly
    if not sections_html:
        body = ch.get("html", "<p><em>No textual content extracted.</em></p>")
        sections_html = [body]

    content = f"""
<div class="breadcrumb"><a href="index.html">Home</a> &rsaquo; {html.escape(num_label)}</div>

{toc_panel}

<div class="chapter-header">
  <div class="chapter-header-num">{html.escape(num_label)}</div>
  <div class="chapter-header-title">{html.escape(ch["title"])}</div>
</div>

{"".join(sections_html)}
"""
    return page_shell(f"{num_label}: {ch['title']}", content,
                      accent=accent, label=f"CH.{ch['num']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    doc = fitz.open(PDF_PATH)
    toc = doc.get_toc()

    # Separate foreword vs chapters
    foreword_entries = []
    chapter_entries = []
    ch_re = re.compile(r"^chapter\s+(\d+)", re.IGNORECASE)

    for i, (level, title, page) in enumerate(toc):
        clean_title = clean(title)
        if ch_re.match(clean_title):
            chapter_entries.append((i, level, clean_title, page))
        elif level == 1:
            foreword_entries.append((i, level, clean_title, page))

    chapters: list[dict] = []

    # ---- Foreword ----
    if foreword_entries:
        fw_sections = []
        for fi, (idx, level, title, page) in enumerate(foreword_entries):
            sub_indices = [j for j, (lv, tt, pp) in enumerate(toc)
                           if lv == 2 and j > idx and
                           (j < foreword_entries[fi+1][0] if fi+1 < len(foreword_entries) else True)]
            # Extract pages for this foreword entry
            pages_data = extract_chapter_pages(doc, toc, idx)
            fw_sections.append({
                "title": title,
                "html": blocks_to_html(pages_data, set()),
            })
        chapters.append({
            "num": 0,
            "title": "Foreword",
            "accent": LCARS["gold"],
            "filename": "chapter-00.html",
            "sections": fw_sections,
        })

    # ---- Chapters 1–11 ----
    for ci, (idx, level, title, start_page) in enumerate(chapter_entries):
        # Extract chapter number from title
        m = ch_re.match(title)
        ch_num = int(m.group(1)) if m else (ci + 1)
        # Clean title: remove "Chapter N:\n" prefix
        display_title = re.sub(r"^chapter\s+\d+[:\s]+", "", title, flags=re.IGNORECASE).strip()
        # Titlecase it
        display_title = display_title.title()

        accent = CHAPTER_COLOURS[(ch_num - 1) % len(CHAPTER_COLOURS)]

        # Find sub-sections (level 2) for this chapter
        # Determine the range of toc indices for this chapter
        next_ch_idx = chapter_entries[ci + 1][0] if ci + 1 < len(chapter_entries) else len(toc)
        sections: list[dict] = []
        for j in range(idx + 1, next_ch_idx):
            lv, sec_title, sec_page = toc[j]
            if lv == 2:
                sec_clean = clean(sec_title)
                sec_pages = extract_chapter_pages(doc, toc, j)
                sections.append({
                    "title": sec_clean,
                    "html": blocks_to_html(sec_pages, set()),
                })

        filename = f"chapter-{ch_num:02d}.html"
        chapters.append({
            "num": ch_num,
            "title": display_title,
            "accent": accent,
            "filename": filename,
            "sections": sections,
        })

    # ---- Write CSS ----
    css_path = os.path.join(OUT_DIR, "style.css")
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(GLOBAL_CSS)
    print(f"Written: {css_path}")

    # ---- Write index ----
    # Only show chapters 1+ on index (skip foreword card if desired)
    index_html = build_index([c for c in chapters if c["num"] >= 1])
    index_path = os.path.join(OUT_DIR, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"Written: {index_path}")

    # ---- Write foreword ----
    for ch in chapters:
        if ch["num"] == 0:
            ch_html = build_chapter_page(ch)
            ch_path = os.path.join(OUT_DIR, ch["filename"])
            with open(ch_path, "w", encoding="utf-8") as f:
                f.write(ch_html)
            print(f"Written: {ch_path}")

    # ---- Write chapter pages ----
    for ch in chapters:
        if ch["num"] == 0:
            continue
        ch_html = build_chapter_page(ch)
        ch_path = os.path.join(OUT_DIR, ch["filename"])
        with open(ch_path, "w", encoding="utf-8") as f:
            f.write(ch_html)
        print(f"Written: {ch_path}")

    # ---- Write _config.yml for GitHub Pages ----
    config_path = os.path.join(OUT_DIR, "_config.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("# GitHub Pages config – plain HTML site, no Jekyll theme\n")
        f.write("theme: null\n")
    print(f"Written: {config_path}")

    # ---- Write .nojekyll ----
    nojekyll_path = os.path.join(OUT_DIR, ".nojekyll")
    with open(nojekyll_path, "w", encoding="utf-8") as f:
        f.write("")
    print(f"Written: {nojekyll_path}")

    print(f"\nDone! {len(chapters)} pages generated in {OUT_DIR}/")


if __name__ == "__main__":
    main()
