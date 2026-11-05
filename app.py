"""
Forza Label Generator -- selection form.

Ties together parse_sds, parse_tds, and label_renderer into a single
interactive tool: pick the product basics, drop in the SDS/TDS, review/edit
the extracted text, and generate the label.

Run with: streamlit run app.py
"""

import io
import os
import re
import tempfile

import streamlit as st
import pymupdf as fitz
from PIL import Image

import master_data
from parse_sds import parse_sds
from parse_tds import extract_product_application_bullets, extract_storage_info
from label_renderer import render_label, render_compact_label, render_tape_label
from label_renderer_small import render_small_label, SMALL_DIMENSION
from product_sizes import PRODUCT_SIZES, get_label_dimensions
from template_config import (
    CATEGORIES, available_categories_for_product, REQUIRES_SDS,
    dimension_group_for_product, is_compact_layout, get_template,
    get_box_label_template, has_template,
)

VERTICAL_BACKGROUNDS = {
    "Industrial": "vertical_backgrounds/Industrial.png",  # default (first item; st.selectbox selects index 0)
    "Composites": "vertical_backgrounds/Composites.jpg",
    "Construction": "vertical_backgrounds/Construction.png",
    "Insulation": "vertical_backgrounds/Insulation.png",
    "Marine": "vertical_backgrounds/Marine.png",
    "Transportation": "vertical_backgrounds/Transportation.png",
}

# Tape's baked backgrounds -- vertical-keyed only (no dimension_group,
# since Tape always uses the same 8x4in canvas regardless of vertical).
# Only Transportation and Marine have real baked backgrounds built so
# far (measured from their true blank reference templates); other
# verticals aren't in this dict yet and fall back to drawing from
# scratch via VERTICAL_BACKGROUNDS instead.
TAPE_BACKGROUNDS = {
    "Transportation": "baked_backgrounds_wip/tape_transportation_8x4_v1_current.png",
    "Marine": "baked_backgrounds_wip/tape_marine_8x4_v1_current.png",
}

# All seven vertical icons extracted directly from the Brand Standards
# doc's "Industry Icon Lockups" page -- every vertical has a real icon now,
# no placeholders needed.
BADGE_ICONS = {
    "Construction": "vertical_badge_icons/Construction.png",
    "Insulation": "vertical_badge_icons/Insulation.png",
    "Composites": "vertical_badge_icons/Composites.png",
    "Foam": "vertical_badge_icons/Foam.png",
    "Industrial": "vertical_badge_icons/Industrial.png",
    "Marine": "vertical_badge_icons/Marine.png",
    "Transportation": "vertical_badge_icons/Transportation.png",
}
DEFAULT_BADGE_ICON = "vertical_badge_icons/Construction.png"


DUAL_SIZES = ["50ml", "300ml", "400ml"]
DUAL_SIZE_OTHER = "Other..."

_SIZE_TYPE_SPLIT_RE = re.compile(r"^(\d[\d.]*\s*[A-Za-z]+)\s+(.+)$")


def _split_product_size_type(product_type):
    """Split a product_type string like '10.1oz Cartridge' into its size
    ('10.1oz') and type ('Cartridge') components, for the PDF filename
    convention. A few product types have no distinct leading size (e.g.
    'Gallon Can') -- these fall back to an empty size with the whole
    string as type, since there's nothing to split out. 'Aerosol Can' is
    special-cased to just 'Aerosol' in the filename, per direct
    instruction -- 'Gallon Can' is deliberately left as-is."""
    if product_type == "Aerosol Can":
        return "", "Aerosol"
    m = _SIZE_TYPE_SPLIT_RE.match(product_type)
    if m:
        return m.group(1), m.group(2)
    return "", product_type


def _sanitize_filename_part(s):
    """Replace characters that are awkward or unsafe in filenames.
    Slashes become hyphens (deleting them outright would silently merge
    adjacent digits, e.g. tape's "3/4in" turning into "34in"); the rest
    (quotes, colons, etc.) are just stripped. Spaces and most punctuation
    used in these fields (periods, hyphens) are left alone."""
    s = s.replace("/", "-")
    return re.sub(r'[\\:*?"<>|]', "", s).strip()


def build_label_filename(ap_number, revision_number, product_code, product_type,
                          canvas_size_in, is_tape=False, tape_size_label="", is_box=False):
    """Build the standardized PDF filename:
    APNumber_N#-ProductCode_ProductSize_ProductType_LabelSize_PDFSize
    'PDFSize' is a fixed literal suffix, everything else depends on input.
    Tape has no product_type in the Cartridge/Sausage sense -- its own
    size (e.g. '3/4in x 108ft') stands in for the ProductSize/ProductType
    pair instead.
    """
    ap_part = f"{ap_number}_N{revision_number}" if ap_number and revision_number else (ap_number or "")
    label_size = f"{canvas_size_in[0]:g}x{canvas_size_in[1]:g}"
    if is_tape:
        size_type_part = tape_size_label or ""
    else:
        size, ptype = _split_product_size_type(product_type)
        size_type_part = "_".join(p for p in [size, ptype] if p)
    # Hyphen specifically between the AP/revision part and the product
    # code -- "APNumber_N#-ProductCode_..." -- every other join is an
    # underscore.
    ap_and_code = "-".join(p for p in [ap_part, product_code] if p)
    # Convention: AP_N#-Code_[BXLBL]_Size_Type_Dimensions_PDFsize. The BXLBL slot
    # is kept (left empty) on single-product labels, giving the double underscore
    # in e.g. AP1708_N1-OS40__10.1oz_Cartridge_8x6_PDFsize.
    box_part = "BXLBL" if is_box else ""
    parts = [ap_and_code, box_part, size_type_part, label_size, "PDFsize"]
    name = "_".join(_sanitize_filename_part(p) for p in parts[:1] + [parts[1]] + [p for p in parts[2:] if p])
    return f"{name}.pdf"


def _save_upload_to_tmp(uploaded_file):
    """Streamlit's UploadedFile isn't a filesystem path -- pdfplumber/fitz
    need one, so write it to a temp file and hand back the path."""
    suffix = os.path.splitext(uploaded_file.name)[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    return tmp.name


st.set_page_config(page_title="Forza Label Generator", layout="wide")


def _load_brand_fonts_css():
    """Inject Forza's real brand fonts (Kallisto Heavy for headers,
    Poppins for body text, per Brand_Standards-Forza_V6.pdf page 7) as
    base64-embedded @font-face rules, rather than relying on Streamlit's
    static file serving (which isn't guaranteed to expose arbitrary
    package files as URLs depending on how/where this is deployed).
    Applied to Streamlit's actual heading/body element classes, since
    generic h1/h2/p selectors don't reliably match Streamlit's internal
    markup."""
    import base64
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    kallisto_path = os.path.join(fonts_dir, "Kallisto-Heavy.otf")
    poppins_reg_path = os.path.join(fonts_dir, "Poppins-Regular.ttf")
    poppins_bold_path = os.path.join(fonts_dir, "Poppins-Bold.ttf")
    with open(kallisto_path, "rb") as f:
        kallisto_b64 = base64.b64encode(f.read()).decode()
    with open(poppins_reg_path, "rb") as f:
        poppins_reg_b64 = base64.b64encode(f.read()).decode()
    with open(poppins_bold_path, "rb") as f:
        poppins_bold_b64 = base64.b64encode(f.read()).decode()

    st.markdown(f"""
    <style>
    @font-face {{
        font-family: 'Kallisto Heavy';
        src: url(data:font/otf;base64,{kallisto_b64}) format('opentype');
        font-display: swap;
    }}
    @font-face {{
        font-family: 'Poppins';
        src: url(data:font/ttf;base64,{poppins_reg_b64}) format('truetype');
        font-weight: normal;
        font-display: swap;
    }}
    @font-face {{
        font-family: 'Poppins';
        src: url(data:font/ttf;base64,{poppins_bold_b64}) format('truetype');
        font-weight: bold;
        font-display: swap;
    }}
    /* Narrowly targeted to genuine text containers only -- avoids
    Streamlit's internal structural/wrapper elements (which may include
    hidden duplicate elements used for width calculations etc.) that a
    broader wildcard like [class*="st-"] or bare div/span would also
    have matched, which is what caused the earlier double-text bug on
    buttons. */
    .stMarkdown p, .stCaption, .stTextInput label, .stSelectbox label,
    .stRadio label, .stTextArea label, .stButton button p {{
        font-family: 'Poppins', sans-serif;
    }}
    h1, h2, h3 {{
        font-family: 'Kallisto Heavy', sans-serif !important;
        color: #1B3764;
    }}
    </style>
    """, unsafe_allow_html=True)


_load_brand_fonts_css()

_logo_col, _title_col = st.columns([1, 3])
with _logo_col:
    st.image("logos/corporate_teal_logo.png", use_container_width=True)
with _title_col:
    st.title("Forza Label Generator")
    st.caption("Drop in an SDS/TDS, fill in the label text, and generate a print-ready label.")

# Session state holds parsed data across reruns so editing a text field
# doesn't force a re-parse of the PDFs.
if "sds_data" not in st.session_state:
    st.session_state.sds_data = None
if "tds_bullets" not in st.session_state:
    st.session_state.tds_bullets = []
if "tds_storage_info" not in st.session_state:
    st.session_state.tds_storage_info = None
if "rendered_label" not in st.session_state:
    st.session_state.rendered_label = None
if "dropped_content" not in st.session_state:
    st.session_state.dropped_content = None

def _label_size_matches(row_size, ptype, cat):
    row_size = (row_size or "").strip().lower()
    if cat == "Tape":
        return True
    if ptype == "Dual Cartridge":
        return row_size.endswith("dual cartridge") or row_size.endswith("dual cartridge (4x2)")
    return row_size == (ptype or "").strip().lower()


def _row_is_box(r):
    return (r.get("Label Type") or "").strip().lower().startswith("box")


def _want_box():
    return st.session_state.get("box_label_radio", "No") == "Yes"


def _candidate_labels(code, ptype, cat):
    """Existing master labels for this code + product type, narrowed to item vs
    box label (and to the chosen color, when one has been set)."""
    rows = [r for r in master_data.label_rows(code)
            if _label_size_matches(r.get("Size / Container"), ptype, cat)
            and _row_is_box(r) == _want_box()]
    if ptype == "Dual Cartridge":
        # 4x2 item labels are stored as "<size> Dual Cartridge (4x2)"; box labels are always 6x4
        _small = (not _want_box()) and st.session_state.get("dual_item_size") == "4x2"
        rows = [r for r in rows if ("(4x2)" in (r.get("Size / Container") or "")) == _small]
    return rows


def _label_option(r):
    bits = [(r.get("AP #") or "").strip(), (r.get("Revision") or "").strip()]
    head = " ".join(b for b in bits if b) or "no AP #"
    tail = " / ".join(x for x in [(r.get("Size / Container") or "").strip(), (r.get("Color") or "").strip(),
                                  "BOX LABEL" if _row_is_box(r) else ""] if x)
    return f"{head} -- {tail}"


def _apply_label_row(row):
    """Prefill the label fields that do not come from the TDS/SDS (AP #, revision,
    color, orange-bar text, tape/dual-cartridge size) from an existing master label."""
    ss = st.session_state
    ss["ap_number"] = (row.get("AP #") or "").strip()
    ss["revision_number"] = re.sub(r"^[Nn]", "", (row.get("Revision") or "").strip())
    color = (row.get("Color") or "").strip()
    ss["has_color"] = "Yes" if color else "No"
    ss["label_color"] = color
    left, right = (row.get("Left Bar Text") or "").strip(), (row.get("Right Bar Text") or "").strip()
    ss["sales_description"] = left
    ss["sales_description_1"] = left
    ss["sales_description_2"] = right
    size = (row.get("Size / Container") or "").strip()
    if ss.get("product_type") == "Dual Cartridge":
        if "(4x2)" in size:
            ss["dual_item_size"] = "4x2"
        m = re.match(r"^(\d+(?:\.\d+)?\s*ml)\b", size, re.I)
        if m:
            sz = m.group(1).replace(" ", "").lower()
            if sz in DUAL_SIZES:
                ss["dual_size_choice"] = sz
            else:
                ss["dual_size_choice"] = DUAL_SIZE_OTHER
                ss["dual_size_other"] = sz
    if ss.get("category") == "Tape":
        ss["tape_size_text"] = size


def _apply_existing_choice():
    ss = st.session_state
    row = ss.get("_existing_label_map", {}).get(ss.get("existing_label_choice"))
    if row:
        _apply_label_row(row)


def _load_from_master():
    """Button callback: pull TDS + SDS data for the chosen product from the
    master and prefill the form. Runs before the widgets are drawn, so it can
    set their values."""
    ss = st.session_state
    code = (ss.get("master_code_label") or "").split(" -- ")[0]
    prod = ss.get("_master_products", {}).get(code)
    if not prod:
        return
    # Reset checkbox state from any earlier product
    for k in [k for k in ss.keys() if k.startswith("bullet_") or k.startswith("ingredient_")]:
        del ss[k]
    tds = master_data.tds_for(code)
    ss.tds_bullets = tds["bullets"]
    cat = prod.get("category")
    if cat in CATEGORIES:
        ss["category"] = cat
    ss.tds_storage_info = tds["storage"] if cat == "Tape" else None
    if prod.get("vertical") in VERTICAL_BACKGROUNDS:
        ss["vertical_name"] = prod["vertical"]
    ss["product_code"] = code
    ss["product_name"] = prod.get("title") or ""
    ss["_name_from_master"] = bool(ss["product_name"])
    # Best-effort match of the master's packaging to a label size
    if cat and cat != "Tape":
        opts = [p for p in PRODUCT_SIZES if cat in available_categories_for_product(p) and PRODUCT_SIZES[p]["item_label"]]
        _dual = next((pk for pk in prod.get("packaging", [])
                      if re.search(r"\d\s*m[lL]\b", pk) and "cartridge" in pk.lower()), None)
        if _dual and master_data.part_choices(master_data.sds_choices(code)):
            ss["product_type"] = "Dual Cartridge"
            _ml = re.search(r"(\d+(?:\.\d+)?)\s*m[lL]\b", _dual).group(1)
            _sz = f"{_ml}ml"
            if _sz in DUAL_SIZES:
                ss["dual_size_choice"] = _sz
            else:
                ss["dual_size_choice"] = DUAL_SIZE_OTHER
                ss["dual_size_other"] = _sz
        for pk in ([] if ss.get("product_type") == "Dual Cartridge" else prod.get("packaging", [])):
            hit = next((o for o in opts if o.lower() == pk.lower()
                        or o.lower().replace(" ", "") == pk.lower().replace(" ", "")), None)
            if hit:
                ss["product_type"] = hit
                break
    # SDS
    ss.sds_data = None
    ss.master_notice = []
    choice = ss.get("_master_sds_map", {}).get(ss.get("master_sds_label"))
    _pc = master_data.part_choices(master_data.sds_choices(code)) if (cat != "Tape") else {}
    combine = bool(_pc) and ss.get("product_type") == "Dual Cartridge"
    needs = REQUIRES_SDS.get(cat or ss.get("category", "Adhesive"), True)
    if needs and combine:
        a = master_data.sds_data_for(_pc["A"]["file_name"])
        b = master_data.sds_data_for(_pc["B"]["file_name"])
        data = master_data.combine_sds(a, b) if a and b else None
        ss.sds_data = data
        if data:
            ss.master_notice.append(f"Part A and Part B SDSs combined; {data['_combined_removed']} duplicate statements removed. "
                                    "Review the statements and ingredients below.")
            if data.get("_master_flags"):
                ss.master_notice.append(f"The master flags: {data['_master_flags']}. Anything missing will be blank on the label.")
    elif needs and choice:
        data = master_data.sds_data_for(choice)
        ss.sds_data = data
        if data and data.get("_master_flags"):
            ss.master_notice.append(f"The master flags this SDS: {data['_master_flags']}. Anything missing will be blank on the label.")
    elif needs:
        up = ss.get("sds_upload_fallback")
        if up is not None:
            path = _save_upload_to_tmp(up)
            ss.sds_data = parse_sds(path)
            os.unlink(path)
            ss.master_notice.append("This product has no SDS in the master, so the uploaded SDS PDF was parsed instead.")
        else:
            ss.master_notice.append("This product has no SDS in the master. Upload one below and load again, or switch to Upload PDFs.")
    if not tds["bullets"]:
        ss.master_notice.append("The master has no Application Instructions for this product, so there are no Directions for Use bullets.")
    ss.master_loaded = code
    ss.rendered_label = None
    # Prefill AP #, revision, color and bar text from an existing label for this product
    try:
        _rows_ = _candidate_labels(code, ss.get("product_type"), ss.get("category"))
        # Only auto-fill when exactly one label matches; with several (e.g. one per
        # color) the user picks from the list so the wrong AP # is never assumed.
        if len(_rows_) == 1:
            _apply_label_row(_rows_[0])
            ss["existing_label_choice"] = _label_option(_rows_[0])
        else:
            ss["existing_label_choice"] = "(none -- fill in manually)"
    except Exception:
        pass


left, right = st.columns([1, 1.3])

with left:
    st.subheader("1. Product Basics")
    CATEGORY_DISPLAY_LABELS = {"Adhesive": "Bond", "Sealant": "Seal", "Tape": "Tape"}
    category = st.selectbox("Category", CATEGORIES, format_func=lambda c: CATEGORY_DISPLAY_LABELS.get(c, c), key="category")

    is_tape = category == "Tape"

    available_products = [
        p for p in PRODUCT_SIZES
        if category in available_categories_for_product(p) and PRODUCT_SIZES[p]["item_label"]
    ] if not is_tape else []
    product_type = st.selectbox(
        "Product Type / Packaging", available_products if available_products else ["N/A -- Tape is one size"],
        disabled=is_tape, key="product_type",
        help="Tape only ever uses one label size regardless of the tape's own physical dimensions, so this is disabled." if is_tape else None,
    )

    if is_tape:
        # Tape's label canvas is fixed at 8x4in regardless of the tape
        # product's own physical width/length -- confirmed across all 5
        # real reference labels measured (Industrial, Marine,
        # Construction, Insulation, Transportation all use this same
        # size). The tape's actual dimensions are entered separately
        # below as free text, since they vary per product and don't
        # match the Cartridge/Sausage/Pail-style dropdown at all.
        canvas_size_in = (8, 4)
        dimension_group = None
        use_compact_layout = False
        tape_size_label = st.text_input("Tape Size", placeholder="e.g. 3/4in x 108ft", key="tape_size_text")
    else:
        canvas_size_in = get_label_dimensions(product_type)
        # Aerosol/22L/108L Canister use a structurally different
        # three-column layout (render_compact_label) from everything
        # else (render_label, two-column) -- this determines which form
        # fields to show below and which render function actually gets
        # called.
        dimension_group = dimension_group_for_product(product_type)
        use_compact_layout = is_compact_layout(dimension_group)

    if product_type != "Dual Cartridge":
        st.caption(f"Label size: {canvas_size_in[0]}\" x {canvas_size_in[1]}\"")

    # Dual (two-part) cartridges share one 6x4 label for product and box; the
    # size printed on it varies per product, so it is typed (or loaded from the master).
    size_label_text = product_type
    dual_filename_size = None
    dual_size_value = None
    if not is_tape and product_type == "Dual Cartridge":
        _choice = st.selectbox("Cartridge size", DUAL_SIZES + [DUAL_SIZE_OTHER], key="dual_size_choice")
        if _choice == DUAL_SIZE_OTHER:
            _choice = st.text_input("Size (e.g. 200ml)", key="dual_size_other").strip()
        _size = _choice or "400ml"
        size_label_text = f"SIZE: {_size}"   # footer reads "SIZE: 400ml"
        dual_filename_size = f"AB_{_size}"
        dual_size_value = _size

    vertical_name = st.selectbox("Vertical Market", list(VERTICAL_BACKGROUNDS.keys()), key="vertical_name")
    badge_icon_path = BADGE_ICONS.get(vertical_name, DEFAULT_BADGE_ICON)

    if not is_tape and not has_template(category, vertical_name, product_type):
        st.warning(
            f"No real label template exists yet for {category} + {vertical_name}. "
            f"This combination may not reflect an actual Forza product -- the preview "
            f"below will use a generic fallback layout that looks visually different "
            f"(different positioning, no baked-in art) from the real templates."
        )

    case_quantity = None
    if is_tape:
        # Every tape product ships as what the other categories call a
        # "Box Label" -- confirmed across all 5 real references, all of
        # which show Case Quantity in the footer unconditionally. No
        # toggle needed; always collected. Case quantity genuinely
        # varies per tape product (no fixed chart value yet), so this
        # stays manual entry until that data exists.
        qty_value = st.text_input("Case Quantity (value)", placeholder="e.g. 12")
        if qty_value:
            case_quantity = qty_value
    else:
        # Box Label branch -- relevant for any product type with a real
        # box_quantity defined in product_sizes.py, not just Cartridge/
        # Sausage by name -- that substring check silently missed Gallon
        # Can and Aerosol Can, which also ship as box labels. Correct
        # verbiage confirmed: "Case Quantity:" for Cartridges, "QTY:" for
        # everything else -- these are genuinely different labels, not
        # just a generic "quantity" field, so the prefix is picked per
        # product type and baked into the value passed to the renderer.
        is_cartridge = "Cartridge" in product_type
        has_box_variant = PRODUCT_SIZES[product_type].get("box_quantity") is not None
        if has_box_variant:
            box_label = st.radio("Box Label?", ["No", "Yes"], horizontal=True, key="box_label_radio")
            if box_label == "Yes":
                qty_prefix = "Case Quantity:" if is_cartridge else "QTY:"
                # Every other category's case quantity is the fixed,
                # known value from the original size chart -- already
                # stored as box_quantity in product_sizes.py, so there's
                # nothing for the user to type; just confirm what it is.
                fixed_qty = PRODUCT_SIZES[product_type]["box_quantity"]
                if fixed_qty == "manual":
                    typed_qty = st.text_input("Case Quantity (value)", placeholder="e.g. 6", key="case_qty_manual")
                    if typed_qty:
                        case_quantity = f"{qty_prefix} {typed_qty}"
                    else:
                        st.warning("Enter the case quantity for this box label.")
                else:
                    case_quantity = f"{qty_prefix} {fixed_qty}"
                    st.caption(f"{qty_prefix} {fixed_qty} (fixed per size chart)")

    # Dual cartridge item labels come in two sizes: 6x4 (default) or the small
    # two-column 4x2. Box labels are always 6x4.
    use_small_layout = False
    if not is_tape and product_type == "Dual Cartridge":
        if case_quantity or st.session_state.get("box_label_radio", "No") == "Yes":
            st.caption("Label size: 6\" x 4\" (box labels are always 6x4)")
        else:
            _item_size = st.radio("Item label size", ["6x4", "4x2"], horizontal=True, key="dual_item_size",
                                  help="4x2 is the small two-column label: signal word and hazard statements on the left, "
                                       "directions and a short storage/disposal line on the right (no precautionary statements).")
            if _item_size == "4x2":
                use_small_layout = True
                canvas_size_in = SMALL_DIMENSION
                dimension_group = "4x2"
                use_compact_layout = False
            st.caption(f"Label size: {canvas_size_in[0]}\" x {canvas_size_in[1]}\"")

    st.subheader("2. Source Documents")
    needs_sds = REQUIRES_SDS.get(category, True)
    source_mode = st.radio(
        "Where should the label content come from?",
        ["Master data (recommended)", "Upload PDFs"],
        horizontal=True, key="source_mode",
        help="Master data uses the approved Product Source of Truth. Upload PDFs parses an SDS and TDS "
             "you provide, for products that are not in the master yet.",
    )
    use_master = source_mode.startswith("Master")
    sds_file = None
    tds_file = None
    if use_master:
        try:
            _plist = master_data.product_list()
        except Exception as _e:
            _plist = None
            st.error(f"Could not read the master data ({type(_e).__name__}). Check the GITHUB_TOKEN secret, "
                     "or switch to Upload PDFs.")
        if _plist:
            st.session_state["_master_products"] = {p["code"]: p for p in _plist}
            st.selectbox("Product Code", [f"{p['code']} -- {p['title']}" for p in _plist], key="master_code_label")
            _code = (st.session_state.get("master_code_label") or "").split(" -- ")[0]
            _choices = master_data.sds_choices(_code) if (_code and needs_sds) else []
            st.session_state["_master_sds_map"] = {c["label"]: c["file_name"] for c in _choices}
            _parts = master_data.part_choices(_choices) if needs_sds else {}
            if _parts and product_type == "Dual Cartridge":
                st.session_state["_master_sds_map"][master_data.COMBINED_LABEL] = "combined"
                st.session_state["master_sds_label"] = master_data.COMBINED_LABEL
                st.caption("Dual cartridge: the Part A and Part B SDSs will be combined into one label.")
            elif needs_sds and len(_choices) > 1:
                st.selectbox("This product has more than one SDS. Which one is for this label?",
                             [c["label"] for c in _choices], key="master_sds_label")
            elif needs_sds and len(_choices) == 1:
                st.session_state["master_sds_label"] = _choices[0]["label"]
                st.caption(f"SDS: {_choices[0]['label']}")
            else:
                st.session_state["master_sds_label"] = None
                if needs_sds:
                    st.warning("No SDS for this product in the master. Upload one to use for this label.")
                    st.file_uploader("SDS (PDF)", type="pdf", key="sds_upload_fallback")
                else:
                    st.caption("Tape products don't require an SDS -- hazard/pictogram content will be skipped.")
            st.button("Load from master", type="secondary", use_container_width=True, on_click=_load_from_master,
                      help="Fills Product Basics and Label Text from the master. You can still edit every field.")
            if st.session_state.get("master_loaded") == _code:
                st.success(f"Loaded {st.session_state.master_loaded} from the master. Review the content below before generating.")
            for _n in st.session_state.get("master_notice", []):
                st.warning(_n)
    else:
        if needs_sds:
            sds_file = st.file_uploader("SDS (PDF)", type="pdf", key="sds_upload")
        else:
            st.caption("Tape products don't require an SDS -- hazard/pictogram content will be skipped.")
        tds_file = st.file_uploader("TDS (PDF)", type="pdf", key="tds_upload")

    if (not use_master) and st.button("Parse Documents", type="secondary", use_container_width=True):
        if needs_sds and sds_file is None:
            st.error("This category requires an SDS.")
        elif tds_file is None:
            st.error("A TDS is required.")
        else:
            with st.spinner("Parsing..."):
                if sds_file is not None:
                    sds_path = _save_upload_to_tmp(sds_file)
                    st.session_state.sds_data = parse_sds(sds_path)
                    os.unlink(sds_path)
                else:
                    st.session_state.sds_data = None

                tds_path = _save_upload_to_tmp(tds_file)
                st.session_state.tds_bullets = extract_product_application_bullets(tds_path)
                # Tape has no SDS to pull Storage from -- the TDS is the
                # only source for it, so parse this for Tape specifically.
                st.session_state.tds_storage_info = extract_storage_info(tds_path) if is_tape else None
                os.unlink(tds_path)
            st.success("Parsed. Review the extracted content below before generating.")

    if st.session_state.sds_data is not None:
        with st.expander("Extracted SDS data", expanded=False):
            st.write("**Signal word:**", st.session_state.sds_data.get("signal_word"))
            st.write("**Pictograms:**", st.session_state.sds_data.get("pictograms"))
            st.write("**Hazard statements:**")
            for h in st.session_state.sds_data.get("hazard_statements", []):
                st.write(f"- {h['text']}")
            st.write("**Precautionary statements:**")
            for p in st.session_state.sds_data.get("precautionary_statements", []):
                st.write(f"- {p['text']}")
            st.write("**Storage:**", st.session_state.sds_data.get("storage"))
            st.write("**Disposal:**", st.session_state.sds_data.get("disposal"))

    if st.session_state.sds_data is not None:
        force_exclude_response = st.checkbox(
            "Exclude Response precautionary statements (P3xx -- \"IF IN EYES\", \"IF INHALED\", etc.) "
            "to allow larger text",
            value=False,
            help="By default, these are only dropped automatically as a last resort if the box "
                 "genuinely doesn't fit otherwise. Check this to exclude them proactively instead, "
                 "even when everything technically fits by shrinking. Storage/Disposal precautionary "
                 "statements (P4xx/P5xx) are always excluded already, since that content is shown "
                 "separately in the Storage/Waste Disposal sections.",
        )
    else:
        force_exclude_response = False

    if st.session_state.tds_bullets:
        st.markdown("**Directions for Use** (from the TDS Application Instructions -- uncheck any to exclude)")
        selected_bullets = []
        for i, bullet in enumerate(st.session_state.tds_bullets):
            if st.checkbox(bullet, value=True, key=f"bullet_{i}"):
                selected_bullets.append(bullet)
    else:
        selected_bullets = []

    # Ingredient selection only matters for the compact layout (22L/108L
    # Canister, Aerosol Can) -- that's the only layout with a CONTAINS
    # section that actually displays ingredients. Showing this checklist
    # for other product types was misleading, since toggling ingredients
    # there had no visible effect on the generated label at all.
    all_ingredients = (
        (st.session_state.sds_data or {}).get("ingredients") or []
        if st.session_state.sds_data and use_compact_layout else []
    )
    if all_ingredients:
        st.markdown("**Ingredients to List** (only hazardous ingredients are listed; non-hazardous catch-all lines and dyes start unchecked)")
        selected_ingredients = []
        for i, ing in enumerate(all_ingredients):
            _nh = master_data.is_non_hazardous(ing.get("chemical_name"))
            label = f"{ing['chemical_name']} (CAS #: {ing['cas_number']})" + ("  -- non-hazardous / dye, not listed by default" if _nh else "")
            if st.checkbox(label, value=not _nh, key=f"ingredient_{i}"):
                selected_ingredients.append(ing)
    else:
        selected_ingredients = []

    st.subheader("3. Label Text")
    if use_master:
        try:
            _ex = _candidate_labels(st.session_state.get("product_code") or "", product_type, category)
        except Exception:
            _ex = []
        if _ex:
            st.session_state["_existing_label_map"] = {_label_option(r): r for r in _ex}
            st.selectbox("Start from an existing label", ["(none -- fill in manually)"] + list(st.session_state["_existing_label_map"]),
                         key="existing_label_choice", on_change=_apply_existing_choice,
                         help="Fills the AP #, revision, color and orange-bar text from a label already in the master, "
                              "so you can edit it or bump the revision.")
            st.caption("Prefilled from the master. Change the revision (N#) for a new revision of this label.")
    ap_col, rev_col = st.columns([2, 1])
    with ap_col:
        ap_number = st.text_input("Internal Label Number (AP + digits, not always 4)", placeholder="e.g. AP2451", key="ap_number")
    with rev_col:
        revision_number = st.text_input("Revision (N#)", placeholder="e.g. 1", key="revision_number")
    if ap_number and revision_number:
        internal_label_number = f"{ap_number} N{revision_number}"
    elif ap_number:
        internal_label_number = ap_number
    else:
        internal_label_number = None
    product_code = st.text_input("Product Code", placeholder="e.g. R-OS86", key="product_code")
    if is_tape:
        badge_color = None
    else:
        has_color = st.radio("Does this product have a color?", ["No", "Yes"], horizontal=True, key="has_color")
        badge_color = st.text_input("Color", placeholder="e.g. WHITE", key="label_color").upper() if has_color == "Yes" else None
    _lock_name = bool(use_master and st.session_state.get("_name_from_master") and st.session_state.get("product_name"))
    product_name = st.text_input("Product Name/Type (below the badge box)", placeholder="e.g. Acetoxy Silicone", key="product_name",
                                 disabled=_lock_name,
                                 help="Locked to the master product name so every document matches. Change it in the master (TDS) to change it here." if _lock_name else None)
    if use_compact_layout:
        sales_description = st.text_input("Sales Description (orange bar)", key="sales_description")
    else:
        sales_description_1 = st.text_input("Sales Description #1 (left orange bar)", key="sales_description_1")
        sales_description_2 = st.text_input("Sales Description #2 (right orange bar)", key="sales_description_2")
    lot_number = "LOT#"  # not user-fillable -- always displays as the literal placeholder

    generate = st.button("Generate Label", type="primary", use_container_width=True)

with right:
    st.subheader("Preview")
    if generate:
        if not product_code or not product_name:
            st.error("Product Code and Product Name are required.")
        else:
            with st.spinner("Rendering label..."):
                background_path = VERTICAL_BACKGROUNDS[vertical_name]
                # Relative to this script's own location, not a hardcoded
                # sandbox-specific path -- works on any machine this app
                # is actually run on.
                _output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_labels")
                output_path = os.path.join(_output_dir, "generated_label.png")
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                # A box label (when checked above) can mean a genuinely
                # different background image, not just extra text on the
                # item_label one -- Aerosol Can's box/case label is a
                # visually different layout. Check that first; everything
                # else that has a box variant (Cartridge/Sausage/Gallon
                # Can) just adds the case_quantity line to the same
                # item_label background instead.
                # Apply the user's ingredient selection -- not all parsed
                # ingredients are required on the label, so this can be a
                # subset of what the SDS actually listed.
                effective_sds_data = st.session_state.sds_data
                if effective_sds_data is not None:
                    effective_sds_data = dict(effective_sds_data)
                    effective_sds_data["ingredients"] = selected_ingredients

                if is_tape:
                    baked_background_path = TAPE_BACKGROUNDS.get(vertical_name)
                else:
                    baked_background_path = None
                    if case_quantity:
                        baked_background_path = get_box_label_template(category, vertical_name, product_type)
                    if baked_background_path is None:
                        try:
                            baked_background_path = get_template(category, vertical_name, product_type)
                        except (KeyError, ValueError):
                            # No baked background registered yet for this
                            # category/vertical/dimension combo -- both render
                            # functions fall back to drawing from scratch via
                            # background_path when baked_background_path is None,
                            # so this is a graceful degrade, not an error.
                            baked_background_path = None

                if is_tape:
                    _, dropped_content = render_tape_label(
                        canvas_size_in=canvas_size_in,
                        background_path=background_path,
                        baked_background_path=baked_background_path,
                        vertical_name=vertical_name,
                        sds_data=effective_sds_data,
                        tds_bullets_selected=selected_bullets,
                        product_name=product_name,
                        sales_description_1=sales_description_1,
                        sales_description_2=sales_description_2,
                        product_code=product_code,
                        size_label=tape_size_label,
                        case_quantity=case_quantity or "",
                        internal_label_number=internal_label_number or None,
                        lot_number=lot_number,
                        tds_storage_info=st.session_state.tds_storage_info,
                        output_path=output_path,
                        dpi=300,
                        force_exclude_response=force_exclude_response,
                    )
                elif use_small_layout:
                    _, dropped_content = render_small_label(
                        canvas_size_in=canvas_size_in,
                        background_path=background_path,
                        vertical_name=vertical_name,
                        category=category,
                        sds_data=effective_sds_data,
                        tds_bullets_selected=selected_bullets,
                        product_name=product_name,
                        sales_description_1=sales_description_1,
                        sales_description_2=sales_description_2,
                        product_code=product_code,
                        size_label=size_label_text,
                        badge_color=badge_color or None,
                        badge_icon_path=badge_icon_path,
                        internal_label_number=internal_label_number or None,
                        lot_number=lot_number,
                        output_path=output_path,
                        dpi=300,
                    )
                elif use_compact_layout:
                    _, dropped_content = render_compact_label(
                        canvas_size_in=canvas_size_in,
                        background_path=background_path,
                        baked_background_path=baked_background_path,
                        dimension_group=dimension_group,
                        vertical_name=vertical_name,
                        category=category,
                        sds_data=effective_sds_data,
                        tds_bullets_selected=selected_bullets,
                        product_name=product_name,
                        sales_description=sales_description,
                        product_code=product_code,
                        size_label=size_label_text,
                        badge_color=badge_color or None,
                        badge_icon_path=badge_icon_path,
                        internal_label_number=internal_label_number or None,
                        case_quantity=case_quantity or None,
                        lot_number=lot_number,
                        output_path=output_path,
                        dpi=300,
                        force_exclude_response=force_exclude_response,
                    )
                else:
                    _, dropped_content = render_label(
                        canvas_size_in=canvas_size_in,
                        background_path=background_path,
                        baked_background_path=baked_background_path,
                        dimension_group=dimension_group,
                        vertical_name=vertical_name,
                        category=category,
                        sds_data=effective_sds_data,
                        tds_bullets_selected=selected_bullets,
                        product_name=product_name,
                        sales_description_1=sales_description_1,
                        sales_description_2=sales_description_2,
                        product_code=product_code,
                        size_label=size_label_text,
                        badge_color=badge_color or None,
                        badge_icon_path=badge_icon_path,
                        internal_label_number=internal_label_number or None,
                        case_quantity=case_quantity or None,
                        lot_number=lot_number,
                        output_path=output_path,
                        dpi=300,
                        force_exclude_response=force_exclude_response,
                    )
                st.session_state.rendered_label = output_path
                st.session_state.dropped_content = dropped_content

    if st.session_state.rendered_label and os.path.exists(st.session_state.rendered_label):
        img = Image.open(st.session_state.rendered_label)
        st.image(img, use_container_width=True)

        dropped = st.session_state.dropped_content or {}
        any_dropped = any(dropped.get(side) for side in ("left", "right"))
        if any_dropped:
            st.warning("Some content didn't fit and was trimmed from the label. Review what was cut below.")
            with st.expander("Review trimmed content", expanded=True):
                for side, label in [("left", "Left box"), ("right", "Right box")]:
                    items = dropped.get(side) or []
                    if items:
                        st.write(f"**{label}:**")
                        for item in items:
                            st.write(f"- {item}")
        pdf_buffer = io.BytesIO()
        img.convert("RGB").save(pdf_buffer, format="PDF", resolution=300.0)

        pdf_filename = build_label_filename(
            ap_number, revision_number, product_code,
            (dual_filename_size or size_label_text) if not is_tape else "",
            canvas_size_in, is_tape=is_tape,
            tape_size_label=tape_size_label if is_tape else "",
            is_box=bool(case_quantity),
        )
        # Set the PDF's internal Title metadata to match the filename
        # (minus the .pdf extension) -- most PDF viewers display this
        # title in place of the filename once the file is opened, so
        # this keeps the two consistent rather than just the download
        # name being right.
        pdf_doc = fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf")
        pdf_doc.set_metadata({"title": pdf_filename[:-4]})
        final_pdf_buffer = io.BytesIO()
        pdf_doc.save(final_pdf_buffer)
        pdf_doc.close()

        st.download_button(
            "Download Label (PDF)",
            data=final_pdf_buffer.getvalue(),
            file_name=pdf_filename,
            mime="application/pdf",
            use_container_width=True,
        )

        # ---- Save this label's details to the master Labels tab (as a DRAFT) ----
        # Only Mike approves drafts, so this never changes approved data. It is a
        # button (not automatic) so test/dummy labels are not saved by accident.
        # Single-bar layouts (aerosol, canisters) store their one bar in "Left Bar Text".
        st.markdown("---")
        if st.button("Save label details to master (draft)", use_container_width=True,
                     help="Saves AP #, revision, size, color and the orange-bar text to the Labels tab as a pending draft for approval."):
            try:
                import master_repo
                if use_compact_layout:
                    _bar_l, _bar_r = (sales_description or "").strip(), ""
                else:
                    _bar_l, _bar_r = (sales_description_1 or "").strip(), (sales_description_2 or "").strip()
                _size_container = (f"{dual_size_value} Dual Cartridge" if dual_size_value else product_type)
                if use_small_layout:
                    _size_container += " (4x2)"
                _ptype, _sds_no = "", ""
                try:
                    _t = next((r for r in master_data._rows("tds") if (r.get("Product Code") or "").strip() == product_code), {})
                    _ptype = (_t.get("Product Type") or "").strip()
                    _files = [f.strip() for f in (st.session_state.get("sds_data") or {}).get("_master_file", "").split("+") if f.strip()]
                    _by_file = {(r.get("File Name") or "").strip(): (r.get("SDS #") or "").strip() for r in master_data._rows("sds")}
                    _sds_no = " + ".join(x for x in (_by_file.get(f, "") for f in _files) if x)
                except Exception:
                    pass
                _row = {
                    "Product Code": product_code,
                    "Product Type (from TDS)": _ptype,
                    "AP #": ap_number or "",
                    "Revision": (f"N{revision_number}" if revision_number else ""),
                    "Size / Container": _size_container,
                    "Color": badge_color or "",
                    "Label Type": "Box" if case_quantity else "Item",
                    "Label Product Name": product_name or "",
                    "Left Bar Text": _bar_l,
                    "Right Bar Text": _bar_r,
                    "SDS # (link to SDS tab)": _sds_no,
                    "Notes": f"Source {pdf_filename}",
                }
                _res = master_repo.save_draft("labels", _row, who="Label Builder")
                master_data.refresh()
                st.success(f"Saved to the Labels tab as a draft ({_res}). It will show once approved.")
            except Exception as e:
                st.error(f"Could not save to the master: {e}")
    else:
        st.info("Fill in the form and click **Generate Label** to see a preview here.")
