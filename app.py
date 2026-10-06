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

from parse_sds import parse_sds
from parse_tds import extract_product_application_bullets, extract_storage_info
from label_renderer import render_label, render_compact_label, render_tape_label
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
                          canvas_size_in, is_tape=False, tape_size_label=""):
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
    parts = [ap_and_code, size_type_part, label_size, "PDFSize"]
    name = "_".join(_sanitize_filename_part(p) for p in parts if p)
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

left, right = st.columns([1, 1.3])

with left:
    st.subheader("1. Product Basics")
    CATEGORY_DISPLAY_LABELS = {"Adhesive": "Bond", "Sealant": "Seal", "Tape": "Tape"}
    category = st.selectbox("Category", CATEGORIES, format_func=lambda c: CATEGORY_DISPLAY_LABELS.get(c, c))

    is_tape = category == "Tape"

    available_products = [
        p for p in PRODUCT_SIZES
        if category in available_categories_for_product(p) and PRODUCT_SIZES[p]["item_label"]
    ] if not is_tape else []
    product_type = st.selectbox(
        "Product Type / Packaging", available_products if available_products else ["N/A -- Tape is one size"],
        disabled=is_tape,
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
        tape_size_label = st.text_input("Tape Size", placeholder="e.g. 3/4in x 108ft")
    else:
        canvas_size_in = get_label_dimensions(product_type)
        # Aerosol/22L/108L Canister use a structurally different
        # three-column layout (render_compact_label) from everything
        # else (render_label, two-column) -- this determines which form
        # fields to show below and which render function actually gets
        # called.
        dimension_group = dimension_group_for_product(product_type)
        use_compact_layout = is_compact_layout(dimension_group)

    st.caption(f"Label size: {canvas_size_in[0]}\" x {canvas_size_in[1]}\"")

    vertical_name = st.selectbox("Vertical Market", list(VERTICAL_BACKGROUNDS.keys()))
    badge_icon_path = BADGE_ICONS.get(vertical_name, DEFAULT_BADGE_ICON)

    if not is_tape and not has_template(category, vertical_name, product_type):
        st.warning(
            f"No real label template exists yet for {category} + {vertical_name}. "
            f"This combination may not reflect an actual Forza product -- the preview "
            f"below will use a generic fallback layout that looks visually different "
            f"(different positioning, no baked-in art) from the real templates."
        )

    st.subheader("2. Source Documents")
    needs_sds = REQUIRES_SDS.get(category, True)
    sds_file = None
    if needs_sds:
        sds_file = st.file_uploader("SDS (PDF)", type="pdf", key="sds_upload")
    else:
        st.caption("Tape products don't require an SDS -- hazard/pictogram content will be skipped.")
    tds_file = st.file_uploader("TDS (PDF)", type="pdf", key="tds_upload")

    if st.button("Parse Documents", type="secondary", use_container_width=True):
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
        st.markdown("**Application Instructions** (uncheck any to exclude)")
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
        st.markdown("**Ingredients to List** (uncheck any not required on this label)")
        selected_ingredients = []
        for i, ing in enumerate(all_ingredients):
            label = f"{ing['chemical_name']} (CAS #: {ing['cas_number']})"
            if st.checkbox(label, value=True, key=f"ingredient_{i}"):
                selected_ingredients.append(ing)
    else:
        selected_ingredients = []

    case_quantity = None
    if is_tape:
        # Every tape product ships as what the other categories call a
        # "Box Label" -- confirmed across all 5 real references, all of
        # which show Case Quantity in the footer unconditionally. No
        # toggle needed; always collected. Case quantity genuinely
        # varies per tape product (no fixed chart value yet), so this
        # stays manual entry until that data exists.
        st.subheader("2b. Case Quantity")
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
            st.subheader("2b. Box Label")
            box_label = st.radio("Box Label?", ["No", "Yes"], horizontal=True)
            if box_label == "Yes":
                qty_prefix = "Case Quantity:" if is_cartridge else "QTY:"
                # Every other category's case quantity is the fixed,
                # known value from the original size chart -- already
                # stored as box_quantity in product_sizes.py, so there's
                # nothing for the user to type; just confirm what it is.
                fixed_qty = PRODUCT_SIZES[product_type]["box_quantity"]
                case_quantity = f"{qty_prefix} {fixed_qty}"
                st.caption(f"{qty_prefix} {fixed_qty} (fixed per size chart)")

    st.subheader("3. Label Text")
    ap_col, rev_col = st.columns([2, 1])
    with ap_col:
        ap_number = st.text_input("Internal Label Number (AP + digits, not always 4)", placeholder="e.g. AP2451")
    with rev_col:
        revision_number = st.text_input("Revision (N#)", placeholder="e.g. 1")
    if ap_number and revision_number:
        internal_label_number = f"{ap_number} N{revision_number}"
    elif ap_number:
        internal_label_number = ap_number
    else:
        internal_label_number = None
    product_code = st.text_input("Product Code", placeholder="e.g. R-OS86")
    if is_tape:
        badge_color = None
    else:
        has_color = st.radio("Does this product have a color?", ["No", "Yes"], horizontal=True)
        badge_color = st.text_input("Color", placeholder="e.g. WHITE").upper() if has_color == "Yes" else None
    product_name = st.text_input("Product Name/Type (below the badge box)", placeholder="e.g. Acetoxy Silicone")
    if use_compact_layout:
        sales_description = st.text_input("Sales Description (orange bar)")
    else:
        sales_description_1 = st.text_input("Sales Description #1 (left orange bar)")
        sales_description_2 = st.text_input("Sales Description #2 (right orange bar)")
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
                        size_label=product_type,
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
                        size_label=product_type,
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
            product_type if not is_tape else "",
            canvas_size_in, is_tape=is_tape,
            tape_size_label=tape_size_label if is_tape else "",
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
    else:
        st.info("Fill in the form and click **Generate Label** to see a preview here.")
