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
    "chemicals under pressure": "GHS04",   # newer HazCom 2024 wording
    "under pressure": "GHS04",
    "aspiration": "GHS08",             # "Aspiration toxicity" / "Aspiration hazard"
    "serious eye damage": "GHS05",
    "eye damage": "GHS05",
    "explosive": "GHS01",
    "aquatic": "GHS09",                # Environment
    "skin sensitiz": "GHS07",          # Exclamation mark
    "eye irrit": "GHS07",
    "skin irrit": "GHS07",
    "respiratory irritation": "GHS07",
}


# Hazard-statement code -> pictogram. Used as a cross-check/fallback so the
# pictograms still come through when an SDS words its Classification block
# in a way the keyword map above doesn't recognise.
HCODE_TO_PICTOGRAM = {
    "H200": "GHS01", "H201": "GHS01", "H202": "GHS01", "H203": "GHS01",
    "H204": "GHS01", "H205": "GHS01",
    "H220": "GHS02", "H221": "GHS02", "H222": "GHS02", "H223": "GHS02",
    "H224": "GHS02", "H225": "GHS02", "H226": "GHS02", "H228": "GHS02",
    "H229": "GHS02", "H230": "GHS02", "H231": "GHS02", "H241": "GHS02",
    "H242": "GHS02", "H250": "GHS02", "H251": "GHS02", "H252": "GHS02",
    "H260": "GHS02", "H261": "GHS02",
    "H270": "GHS03", "H271": "GHS03", "H272": "GHS03",
    "H280": "GHS04", "H281": "GHS04", "H284": "GHS04",
    "H290": "GHS05", "H314": "GHS05", "H318": "GHS05",
    "H300": "GHS06", "H301": "GHS06", "H310": "GHS06", "H311": "GHS06",
    "H330": "GHS06", "H331": "GHS06",
    "H302": "GHS07", "H312": "GHS07", "H315": "GHS07", "H317": "GHS07",
    "H319": "GHS07", "H332": "GHS07", "H335": "GHS07", "H336": "GHS07",
    "H304": "GHS08", "H334": "GHS08", "H340": "GHS08", "H341": "GHS08",
    "H350": "GHS08", "H351": "GHS08", "H360": "GHS08", "H361": "GHS08",
    "H362": "GHS08", "H370": "GHS08", "H371": "GHS08", "H372": "GHS08",
    "H373": "GHS08",
    "H400": "GHS09", "H410": "GHS09", "H411": "GHS09",
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
    if "2" not in sections:
        sections = _split_numbered_headings(full_text) or sections
    return sections


_NUMBERED_TITLES = {
    1: "Identification", 2: r"Hazards?\(?s?\)?\s+identification", 3: "Composition",
    4: "First[- ]aid", 5: "Fire[- ]?fighting", 6: "Accidental release",
    7: "Handling and storage", 8: "Exposure controls", 9: "Physical and chemical",
    10: "Stability", 11: "Toxicological", 12: "Ecological", 13: "Disposal",
    14: "Transport", 15: "Regulatory", 16: "Other information",
}


def _split_numbered_headings(full_text):
    """Older layout (e.g. C830): headings are plain '2. Hazard(s) identification'
    lines instead of 'SECTION 2'. Take the first heading line for each
    section number, in order."""
    marks = []
    pos = 0
    for n in range(1, 17):
        m = re.compile(rf"^\s*{n}\.\s*{_NUMBERED_TITLES[n]}[^\n]*$", re.M | re.I).search(full_text, pos)
        if m:
            marks.append((n, m.start(), m.end()))
            pos = m.end()
    if not any(n == 2 for n, _, _ in marks):
        return {}
    out = {}
    for i, (n, st, en) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(full_text)
        out[str(n)] = full_text[en:end].strip()
    return out


def extract_signal_word(section2_text):
    m = re.search(r"Signal\s+Word\s*:?[ \t]*([A-Za-z]+)", section2_text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_classification(section2_text):
    """Grab the Classification block. SDS authors word this heading many
    ways ('Classification:', 'Classification of the Substance or
    Mixture:', 'Classification of the mixture (HazCom 2024 / GHS Rev. 7)'
    with no colon at all), and the block ends at 'Label Elements' with or
    without a colon, so match flexibly rather than on one fixed string."""
    heading_patterns = [
        r"Classification of the (?:chemical|substance or mixture|mixture)[^\n]*?:",
        r"Classification of the Substance or Mixture:",
        r"Classification\s*(?:\([^)]*\))?:",  # also matches "Classification (OSHA HazCom 2024 / GHS Rev. 7):"
        r"Classification(?:\s+of\s+the\s+(?:substance\s+or\s+)?mixture)?\s*(?:\([^)]*\))?\s*:?",
    ]
    end = r"(?:Label\s+Elements:?|(?:GHS\s+)?Signal\s+Word:?|Hazard\s+Pictograms:?)"
    for heading in heading_patterns:
        m = re.search(
            rf"{heading}\s*(.*?)\s*{end}",
            section2_text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            raw = m.group(1).strip()
            lines = [l.strip().lstrip("•\u2022-–— ").strip()
                     for l in raw.split("\n") if l.strip()]
            lines = [l for l in lines if l]
            cut = next((i for i, l in enumerate(lines)
                        if i > 0 and re.match(r"(Physical Hazards:|Not Classified For|Health Hazards:)", l, re.I)), None)
            if cut is not None:
                lines = lines[:cut]
            lines = [l for l in lines if not re.match(r"(Page \d+ of \d+|DCN:|(Physical|Health|Environmental) hazards$|None expected|Not adopted under OSHA)", l, re.I)]
            if lines:
                return lines
    return []


def derive_pictograms(classification_lines, hazard_statements=None):
    """Map classification lines (and, as a cross-check, the H-codes) to GHS
    pictogram codes. Returns a sorted, de-duplicated list of codes."""
    found = set()
    for hs in hazard_statements or []:
        code = HCODE_TO_PICTOGRAM.get(hs.get("code"))
        if code:
            found.add(code)
    if found:
        # The label's own H-statements are the authoritative source: the
        # Classification block can also contain "Not classified for: ..."
        # prose whose words (corrosion, aquatic, ...) are NOT hazards.
        return sorted(found)
    for line in classification_lines:
        for hc in re.findall(r"H\d{3}", line):
            if hc in HCODE_TO_PICTOGRAM:
                found.add(HCODE_TO_PICTOGRAM[hc])
    for line in classification_lines:
        found |= _line_pictograms(line)
    return sorted(found)


def _line_pictograms(line):
    """Pictograms for one Classification line, category-aware: Acute
    toxicity Cat 1-3 is the skull (GHS06) but Cat 4 is the exclamation mark
    (GHS07, Cat 5 has none); STOT single exposure Cat 3 (irritation /
    drowsiness) is the exclamation mark, Cat 1-2 and repeated exposure are
    the health-hazard symbol (GHS08)."""
    lower = line.lower()
    out = set()
    cat = re.search(r"categor(?:y|ies)\s*([1-5])", lower)
    cat = int(cat.group(1)) if cat else None
    for keyword, code in CLASSIFICATION_TO_PICTOGRAM.items():
        if keyword not in lower:
            continue
        if keyword in ("serious eye damage", "eye damage") and "irrit" in lower and cat != 1 and "h318" not in lower:
            continue  # "Serious eye damage/eye irritation - Category 2A" is the exclamation mark, not corrosion
        if keyword == "acute toxicity":
            if cat in (1, 2, 3):
                out.add("GHS06")
            elif cat == 4:
                out.add("GHS07")
            elif cat is None:
                out.add("GHS06")  # unknown severity: keep the safer, stricter symbol
        elif keyword == "stot":
            single = re.search(r"\bse\b|single", lower)
            if single and cat == 3:
                out.add("GHS07")
            else:
                out.add("GHS08")
        else:
            out.add(code)
    return out


def extract_hazard_statements(section2_text):
    """Extract hazard statements from the 'Hazard Statements:' subsection
    specifically -- NOT from the Classification block, which sometimes
    also contains H-codes inline (e.g. 'H315 – Skin Irritation Category
    2') that would otherwise get matched first and produce the wrong
    text. Separator between code and text varies by document: some use
    '–' (dash), others use ':' (colon).

    Older Forza SDS list the statements as plain sentences with NO H-codes
    ('Causes skin and eye irritation'); those come back with code=None.
    A literal 'None' (non-hazardous products) yields an empty list."""
    m = re.search(
        r"Hazard\s+Statement\(?s\)?:?\s*(.*?)(?=\n\s*(?:GHS\s+)?(?:Precautionary\s+Statement|Other Hazards|Prevention|Hazards? ?\(?s?\)? not otherwise|Hazard\s+(?:symbol|pictogram)|Revision Date)|\s+GHS\s*\n?\s*Hazard symbol|\nSECTION|\Z)",
        section2_text,
        re.DOTALL | re.IGNORECASE,
    )
    search_text = m.group(1) if m else section2_text
    pattern = re.compile(r"(H\d{3})\s*[:\-–—]\s*([^\n]+)")
    coded = [{"code": mm.group(1), "text": mm.group(2).strip()}
             for mm in pattern.finditer(search_text)]
    if coded:
        return coded
    if not m:
        return []
    # No H-codes: treat each line of the block as one statement, merging
    # wrapped continuation lines (start lowercase) into the previous one.
    lines = [re.sub(r"^(?:[•\u2022o\-–—]\s+|[•\u2022\-–—]+\s*)", "", l.strip()).strip() for l in m.group(1).split("\n")]
    lines = [l for l in lines if l and not re.match(r"(Page\s+\d+\s+of\s+\d+|DCN:)", l, re.I)]
    merged = []
    for line in lines:
        if merged and line[0].islower():
            merged[-1] += " " + line
        else:
            merged.append(line)
    merged = [l for l in merged if l.lower().rstrip(".") not in ("none", "n/a", "not applicable")]
    return [{"code": None, "text": l} for l in merged]


_P_LINE_RE = re.compile(
    r"^(?:[o•\u2022\-–—*]\s+)?"                       # optional bullet marker
    r"(P\d{3}(?:\s*\+\s*P\d{3})*)"                    # P-code(s), e.g. P302+P352
    r"\s*[-–—:]?\s*(.*)$"                              # optional separator, then text
)
_P_SUBHEAD_RE = re.compile(r"^(Prevention|Response|Storage|Disposal|Precautionary [Ss]tatements)\s*:?\s*$")
_P_END_RE = re.compile(r"^(Contains\s|Other [Hh]azards|Hazards? ?\(?s?\)? not otherwise|Percentage of|SECTION|Curing note)", re.I)
_P_PAGE_RE = re.compile(r"^(Page\s+\d+\s+of\s+\d+|DCN:)", re.I)


def _extract_p_statements_by_line(section2_text):
    """Line-based P-statement parser. Handles documents where the code is
    followed directly by its text with no dash/colon ('o P201 Obtain special
    instructions'), 'o'/bullet markers, and Prevention/Response/Storage/
    Disposal sub-headings, with wrapped continuation lines. Older SDS list
    the statements as plain bullets with no P-codes at all; those come back
    with code=None."""
    m = re.search(r"Precautionary\s+Statement\(?s\)?:?", section2_text, re.I)
    text = section2_text[m.end():] if m else section2_text
    results, current = [], None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _P_PAGE_RE.match(line) or re.match(r"^\d{1,2}$", line):
            continue   # running page header/footer, not content
        if _P_END_RE.match(line):
            break
        if _P_SUBHEAD_RE.match(line):
            current = None
            continue
        pm = _P_LINE_RE.match(line)
        if pm:
            code = re.sub(r"\s*\+\s*", " + ", pm.group(1).strip())
            current = {"code": code, "text": pm.group(2).strip()}
            results.append(current)
        elif current is not None and not re.match(r"^[o•\u2022]\s+", line):
            current["text"] = (current["text"] + " " + line).strip()
        else:
            current = None
    coded = [r for r in results if r["text"]]
    if coded:
        for r in coded:
            r["text"] = " ".join(r["text"].split())
        return coded

    # No P-codes anywhere: one statement per line/bullet, wrapped lines merged.
    items = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or _P_PAGE_RE.match(line) or re.match(r"^\d{1,2}$", line):
            continue
        if _P_END_RE.match(line):
            break
        if _P_SUBHEAD_RE.match(line):
            continue
        is_bullet = bool(re.match(r"^[•\u2022o\-–—*]\s+", line))
        line = re.sub(r"^[•\u2022o\-–—*]\s+", "", line).strip()
        if items and not is_bullet and line[:1].islower():
            items[-1] += " " + line
        else:
            items.append(line)
    items = [" ".join(i.split()) for i in items
             if i.lower().rstrip(".") not in ("none", "none needed", "n/a", "not applicable")]
    return [{"code": None, "text": i} for i in items]


def extract_precautionary_statements(section2_text):
    """Extract P-code lines, including compound codes like 'P302 + P352'.
    Falls back to plain-sentence extraction when a document lists
    precautionary instructions without P-codes at all (seen in some SDS
    variants) -- in that case each line under 'Precautionary Statements:'
    up to the next section heading is treated as one statement."""
    by_line = _extract_p_statements_by_line(section2_text)
    if by_line:
        return by_line

    _p_stop = r"•|\u2022|Other [Hh]azards|P\d{3}|SECTION|Precautionary [Ss]tatements:|Curing note:|Hazards not otherwise classified|Page\s+\d+\s+of\s+\d+|DCN:"
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
                # Real ingredient tables carry a concentration column; this
                # rejects look-alikes such as the Section 15 state
                # right-to-know table (Component | CAS No. | MA | NJ | PA).
                has_conc_col = any(k in header for k in ("conc", "%", "weight", "wt", "percent", "range", "content"))
                if not (has_name_col and has_cas_col and has_conc_col):
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


def _join_wrapped(lines):
    """Join PDF-wrapped lines into one string. A line ending in '-' whose
    next line starts lowercase is a wrapped hyphenated word ('well-' /
    'ventilated'), so join without a space to avoid 'well- ventilated'."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out.endswith("-") and line[:1].islower():
            out += line
        else:
            out = (out + " " + line) if out else line
    return " ".join(out.split())


def _numbered_field(section_text, start_labels, stop_labels):
    """Legacy numbered layout: '<Label> text...' on one line, wrapped lines
    below, next label starts the next field."""
    m = re.search(rf"(?:{'|'.join(start_labels)})\s+(.*?)(?=\n\s*(?:{'|'.join(stop_labels)})|\Z)",
                  section_text, re.S | re.I)
    if not m:
        return None
    lines = [l.strip() for l in m.group(1).split("\n") if l.strip()
             and not re.match(r"^(\d{1,2}|Disposal methods)$", l.strip(), re.I)]
    return _join_wrapped(lines) or None


def extract_legacy_ingredients(section3_text):
    """Text-only ingredient parse for layouts where Section 3 is not a table:
    '<name> / CAS number: <cas>' with the percent range split around the name
    ('30-', 'Methyl Ethyl Ketone', '60%')."""
    out, buf = [], []
    for raw in section3_text.split("\n"):
        line = raw.strip()
        if not line or re.match(r"^(Mixtures?|Substances?)$", line, re.I):
            continue
        m = re.match(r"CAS number:?\s*([\d\-]+|[A-Za-z /]+)?", line, re.I)
        if m:
            pct = " ".join(b for b in buf if re.fullmatch(r"[<>≤≥]?\s*[\d.]+\s*-?\s*[\d.]*\s*%?", b))
            pct = re.sub(r"\s*-\s*", "-", pct).strip()
            name = " ".join(b for b in buf if b not in pct.split() and not re.fullmatch(r"[<>≤≥]?\s*[\d.]+\s*-?\s*[\d.]*\s*%?", b))
            if name:
                out.append({"chemical_name": name.strip(), "cas_number": (m.group(1) or "").strip(),
                            "percent": pct, "classification": ""})
            buf = []
            continue
        if re.match(r"^(Classification|The full text|Flam\.|Acute|Eye|Skin|STOT|Asp\.|Carc|Repr|Aquatic|Muta|Resp\.|Press\.|Self|Org\.)", line, re.I):
            buf = []   # classification block belongs to the previous ingredient
            continue
        buf.append(line)
    return out


_ROW_RE = re.compile(
    r"^(?P<name>[A-Za-z][^\n]*?)\s+(?P<cas>\d{2,7}-\d{2}-\d(?:;\s*\d{2,7}-\d{2}-\d)*|Proprietary|\[See[^\]]*\]|Mixture)\s+"
    r"(?P<pct>[<>≤≥]?\s*[\d.]+(?:\s*[-–]\s*[\d.]+)?\s*%?|Balance)\s*$", re.I)


def extract_table_rows_from_text(section3_text):
    """Fallback when the ingredient table's wrapped rows defeat the table
    extractor: pick rows by '<name> <CAS|Proprietary> <percent>' on one line."""
    out = []
    for raw in section3_text.split("\n"):
        m = _ROW_RE.match(raw.strip())
        if not m:
            continue
        name = re.sub(r"\s+\d{4,6}(\s*\([^)]*\))?$", "", m.group("name")).strip()
        if name:
            out.append({"chemical_name": name, "cas_number": m.group("cas"),
                        "percent": m.group("pct").replace("–", "-"), "classification": ""})
    return out


def legacy_meta(full_text):
    m = re.search(r"SDS No\.?\s*([A-Za-z0-9\-]+)", full_text)
    d = re.search(r"Revision Date\s*:?\s*([0-9/]+|[A-Za-z]+\.? \d{1,2}, \d{4})", full_text)
    return {"legacy_sds_no": m.group(1) if m else "", "revision_date": d.group(1) if d else ""}


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
            rf"{re.escape(label)}\s*:?\s*(.+?)(?=\n[A-Z][A-Za-z /]+\s*:|\nSECTION|$)",
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
                text = _join_wrapped(lines)
            text = re.sub(r"^[:\s]+", "", text or "").replace("wellventilated", "well-ventilated")
            if text:
                return text
    return None


def _strip_title(section_text):
    """Section bodies can start with the rest of the heading ('. DISPOSAL
    CONSIDERATIONS', '. HANDLING AND STORAGE'); drop it so field labels such as
    'Disposal' or 'Storage' are not matched inside the heading itself."""
    if section_text.lstrip().startswith(".") or re.match(r"^[A-Z /,&\-]{6,}$", section_text.split("\n", 1)[0].strip() or "x"):
        parts = section_text.split("\n", 1)
        return parts[1] if len(parts) > 1 else ""
    return section_text


def parse_sds(pdf_path):
    full_text = extract_full_text(pdf_path)
    sections = split_into_sections(full_text)

    section2 = sections.get("2", "")
    section3 = sections.get("3", "")
    section7 = _strip_title(sections.get("7", ""))
    section13 = _strip_title(sections.get("13", ""))

    classification_lines = extract_classification(section2)
    hazard_statements = extract_hazard_statements(section2)

    result = {
        "signal_word": extract_signal_word(section2),
        "classification": classification_lines,
        "pictograms": derive_pictograms(classification_lines, hazard_statements),
        "hazard_statements": hazard_statements,
        "precautionary_statements": extract_precautionary_statements(section2),
        "ingredients": extract_ingredients(pdf_path),
        "storage": extract_field(section7, ["Conditions for Safe Storage", "Storage"]),
        "handling": extract_field(section7, ["Precautions for Safe Handling", "Advice on safe handling", "Handling"]),
        "disposal": extract_field(section13, ["Waste Disposal Method", "Waste from residues", "Waste treatment methods", "Waste treatment", "Disposal"]),
    }
    if not result["ingredients"]:
        result["ingredients"] = extract_table_rows_from_text(section3)
    if "SECTION" not in full_text.upper().split("2")[0] and re.search(r"^\s*2\.\s*Hazards?\(?s?\)?\s+identification", full_text, re.M | re.I):
        result["layout"] = "numbered-legacy"
        result.update(legacy_meta(full_text))
        if not result["ingredients"]:
            result["ingredients"] = extract_legacy_ingredients(section3)
        _v = _numbered_field(section7, ["Storage precautions"], ["Specific end use", "Conditions for"])
        if _v and len(_v) > 25:
            result["storage"] = _v
        _v = _numbered_field(section7, ["Usage precautions"], ["Advice on general", "Conditions for"])
        if _v and len(_v) > 25:
            result["handling"] = _v
        _v = _numbered_field(section13, ["Waste treatment methods", "Disposal methods"], ["14\\."])
        if _v and len(_v) > 25:
            result["disposal"] = _v
    return result


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/mnt/user-data/uploads/ForzaEagle_T-OS164_Transportation_Sealant_SDS_V1_08_11_2026.pdf"
    data = parse_sds(path)
    print(json.dumps(data, indent=2))
