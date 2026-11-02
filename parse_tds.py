"""
TDS Parser
Extracts the "Product Application" bullet list from a Forza TDS PDF.

Key problem this solves: Forza's TDS layout is two-column. Plain
page.extract_text() reads in a jumbled order that interleaves the left and
right columns mid-sentence (e.g. "Open Time: Extended" from the right column
lands in the middle of the Product Application bullets from the left
column). To get clean text, we detect the column gap and crop/extract each
column separately, then search for the section within whichever column
contains it.
"""

import re
import pdfplumber


SECTION_TITLE = "Product Application"

# Heading names the application/directions section has gone by. The older
# TDS layout calls it "Product Application" (bulleted, in the front-page
# columns); the newer layout puts "Application Instructions" on the BACK
# page as plain sentences/paragraphs. Tried in this order.
SECTION_TITLES = [
    "Product Application",
    "Application Instructions",
    "Directions for Use",
    "Directions For Use",
    "Application Directions",
]


def find_column_split(page, min_gap=8):
    """Detect the x-coordinate of the gutter between two columns.

    The two columns have independent line-wrapping, so their rows rarely
    align at the same vertical position -- a per-line gap check misses the
    gutter because no single line contains both "last word of left column"
    and "first word of right column" at the same height. Instead, this
    looks at word START positions (x0) across the WHOLE page: each column
    has a fairly consistent left margin (bullets/paragraphs all start near
    the same x), so the x0 values cluster into two tight bands with a real
    gap between them, even though words' END positions (x1) overlap freely
    because of variable line length. We find the widest gap between
    consecutive x0 values, restricted to a plausible middle band so we don't
    pick up incidental indentation.
    """
    words = page.extract_words()
    if not words:
        return None

    mid_lo, mid_hi = page.width * 0.30, page.width * 0.70
    x0s = sorted(w["x0"] for w in words)

    best_gap = 0
    best_mid = None
    for a, b in zip(x0s, x0s[1:]):
        if mid_lo <= a <= mid_hi and (b - a) > best_gap:
            best_gap = b - a
            best_mid = (a + b) / 2

    if best_gap < min_gap:
        return None
    return best_mid


def _words_to_text(words, mark_paragraphs=False):
    """Reconstruct line-broken text from a word list, grouping words into
    lines by vertical position (words on the same line share a similar
    'top' value). With mark_paragraphs, a blank line is emitted wherever the
    vertical gap between two lines is clearly larger than the normal line
    pitch -- that is how paragraph breaks show up in a PDF with no bullet
    glyphs."""
    if not words:
        return ""
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines, tops, rights = [], [], []
    current_line, current_top, cur_right = [], None, 0
    for w in words:
        top = round(w["top"])
        if current_top is None or abs(top - current_top) <= 2:
            current_line.append(w["text"])
            cur_right = max(cur_right, w["x1"])
            if current_top is None:
                current_top, exact_top = top, w["top"]
        else:
            lines.append(" ".join(current_line)); tops.append(exact_top); rights.append(cur_right)
            current_line = [w["text"]]
            current_top, exact_top, cur_right = top, w["top"], w["x1"]
    if current_line:
        lines.append(" ".join(current_line)); tops.append(exact_top); rights.append(cur_right)
    if not mark_paragraphs or len(lines) < 3:
        return "\n".join(lines)
    gaps = [b - a for a, b in zip(tops, tops[1:])]
    pitch = sorted(gaps)[len(gaps) // 2]   # median line pitch
    left_edge = min(w["x0"] for w in words)
    full_w = max(rights) - left_edge
    out = [lines[0]]
    for gap, prev_line, prev_right, line in zip(gaps, lines, rights, lines[1:]):
        # A paragraph break needs the previous line to have FINISHED a
        # sentence, plus either extra vertical space beyond the usual line
        # pitch, or that line stopping well short of the column's full width
        # (a ragged last line -- how paragraphs end when the PDF has no
        # extra spacing between them).
        ends_sentence = prev_line.rstrip().endswith((".", "!", "?", ":"))
        extra_space = pitch > 0 and gap > pitch * 1.15
        short_line = (prev_right - left_edge) < 0.8 * full_w
        if ends_sentence and (extra_space or short_line):
            out.append("")
        out.append(line)
    return "\n".join(out)


def extract_columns_text(page, mark_paragraphs=False):
    """Return a list of text blocks, one per detected column (or a single
    block if the page is single-column).

    Builds each column from WHOLE WORDS assigned by center x-position,
    rather than pdfplumber's page.crop() -- crop() slices by raw pixel
    coordinates against each character's bounding box, which can physically
    bisect a single word if it straddles the column gutter (seen in the
    wild: "Packaging" in the right column split into "Pa" left of the
    gutter and "ackaging" right of it, corrupting the left column's text
    with a stray "Pa"). Assigning whole words by their center avoids ever
    cutting a word in half.
    """
    split_x = find_column_split(page)
    if split_x is None:
        if mark_paragraphs:
            return [_words_to_text(page.extract_words(), mark_paragraphs=True)]
        return [page.extract_text() or ""]

    words = page.extract_words()
    left_words = [w for w in words if (w["x0"] + w["x1"]) / 2 < split_x]
    right_words = [w for w in words if (w["x0"] + w["x1"]) / 2 >= split_x]

    return [_words_to_text(left_words, mark_paragraphs), _words_to_text(right_words, mark_paragraphs)]


def extract_product_application_bullets(pdf_path):
    """Find the application section across all pages/columns and return its
    items as a clean list, preserving original wording.

    Handles both TDS layouts:
      * older: "Product Application" heading followed by bulleted lines
      * newer: "Application Instructions" heading (back page) followed by
        plain sentences / short paragraphs with no bullet glyphs

    Bullets in the source are hyphenated across line-wraps by the PDF
    renderer's fixed line width (not real hyphenation), so wrapped lines are
    rejoined into a single bullet string.
    """
    with pdfplumber.open(pdf_path) as pdf:
        for title in SECTION_TITLES:
            for page in pdf.pages:
                for block in extract_columns_text(page, mark_paragraphs=True):
                    if not any(l.strip().startswith(title) for l in block.split("\n")):
                        continue
                    items = _items_from_block(block, title)
                    if items:
                        return items
    return []


def _looks_like_heading(line, prev_line=""):
    """Short, title-case line with no terminal punctuation that follows a
    finished sentence (or the section start) -- i.e. the next section title."""
    s = line.strip()
    if not s or s[0] in "•-":
        return False
    prev = prev_line.strip()
    return (
        s[0].isupper()
        and len(s.split()) <= 4
        and not s.endswith((".", ",", ":", ";"))
        and (not prev or prev.endswith((".", "!", "?")))
    )


def _is_footer(line):
    s = line.strip()
    return bool(
        "@" in s
        or s.lower().startswith("www.")
        or re.search(r"\d{3}[.\-]\d{3}[.\-]\d{4}", s)
        or (s.isupper() and len(s) > 3)
    )


def _items_from_block(block, title):
    """Dispatch on layout: bulleted (old) vs. prose (new)."""
    lines = block.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip().startswith(title))
    except StopIteration:
        return []

    # Collect the span of lines belonging to this section (up to the next
    # heading / footer) and see whether it uses bullet markers. A blank
    # string in the span marks a paragraph break.
    span, prev = [], ""
    for line in lines[start + 1:]:
        if not line.strip():
            if span and span[-1] != "":
                span.append("")
            continue
        if _is_footer(line) or _looks_like_heading(line, prev):
            break
        span.append(line.strip())
        prev = line
    has_markers = any(l and (l[0] in "•" or l == "-" or l.startswith("- ")) for l in span)

    if has_markers:
        return _bullets_from_block(block, title)
    return _paragraphs_from_lines(span)


def _join_wrapped(lines):
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text += line          # wrap hyphen: 'well-' + 'ventilated'
        else:
            text = (text + " " + line) if text else line
    return " ".join(text.split())


def _paragraphs_from_lines(span):
    """Prose section -> one item per PARAGRAPH (a paragraph can hold several
    sentences and stays together as one bullet, matching how the TDS groups
    its instructions). If the PDF gave no paragraph spacing at all, fall back
    to one item per sentence."""
    paragraphs, cur = [], []
    for line in span + [""]:
        if line == "":
            if cur:
                paragraphs.append(_join_wrapped(cur))
                cur = []
        else:
            cur.append(line)
    paragraphs = [p for p in paragraphs if len(p) > 2]
    if len(paragraphs) <= 1 and "" not in span:
        return _sentences_from_lines([l for l in span if l])
    return paragraphs


def _sentences_from_lines(span):
    """Prose section -> list of sentences. Wrapped lines are re-joined (a
    trailing '-' on a line is a wrap hyphen, joined without a space), then
    the text is split on sentence boundaries so each instruction becomes its
    own checkbox/line on the label."""
    text = ""
    for line in span:
        if text.endswith("-") and line[:1].islower():
            text += line
        else:
            text = (text + " " + line) if text else line
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if len(p.strip()) > 2]


def _bullets_from_block(block, title=SECTION_TITLE):
    """Given a text block containing the Product Application heading,
    isolate the bullet lines that follow it, stopping at the next heading
    (a line with no leading bullet that looks like a new section title).

    Handles a layout quirk seen in some TDS files: the "•" marker glyph
    sometimes gets sorted into reading order in the MIDDLE of its own
    wrapped bullet's text rather than at the start (e.g. text line, then
    a bare "•" with no text of its own, then the bullet's continuation
    lines). A bare marker is only treated as a real bullet BOUNDARY when
    the text accumulated so far ends in terminal punctuation (a finished
    sentence) -- otherwise it's mid-paragraph noise and gets dropped
    while accumulation continues right through it.
    """
    lines = block.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if title in l)
    except StopIteration:
        return []

    bullets = []
    current = None
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped in ("•", "-"):
            if current and current.rstrip().endswith((".", "!", "?")):
                bullets.append(current.strip())
                current = None
            # else: mid-paragraph noise, drop and keep accumulating
            continue

        if len(stripped) <= 2:
            # Short crop-artifact fragment from an adjacent column.
            continue

        if stripped.startswith("•") or stripped.startswith("-"):
            if current:
                bullets.append(current.strip())
            current = stripped.lstrip("•- ").strip()
        elif current is not None:
            # Footer boilerplate (tagline, phone, email, URL, address) can
            # slip past the heading check below since it often ends in a
            # period too (e.g. "PURPOSE BUILT. PERFORMANCE."), which the
            # "doesn't end in punctuation" rule assumes only real bullet
            # continuations do. Catch it explicitly instead.
            looks_like_footer = (
                "@" in stripped
                or stripped.lower().startswith("www.")
                or re.search(r"\d{3}[.\-]\d{3}[.\-]\d{4}", stripped)
                or (stripped.isupper() and len(stripped) > 3)
            )
            if looks_like_footer:
                break

            looks_like_new_heading = (
                stripped[0].isupper()
                and not stripped[0].islower()
                and len(stripped.split()) <= 4
                and not stripped.endswith((".", ",", ":"))
            )
            if looks_like_new_heading:
                break
            current += " " + stripped
        else:
            current = stripped

    if current:
        bullets.append(current.strip())
    return bullets


if __name__ == "__main__":
    import sys
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/mnt/user-data/uploads/FORZA_V2_M-C227_TDS_Marine_DrumAerosol_06_28_26.pdf"
    bullets = extract_product_application_bullets(path)
    print(json.dumps(bullets, indent=2))


STORAGE_SECTION_HEADINGS = ["Storage and Shelf Life", "Storage & Shelf Life", "Storage Conditions", "Storage"]


def extract_storage_info(pdf_path):
    """Find a storage/shelf-life section in the TDS and return its text,
    or None if no matching heading is found. Tape products have no SDS to
    pull Storage from, but their TDS documents carry this information
    instead -- tries several heading variants since wording isn't
    standardized across TDS documents the way SDS section numbers are.

    Best-effort pattern-matching, same approach as extract_product_
    application_bullets -- not yet verified against a real tape TDS
    document (none were available to test against), so the heading list
    may need adjusting once tried against one.
    """
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for block in extract_columns_text(page):
                for heading in STORAGE_SECTION_HEADINGS:
                    if heading in block:
                        text = _section_text_after_heading(block, heading)
                        if text:
                            return text
    return None


def _section_text_after_heading(block, heading):
    """Isolate the paragraph text following a given heading within a text
    block, stopping at the next heading-like line (short line with no
    terminal punctuation, title-cased) or end of block."""
    lines = block.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if heading in l)
    except StopIteration:
        return None
    # Heading may be on its own line or prefixed to the first sentence --
    # strip it either way.
    first_line = lines[start].split(heading, 1)[-1].strip(" :-")
    collected = [first_line] if first_line else []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            break
        looks_like_heading = (
            len(stripped) < 40
            and not stripped.endswith((".", ",", ";"))
            and stripped[:1].isupper()
            and "•" not in stripped
        )
        if looks_like_heading:
            break
        collected.append(stripped)
    text = " ".join(collected).strip()
    return text or None
