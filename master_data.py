"""Read label inputs from the Forza product-data master (data/*.csv).

Replaces parsing an uploaded SDS/TDS for any product that is in the master:
  * TDS tab            -> product name, vertical, directions bullets, storage (tape)
  * Product-SDS map    -> which SDS file(s) apply to a product code
  * SDS tab            -> signal word, pictograms, H/P statements, ingredients,
                          storage and disposal text

The result for an SDS has the same shape parse_sds() returns, so the renderer
and every include/exclude option in the form work unchanged.

Read-only. Needs GITHUB_TOKEN (Streamlit secret) like the draft-saving apps.
Tests can swap the data source with set_loader().
"""
import re

_loader = None


def set_loader(fn):
    """fn(tab) -> list of row dicts. Used by tests / offline runs."""
    global _loader
    _loader = fn


def _load_uncached(tab):
    if _loader is not None:
        return _loader(tab)
    from master_repo import read_master
    return read_master(tab)


try:
    import streamlit as st

    @st.cache_data(ttl=300, show_spinner=False)
    def _load_cached(tab):
        return _load_uncached(tab)
except Exception:  # streamlit not available (tests)
    def _load_cached(tab):
        return _load_uncached(tab)


def _rows(tab):
    return _load_uncached(tab) if _loader is not None else _load_cached(tab)


def refresh():
    try:
        _load_cached.clear()
    except Exception:
        pass


# ---------------------------------------------------------------- products
_BRAND_TO_CATEGORY = {"BOND": "Adhesive", "SEAL": "Sealant", "TAPE": "Tape"}
_VERTICALS = {"Industrial", "Construction", "Marine", "Transportation", "Insulation", "Composites"}


def _lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def product_list():
    out = []
    for r in _rows("tds"):
        code = (r.get("Product Code") or "").strip()
        if not code:
            continue
        cat = (r.get("Category") or "").strip()
        out.append({
            "code": code,
            "title": (r.get("TDS Title") or r.get("Product Type") or "").strip(),
            "category": _BRAND_TO_CATEGORY.get((r.get("Brand Line") or "").strip()),
            "vertical": cat if cat in _VERTICALS else None,
            "packaging": _lines(r.get("Packaging")),
        })
    return sorted(out, key=lambda p: p["code"].upper())


def tds_for(code):
    for r in _rows("tds"):
        if (r.get("Product Code") or "").strip() == code:
            return {
                "bullets": _lines(r.get("Application Instructions")),
                "storage": " ".join(_lines(r.get("Storage"))) or None,
            }
    return {"bullets": [], "storage": None}


# --------------------------------------------------------------------- SDS
_MAP_LINE = re.compile(r"^(?P<label>.*?)\s*\[(?P<file>[^\]]+)\]\s*$")


def sds_choices(code):
    """[{label, file_name}] for the product; empty when the master has no SDS."""
    for r in _rows("product_sds_map"):
        if (r.get("Product Code") or "").strip() == code:
            out = []
            for line in _lines(r.get("SDS File(s)")):
                m = _MAP_LINE.match(line)
                if m:
                    out.append({"label": m["label"].strip() or m["file"], "file_name": m["file"].strip()})
            return out
    return []


_H = re.compile(r"(H\d{3}(?:\s*\+\s*H\d{3})*)\s*[–—:\-]?\s*")
_P = re.compile(r"(P\d{3}(?:\s*\+\s*P\d{3})*)\s*[–—:\-,]?\s*")


def _statements(text, rx):
    """Split master statement text into [{code, text}]. Lines can hold one or
    several coded statements, or plain text (older SDS) with code ""."""
    items = []
    for line in _lines(text):
        ms = list(rx.finditer(line))
        if not ms:
            items.append({"code": "", "text": line})
            continue
        lead = line[:ms[0].start()].strip()
        if lead:
            items.append({"code": "", "text": lead})
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
            code = re.sub(r"\s*\+\s*", " + ", m.group(1))
            body = line[m.end():end].strip(" ,;")
            if body:
                items.append({"code": code, "text": body})
    return items


_NON_HAZ = re.compile(r"non[\s-]*haz|not\s+classified\s+as\s+hazardous|other\s+(?:ingredients|components)|\bdyes?\b", re.I)


def is_non_hazardous(name):
    """True for catch-all SDS lines such as 'Other Non-Hazardous Ingredients'
    and for dyes (Red/Green/Blue Dye). Labels only list hazardous ingredients,
    so these start unchecked."""
    return bool(_NON_HAZ.search(name or ""))


def _ingredients(text):
    out = []
    for line in _lines(text):
        parts = [p.strip() for p in line.split("|")]
        out.append({"chemical_name": parts[0],
                    "cas_number": parts[1] if len(parts) > 1 else "",
                    "percent": parts[2] if len(parts) > 2 else ""})
    return out


def _clean_block(s):
    """Master storage/disposal text sometimes starts mid-sentence (a cut-off
    fragment from the original SDS parse) or carries a page footer. Drop those."""
    s = re.sub(r"\s*Page \d+ of \d+\s*", " ", (s or "")).strip()
    if s and (s[0].islower() or s[0] in ",;"):
        m = re.search(r"•\s*|(?<=[.!?])\s+(?=[A-Z])", s)
        s = s[m.end():].strip() if m else s
    return s


def sds_data_for(file_name):
    """parse_sds()-shaped dict for one SDS file in the master, or None."""
    for r in _rows("sds"):
        if (r.get("File Name") or "").strip() != file_name:
            continue
        hazards = _statements(r.get("Hazard Statements"), _H)
        for h in hazards:
            h.setdefault("code", "")
        signal = (r.get("Signal Word") or "").strip()
        signal = signal if signal.lower() in ("danger", "warning") else None
        pics = [p.strip() for p in (r.get("Pictograms") or "").split(",") if re.match(r"^GHS0\d$", p.strip())]
        classification = _lines(r.get("Classification"))
        if not pics:
            try:
                from parse_sds import derive_pictograms
                pics = derive_pictograms(classification, [h for h in hazards if h["code"]])
            except Exception:
                pics = []
        return {
            "signal_word": signal,
            "classification": classification,
            "pictograms": pics,
            "hazard_statements": hazards,
            "precautionary_statements": _statements(r.get("Precautionary Statements"), _P),
            "ingredients": _ingredients(r.get("Ingredients (Name | CAS | %)")),
            "storage": _clean_block(r.get("Storage")),
            "handling": _clean_block(r.get("Handling")),
            "disposal": _clean_block(r.get("Disposal")),
            "_master_flags": (r.get("Parse Flags") or "").strip(),
            "_master_file": file_name,
        }
    return None


# ------------------------------------------------- Part A + Part B combining
COMBINED_LABEL = "Combine Part A + Part B (dual cartridge)"
_PART = re.compile(r"part[\s_-]*([ab])\b", re.I)


def part_choices(choices):
    """{'A': choice, 'B': choice} when the SDS list holds exactly one Part A and
    one Part B file, else {}."""
    found = {}
    for c in choices:
        m = _PART.search(c["label"]) or _PART.search(c["file_name"])
        if m:
            found.setdefault(m.group(1).upper(), c)
    return found if set(found) == {"A", "B"} and len(choices) == 2 else {}


def is_dual_cartridge_packaging(packaging):
    return any(re.search(r"\d\s*m[lL]\b", p) and "cartridge" in p.lower() for p in packaging)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _merge_statements(*lists):
    seen, out = set(), []
    for lst in lists:
        for s in lst:
            key = re.sub(r"\s+", "", s.get("code") or "").upper() or _norm(s["text"])
            if key in seen or _norm(s["text"]) in seen:
                continue
            seen.add(key)
            seen.add(_norm(s["text"]))
            out.append(s)
    return out


def combine_sds(a, b):
    """Merge two parse_sds()-shaped dicts (Part A, Part B) into one for a
    dual-cartridge label. Duplicates are removed; the more severe signal word
    wins; pictograms are unioned."""
    sev = {"danger": 2, "warning": 1}
    words = [w for w in (a.get("signal_word"), b.get("signal_word")) if w]
    signal = max(words, key=lambda w: sev.get(w.lower(), 0)) if words else None
    haz = _merge_statements(a["hazard_statements"], b["hazard_statements"])
    pre = _merge_statements(a["precautionary_statements"], b["precautionary_statements"])
    ing, seen = [], set()
    for i in a["ingredients"] + b["ingredients"]:
        k = (_norm(i["chemical_name"]), _norm(i["cas_number"]))
        if k not in seen:
            seen.add(k)
            ing.append(i)
    cls = []
    for line in a.get("classification", []) + b.get("classification", []):
        if line not in cls:
            cls.append(line)
    removed = (len(a["hazard_statements"]) + len(b["hazard_statements"]) - len(haz)
               + len(a["precautionary_statements"]) + len(b["precautionary_statements"]) - len(pre))
    flags = "; ".join(f"Part {n}: {d['_master_flags']}" for n, d in (("A", a), ("B", b)) if d.get("_master_flags"))
    return {
        "signal_word": signal,
        "classification": cls,
        "pictograms": sorted(set(a["pictograms"]) | set(b["pictograms"])),
        "hazard_statements": haz,
        "precautionary_statements": pre,
        "ingredients": ing,
        "storage": a["storage"] or b["storage"],
        "handling": a["handling"] or b["handling"],
        "disposal": a["disposal"] or b["disposal"],
        "_master_flags": flags,
        "_master_file": f"{a['_master_file']} + {b['_master_file']}",
        "_combined_removed": removed,
    }
