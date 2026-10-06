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


def extract_columns_text(page):
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
        return [page.extract_text() or ""]

    words = page.extract_words()
    left_words = [w for w in words if (w["x0"] + w["x1"]) / 2 < split_x]
    right_words = [w for w in words if (w["x0"] + w["x1"]) / 2 >= split_x]

    def _words_to_text(words):
        """Reconstruct line-broken text from a word list, grouping words
        into lines by vertical position (words on the same line share a
        similar 'top' value)."""
        if not words:
            return ""
        words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
        lines, current_line, current_top = [], [], None
        for w in words:
            top = round(w["top"])
            if current_top is None or abs(top - current_top) <= 2:
                current_line.append(w["text"])
                current_top = top if current_top is None else current_top
            else:
                lines.append(" ".join(current_line))
                current_line = [w["text"]]
                current_top = top
        if current_line:
            lines.append(" ".join(current_line))
        return "\n".join(lines)

    return [_words_to_text(left_words), _words_to_text(right_words)]


def extract_product_application_bullets(pdf_path):
    """Find the 'Product Application' heading across all pages/columns and
    return its bullet points as a clean list, preserving original wording.

    Bullets in the source are hyphenated across line-wraps by the PDF
    renderer's fixed line width (not real hyphenation), so wrapped lines are
    rejoined into a single bullet string.
    """
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for block in extract_columns_text(page):
                if SECTION_TITLE not in block:
                    continue
                bullets = _bullets_from_block(block)
                if bullets:
                    return bullets
    return []


def _bullets_from_block(block):
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
        start = next(i for i, l in enumerate(lines) if SECTION_TITLE in l)
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
