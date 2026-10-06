"""
SDS Parser
Extracts label-relevant fields from a GHS-format Safety Data Sheet PDF:
- Signal word
- Hazard statements (H-codes)
- Precautionary statements (P-codes)
- Storage instructions (Section 7)
- Disposal instructions (Section 13)
- Ingredients (Section 3)
- Classification categories (used to derive GHS pictograms, since pictograms
  appear as an IMAGE in the PDF, not as text codes like "GHS07")

Anchoring strategy: GHS SDS documents use numbered, consistently-worded
section headers ("SECTION 2 – Hazard Identification"). We extract full text,
then split on a regex that matches "SECTION <n>" regardless of dash style
(some SDS use hyphen, some use en-dash, some use em-dash).
"""

import re
import pdfplumber


SECTION_HEADER_RE = re.compile(
    r"^SECTION\s+(\d{1,2})\s*[-–—:]?\s*([A-Za-z /,\(\)]+)?",
    re.IGNORECASE | re.MULTILINE,
)

# Maps GHS hazard classification keywords (as they appear in SDS Section 2
# "Classification:" block) to the pictogram code that applies.
# This is intentionally simple keyword matching, not a full GHS classification
# engine. It's meant to catch the common cases seen in adhesive/sealant SDS
# documents. Flagged for manual review in the app regardless.
CLASSIFICATION_TO_PICTOGRAM = {
    "flammable": "GHS02",              # Flame
    "oxidizer": "GHS03",               # Flame over circle
    "oxidizing": "GHS03",
    "gas under pressure": "GHS04",     # Gas cylinder
    "corrosive": "GHS05",              # Corrosion
    "skin corrosion": "GHS05",
    "acute toxicity": "GHS06",         # Skull and crossbones (severe only)
    "carcinogen": "GHS08",             # Health hazard
    "respiratory sensitiz": "GHS08",
    "reproductive toxicity": "GHS08",
    "stot": "GHS08",
    "aspiration hazard": "GHS08",
    "aquatic": "GHS09",                # Environment
    "skin sensitiz": "GHS07",          # Exclamation mark
    "eye irrit": "GHS07",
    "skin irrit": "GHS07",
    "respiratory irritation": "GHS07",
}


def extract_full_text(pdf_path):
    """Extract and concatenate text from all pages, preserving page breaks
    as a single continuous stream so multi-page sections parse cleanly."""
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            pages_text.append(t)
    return "\n".join(pages_text)


def split_into_sections(full_text):
    """Split full SDS text into a dict: {section_number: section_body_text}."""
    matches = list(SECTION_HEADER_RE.finditer(full_text))
    sections = {}
    for i, m in enumerate(matches):
        sec_num = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        sections[sec_num] = full_text[start:end].strip()
    return sections


def extract_signal_word(section2_text):
    m = re.search(r"Signal\s+Word:\s*([A-Za-z]+)", section2_text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_classification(section2_text):
    """Grab the Classification block. Different SDS authors use different
    heading wording ('Classification:' vs 'Classification of the
    Substance or Mixture:'), so try a couple of known variants rather than
    a single fixed string."""
    heading_patterns = [
        r"Classification of the Substance or Mixture:",
        r"Classification\s*(?:\([^)]*\))?:",  # also matches "Classification (OSHA HazCom 2024 / GHS Rev. 7):"
    ]
    for heading in heading_patterns:
        m = re.search(
            rf"{heading}\s*(.*?)\s*(?:Label Elements:|Signal\s+Word:)",
            section2_text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            raw = m.group(1).strip()
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            return lines
    return []


def derive_pictograms(classification_lines):
    """Map classification lines to GHS pictogram codes via keyword match.
    Returns a sorted, de-duplicated list of pictogram codes."""
    found = set()
    for line in classification_lines:
        lower = line.lower()
        for keyword, code in CLASSIFICATION_TO_PICTOGRAM.items():
            if keyword in lower:
                found.add(code)
    return sorted(found)


def extract_hazard_statements(section2_text):
    """Extract H-code lines from the 'Hazard Statements:' subsection
    specifically -- NOT from the Classification block, which sometimes
    also contains H-codes inline (e.g. 'H315 – Skin Irritation Category
    2') that would otherwise get matched first and produce the wrong
    text. Separator between code and text varies by document: some use
    '–' (dash), others use ':' (colon)."""
    m = re.search(
        r"Hazard Statements:\s*(.*?)(?=\n[A-Z][A-Za-z ]+:|\nSECTION|\Z)",
        section2_text,
        re.DOTALL,
    )
    search_text = m.group(1) if m else section2_text
    pattern = re.compile(r"(H\d{3})\s*[:\-–—]\s*([^\n]+)")
    return [{"code": m.group(1), "text": m.group(2).strip()}
            for m in pattern.finditer(search_text)]


def extract_precautionary_statements(section2_text):
    """Extract P-code lines, including compound codes like 'P302 + P352'.
    Falls back to plain-sentence extraction when a document lists
    precautionary instructions without P-codes at all (seen in some SDS
    variants) -- in that case each line under 'Precautionary Statements:'
    up to the next section heading is treated as one statement."""
    _p_stop = r"P\d{3}|SECTION|Precautionary [Ss]tatements:|Curing note:|Hazards not otherwise classified|Page\s+\d+\s+of\s+\d+|DCN:"
    pattern = re.compile(
        rf"((?:P\d{{3}}(?:\s*\+\s*P\d{{3}})*))\s*(?:[A-Z][A-Za-z ]{{0,24}})?\s*[-–—:]\s*([^\n]+(?:\n(?!{_p_stop})[^\n]+)*)"
    )
    results = []
    for m in pattern.finditer(section2_text):
        code = m.group(1).strip()
        text = " ".join(m.group(2).split())  # collapse wrapped lines
        results.append({"code": code, "text": text})

    if results:
        return results

    # Fallback: no P-codes found. Grab the raw block under the heading and
    # split into individual statements by line.
    m = re.search(
        r"Precautionary Statements:\s*(.*?)(?=\n(?:Other Hazards:|SECTION|\Z))",
        section2_text,
        re.DOTALL,
    )
    if not m:
        return []
    raw_lines = [l.strip() for l in m.group(1).split("\n") if l.strip()]
    # Merge wrapped continuation lines back into the statement they belong
    # to -- a line that starts lowercase is a PDF line-wrap continuation of
    # the previous line, not a new standalone statement (e.g. "...if
    # present" / "and easy to do" is one sentence split across two lines).
    merged = []
    for line in raw_lines:
        if merged and line[0].islower():
            merged[-1] = merged[-1] + " " + line
        else:
            merged.append(line)
    return [{"code": None, "text": line} for line in merged]


def extract_ingredients(pdf_path):
    """Extract the ingredient table from Section 3.

    Plain text extraction scrambles multi-line table cells (e.g. "Crosslinking
    silane" and "compound" land on separate lines with the numeric columns
    interleaved between them), so this uses pdfplumber's structured table
    extraction instead and picks the table whose header row matches the
    expected ingredient-table columns.

    Different SDS authors use different column headers for the same data
    (e.g. "Chemical Name" vs "Component Identifier") and some omit the
    Classification column entirely, so the name column and the
    classification column are both matched flexibly rather than requiring
    one fixed header string.
    """
    name_header_keywords = ["chemical name", "component identifier", "component"]
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or not table[0]:
                    continue
                header_cells = [(c or "").lower() for c in table[0]]
                header = " ".join(header_cells)
                has_name_col = any(k in header for k in name_header_keywords)
                has_cas_col = "cas" in header
                if not (has_name_col and has_cas_col):
                    continue
                for raw_row in table[1:]:
                    cells = [(c or "").replace("\n", " ").strip() for c in raw_row]
                    if len(cells) < 3:
                        continue
                    rows.append({
                        "chemical_name": cells[0],
                        "cas_number": cells[1],
                        "percent": cells[2] if len(cells) > 2 else "",
                        "classification": cells[3] if len(cells) > 3 else "",
                    })
    return rows


def extract_field(section_text, labels):
    """Generic field extractor: '<Label>: value text until next bold
    label or end of section'. Accepts a single label string or a list of
    candidate labels, since different SDS authors word the same field
    differently (e.g. 'Conditions for Safe Storage' vs plain 'Storage:').
    Tries each candidate in order and returns the first match."""
    if isinstance(labels, str):
        labels = [labels]
    for label in labels:
        pattern = re.compile(
            rf"{re.escape(label)}:?\s*(.+?)(?=\n[A-Z][A-Za-z /]+:|\nSECTION|$)",
            re.DOTALL | re.IGNORECASE,
        )
        m = pattern.search(section_text)
        if m:
            raw = m.group(1)
            # Some documents format this field as an "o "-prefixed bullet
            # list (one bullet per line) rather than a single sentence.
            # Detect that by checking each line's own leading marker --
            # a regex trying to exclude the letter "o" from bullet TEXT
            # breaks immediately on ordinary words like "moisture" or
            # "container", so this splits by line first and strips a
            # leading "o " token only, not any "o" character anywhere.
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            bullet_items = []
            is_bulleted = True
            for line in lines:
                if line.startswith("o ") or line.startswith("o\t"):
                    bullet_items.append(line[2:].strip())
                else:
                    is_bulleted = False
                    break
            if is_bulleted and len(bullet_items) > 1:
                text = "; ".join(bullet_items)
            else:
                text = " ".join(raw.split())
            if text:
                return text
    return None


def parse_sds(pdf_path):
    full_text = extract_full_text(pdf_path)
    sections = split_into_sections(full_text)

    section2 = sections.get("2", "")
    section3 = sections.get("3", "")
    section7 = sections.get("7", "")
    section13 = sections.get("13", "")

    classification_lines = extract_classification(section2)

    result = {
        "signal_word": extract_signal_word(section2),
        "classification": classification_lines,
        "pictograms": derive_pictograms(classification_lines),
        "hazard_statements": extract_hazard_statements(section2),
        "precautionary_statements": extract_precautionary_statements(section2),
        "ingredients": extract_ingredients(pdf_path),
        "storage": extract_field(section7, ["Conditions for Safe Storage", "Storage"]),
        "handling": extract_field(section7, ["Precautions for Safe Handling", "Handling"]),
        "disposal": extract_field(section13, ["Waste Disposal Method", "Waste treatment methods", "Disposal"]),
    }
    return result


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/mnt/user-data/uploads/ForzaEagle_T-OS164_Transportation_Sealant_SDS_V1_08_11_2026.pdf"
    data = parse_sds(path)
    print(json.dumps(data, indent=2))
