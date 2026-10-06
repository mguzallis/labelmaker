"""
Label renderer.

Composites a finished label from:
  - a vertical's background art + logo (swappable per vertical)
  - parsed SDS data (signal word, hazard/precautionary statements,
    storage, disposal, pictograms) -- skipped entirely for Tape
  - selected TDS Application Instructions bullets (verbatim)
  - manual fields the app must prompt for: product name, sales
    descriptions, product code, size label, badge text

Uses the shared fractional layout from layout_config.py, so the same
function works for any dimension group / vertical -- only the background
image, logo, vertical name, and content differ.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import re
import textwrap

from layout_config import ZONES, zone_px, badge_zone_px, icon_zone_px, FONTS, COLOR_ORANGE, COLOR_NAVY, COLOR_GREY_BOX, COLOR_WHITE, COLOR_DARK_TEXT, VERTICAL_BADGE_TEXT_COLOR, DEFAULT_BADGE_TEXT_COLOR


def _font(weight, size):
    return ImageFont.truetype(FONTS[weight], size)


def _precaution_code_in_category(code, category_digit):
    """True if ANY part of this (possibly compound, e.g. "P342+P311")
    code is in the given GHS category (2=Prevention, 3=Response,
    4=Storage, 5=Disposal) -- filtered by code prefix rather than
    wording, since the same code gets phrased differently across SDS
    authors (confirmed repeatedly this session)."""
    parts = [p.strip() for p in code.split("+")]
    return any(re.match(rf"P{category_digit}\d{{2}}$", p) for p in parts)


def strip_redundant_precautions(precautionary_statements):
    """Unconditionally remove P4xx (Storage) and P5xx (Disposal) --
    this content is already shown elsewhere on the label (the right
    box's STORAGE and WASTE DISPOSAL sections, sourced directly from
    SDS Section 7/13 text, not from these P-codes), so including it here
    too would just be redundant duplication regardless of available
    space. P2xx (Prevention) and P3xx (Response) are left untouched by
    this function -- P2xx is never filtered at all, and P3xx is only
    ever filtered conditionally (see split_response_precautions)."""
    return [
        p for p in precautionary_statements
        if not (_precaution_code_in_category(p["code"], 4) or _precaution_code_in_category(p["code"], 5))
    ]


def split_response_precautions(precautionary_statements):
    """Split into (non_response, response) -- response is P3xx. This is
    a CONDITIONAL space-saving fallback: callers try fitting with the
    full (non-P4xx/P5xx) list first, and only use the non_response subset
    if that doesn't fit even after tightening. Never applied unprompted
    when content already fits fine as full prevention+response."""
    non_response, response = [], []
    for p in precautionary_statements:
        (response if _precaution_code_in_category(p["code"], 3) else non_response).append(p)
    return non_response, response


def _measure_wrapped_lines(text, font, max_width):
    """Return the wrapped lines for text at this font/width, without
    drawing. Measures each candidate line's ACTUAL rendered pixel width
    (greedily adding words until the next one would overflow), rather
    than estimating from an average character width -- SDS text's heavy
    use of uppercase letters, numbers, and punctuation (CAS numbers,
    chemical names) is typically wider than the lowercase-letter average
    a character-count estimate would calibrate against, which caused
    systematic premature wrapping (breaking a line with room left for
    another word or two)."""
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.getlength(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped_text(draw, xy, text, font, fill, max_width, line_spacing=1.3):
    """Draw text wrapped to max_width (px). Returns the y-coordinate after
    the last line drawn."""
    x, y = xy
    line_height = int(font.size * line_spacing)
    for line in _measure_wrapped_lines(text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _measure_ingredient_list_height(ingredients, name_font, cas_font, max_width, line_spacing=1.3, item_gap=0.3):
    """Companion to _draw_ingredient_list -- same column-alignment logic,
    but measuring only (no drawing), for use in fit-to-box sizing passes.
    Returns (total_height, cas_column_x_offset)."""
    if not ingredients:
        return 0, 0
    cas_strings = [f"CAS #: {ing['cas_number']}" for ing in ingredients]
    name_strings = [ing["chemical_name"] for ing in ingredients]
    gap = int(name_font.size * 0.8)
    # Column starts right after the widest name that still leaves room
    # for its CAS number on the same line -- a single very long name
    # shouldn't drag the whole column out past what's usable, so this
    # caps the column start at 65% of max_width and lets only that one
    # name wrap its CAS onto the next line instead.
    max_name_w = max(name_font.getlength(n) for n in name_strings)
    cas_col_x = min(max_name_w + gap, max_width * 0.65)
    total_h = 0
    for name, cas in zip(name_strings, cas_strings):
        name_w = name_font.getlength(name)
        if name_w <= cas_col_x - gap:
            # Name fits within the column -- name and CAS share one line.
            total_h += int(name_font.size * line_spacing)
        else:
            # Name itself is wider than the column -- wraps onto its own
            # line(s), CAS number goes on the line after.
            wrap_w = max(int(cas_col_x * 2 / (name_font.size * 0.55)), 8)
            name_lines = textwrap.wrap(name, width=wrap_w) or [name]
            total_h += len(name_lines) * int(name_font.size * line_spacing)
            total_h += int(cas_font.size * line_spacing)
        total_h += int(name_font.size * item_gap)
    return total_h, cas_col_x


def _draw_ingredient_list(draw, xy, ingredients, name_font, cas_font, name_fill, cas_fill, max_width,
                           line_spacing=1.3, item_gap=0.3):
    """Draw a chemical_name / CAS # ingredient list with CAS numbers
    aligned in a fixed column, rather than each one simply following its
    own name at whatever width that name happens to be (which reads as
    ragged, not as a table). Returns the y-coordinate after the last
    line drawn."""
    x, y = xy
    if not ingredients:
        return y
    total_h, cas_col_x = _measure_ingredient_list_height(ingredients, name_font, cas_font, max_width, line_spacing, item_gap)
    gap = int(name_font.size * 0.8)
    for ing in ingredients:
        name = ing["chemical_name"]
        cas_text = f"CAS #: {ing['cas_number']}"
        name_w = name_font.getlength(name)
        if name_w <= cas_col_x - gap:
            draw.text((x, y), name, font=name_font, fill=name_fill)
            draw.text((x + cas_col_x, y), cas_text, font=cas_font, fill=cas_fill)
            y += int(name_font.size * line_spacing)
        else:
            wrap_w = max(int(cas_col_x * 2 / (name_font.size * 0.55)), 8)
            name_lines = textwrap.wrap(name, width=wrap_w) or [name]
            for line in name_lines:
                draw.text((x, y), line, font=name_font, fill=name_fill)
                y += int(name_font.size * line_spacing)
            draw.text((x, y), cas_text, font=cas_font, fill=cas_fill)
            y += int(cas_font.size * line_spacing)
        y += int(name_font.size * item_gap)
    return y


def _draw_bulleted_list(draw, xy, items, font, fill, max_width, line_spacing=1.3, bullet="•  ", bullet_gap=0.3):
    """Draw a bulleted list with a hanging indent: wrapped continuation
    lines align under the START OF THE TEXT, not under the bullet glyph,
    matching standard bullet-list typography."""
    x, y = xy
    bullet_width = font.getlength(bullet)
    for item in items:
        lines = _measure_wrapped_lines(item, font, max_width - bullet_width)
        line_height = int(font.size * line_spacing)
        for i, line in enumerate(lines):
            if i == 0:
                draw.text((x, y), f"{bullet}{line}", font=font, fill=fill)
            else:
                draw.text((x + bullet_width, y), line, font=font, fill=fill)
            y += line_height
        y += int(font.size * bullet_gap)  # gap between bullets
    return y


class Section:
    """One labeled block within a content box: a header line plus either
    a single wrapped paragraph or a bulleted list.

    `protected=True` marks content that must never be silently truncated
    once selected -- currently used for Application Instructions, since
    the checkbox selection step is a deliberate curation the person
    already did; the auto-fit engine truncating it further would undo
    that choice. When space runs short, non-protected sections give
    ground first (their content shrinks/truncates before a protected
    section ever does).
    """
    def __init__(self, header, content, kind="bulleted", bullet="•  ", protected=False, body_bold=False, body_color=None):
        self.header = header
        self.content = content  # str for "text", list[str] for "bulleted"
        self.kind = kind
        self.bullet = bullet
        self.protected = protected
        self.body_bold = body_bold  # render text-kind content in bold (same size as body)
        self.body_color = body_color  # override fill_body for just this section (e.g. the orange standing note)


def _measure_section_height(section, header_font, body_font, max_width, line_spacing=1.3, gap=0.6,
                              header_ratio=1.4, bullet_gap=0.3):
    if not section.content:
        return 0  # matches the draw step, which skips fully-emptied sections entirely
    h = int(header_font.size * header_ratio) if section.header else 0  # no header line -> no header space reserved
    effective_body_font = _font("bold", body_font.size) if (section.kind == "text" and section.body_bold) else body_font
    if section.kind == "text":
        lines = _measure_wrapped_lines(section.content, effective_body_font, max_width)
        h += len(lines) * int(body_font.size * line_spacing)
    else:
        bullet_width = body_font.getlength(section.bullet)
        for item in section.content:
            lines = _measure_wrapped_lines(item, body_font, max_width - bullet_width)
            h += len(lines) * int(body_font.size * line_spacing)
            h += int(body_font.size * bullet_gap)
    h += int(body_font.size * gap)
    return h


def _total_height(sections, header_font, body_font, max_width, line_spacing=1.3, gap=0.6,
                   header_ratio=1.4, bullet_gap=0.3):
    return sum(
        _measure_section_height(s, header_font, body_font, max_width,
                                 line_spacing=line_spacing, gap=gap,
                                 header_ratio=header_ratio, bullet_gap=bullet_gap)
        for s in sections
    )


def _pictogram_positions(n, size, base_gap, touch_offset, col_l_x, col_r_x, apex_x, bottom_top_y):
    """Module-level so both render_label and render_compact_label can use
    it -- originally nested inside render_label only."""
    if n <= 0:
        return []
    if n == 1:
        return [(apex_x - size / 2, bottom_top_y)]
    if n == 2:
        return [(col_l_x, bottom_top_y), (col_r_x, bottom_top_y)]
    if n == 3:
        return [(col_l_x, bottom_top_y), (col_r_x, bottom_top_y),
                 (apex_x - size / 2, bottom_top_y - touch_offset)]
    if n == 4:
        diamond_offset = size * 0.53
        bottom_center_y = bottom_top_y + size / 2
        wing_center_y = bottom_center_y - diamond_offset
        top_center_y = wing_center_y - diamond_offset
        bottom_pt = (apex_x - size / 2, bottom_top_y)
        left_wing = (apex_x - diamond_offset - size / 2, wing_center_y - size / 2)
        right_wing = (apex_x + diamond_offset - size / 2, wing_center_y - size / 2)
        top_pt = (apex_x - size / 2, top_center_y - size / 2)
        return [bottom_pt, left_wing, right_wing, top_pt]
    return [(col_l_x, bottom_top_y), (col_r_x, bottom_top_y),
             (apex_x - size / 2, bottom_top_y - touch_offset),
             (col_l_x, bottom_top_y - 2 * touch_offset),
             (col_r_x, bottom_top_y - 2 * touch_offset)]


_FULL_SPACING = dict(line_spacing=1.3, gap=0.6, header_ratio=1.4, bullet_gap=0.3)
_MIN_SPACING = dict(line_spacing=1.05, gap=0.25, header_ratio=1.15, bullet_gap=0.1)
_SPACING_STEPS = 8  # granularity of the tightening search between full and min


def _spacing_at(tightness):
    """tightness: 1.0 = full/default spacing, 0.0 = tightest allowed.
    Interpolates all four spacing knobs together on one dial, rather than
    searching each independently -- keeps the search space small while
    still giving real room to tighten before font size has to shrink."""
    return {
        k: _MIN_SPACING[k] + tightness * (_FULL_SPACING[k] - _MIN_SPACING[k])
        for k in _FULL_SPACING
    }


def fit_and_draw_box(draw, box_bounds, sections, base_header_size, base_body_size,
                       max_width, font_weight_header="bold", font_weight_body="regular",
                       min_scale=0.6, scale_step=0.05, fill_header=None, fill_body=None,
                       forced_scale=None, measure_only=False, header_ratio_boost=1.0, gap_boost=1.0):
    """Render a stack of Sections inside box_bounds. Per direct feedback,
    spacing tightens before font size shrinks -- at each candidate font
    scale (starting from 1.0), the full range of spacing tightness is
    tried before giving up on that scale and trying a smaller one. This
    keeps text as large as possible, trading away whitespace first.

    forced_scale: skip the font-scale search entirely and use exactly
    this scale (only the spacing-tightening search still runs). Used on
    a second pass once both boxes' independently-required scales are
    known, so both can be drawn at whichever one is smaller -- keeping
    the two boxes visually consistent instead of each independently
    maximizing its own fit.

    measure_only: compute and return the required (scale, spacing) with
    no drawing at all (draw may be None in this mode). Used for the first
    pass to find each box's own requirement before deciding the shared
    scale.

    If content still doesn't fit even at min_scale and the tightest
    spacing, trailing bullet items/sentences are dropped (starting from
    the last non-protected section) until it fits. No note is drawn on
    the label for this -- instead, the dropped content is returned so the
    caller can surface it (e.g. a review panel in the app) rather than
    printing a disclaimer on the label itself.
    """
    from layout_config import COLOR_ORANGE, COLOR_DARK_TEXT
    fill_header = fill_header or COLOR_ORANGE
    fill_body = fill_body or COLOR_DARK_TEXT

    x0, y0, x1, y1 = box_bounds
    pad = int(0.015 * (x1 - x0))
    # Drawing starts at y0+pad (see cursor_y below), so the true drawable
    # space is (y1-y0-pad), not the full (y1-y0) -- otherwise the last
    # element can be measured as fitting but then actually drawn past
    # the box's bottom edge by roughly the padding amount.
    available_h = (y1 - y0) - pad
    cursor_x = x0 + pad
    max_w = max_width

    # 1. Try each font scale (1.0 down to min_scale, or just forced_scale
    # if given); at each, try the full spacing-tightness range before
    # moving to a smaller scale.
    scales_to_try = [forced_scale] if forced_scale is not None else (
        [1.0 - i * scale_step for i in range(int((1.0 - min_scale) / scale_step) + 1)]
    )
    chosen_scale = None
    chosen_spacing = None
    for scale in scales_to_try:
        for step in range(_SPACING_STEPS + 1):
            tightness = 1.0 - step / _SPACING_STEPS
            spacing = _spacing_at(tightness)
            spacing["header_ratio"] *= header_ratio_boost
            spacing["gap"] *= gap_boost
            hf = _font(font_weight_header, max(int(base_header_size * scale), 1))
            bf = _font(font_weight_body, max(int(base_body_size * scale), 1))
            total = _total_height(sections, hf, bf, max_w, **spacing)
            if total <= available_h:
                chosen_scale = scale
                chosen_spacing = spacing
                break
        if chosen_scale is not None:
            break

    working_sections = sections
    truncated = False
    dropped_items = []  # exact text of whatever got cut, for the caller to surface
    needed_fallback = chosen_scale is None  # True if even min_scale+tightest spacing didn't fit

    if chosen_scale is None:
        # 2. Even at minimum scale and tightest spacing, it doesn't fit --
        # truncate content starting from the LAST non-protected section
        # backward. Protected sections (e.g. Application Instructions,
        # once the person has deliberately selected which bullets to
        # include) are skipped entirely here; other sections give ground
        # first regardless of kind -- bulleted sections lose trailing
        # items, and text-kind sections (Storage, Waste Disposal) lose
        # trailing SENTENCES one at a time, so a paragraph can be
        # shortened instead of only ever emptying whichever section
        # happens to be a bulleted list.
        chosen_scale = min_scale
        chosen_spacing = _MIN_SPACING
        hf = _font(font_weight_header, max(int(base_header_size * chosen_scale), 1))
        bf = _font(font_weight_body, max(int(base_body_size * chosen_scale), 1))

        working_sections = []
        for s in sections:
            new_s = Section(s.header, s.content, s.kind, s.bullet, protected=s.protected, body_bold=s.body_bold, body_color=s.body_color)
            if s.kind == "bulleted":
                new_s.content = list(s.content)
                new_s._chunks = new_s.content  # same list object, mutated in place
            else:
                new_s._chunks = [c for c in re.split(r"(?<=[.!?])\s+", s.content.strip()) if c]
            working_sections.append(new_s)

        def _remove_one(allow_protected):
            for s in reversed(working_sections):
                if s.protected and not allow_protected:
                    continue
                if len(s._chunks) > 0:
                    dropped_items.append(s._chunks.pop())
                    s.content = s._chunks if s.kind == "bulleted" else " ".join(s._chunks)
                    return True
            return False

        while True:
            total = _total_height(working_sections, hf, bf, max_w, **chosen_spacing)
            if total <= available_h:
                truncated = len(dropped_items) > 0
                break
            if _remove_one(allow_protected=False):
                continue
            # Nothing non-protected left to trim -- as an absolute last
            # resort, allow touching protected content too rather than
            # overflowing the box, but this should be rare in practice.
            if _remove_one(allow_protected=True):
                continue
            truncated = len(dropped_items) > 0
            break
    else:
        hf = _font(font_weight_header, max(int(base_header_size * chosen_scale), 1))
        bf = _font(font_weight_body, max(int(base_body_size * chosen_scale), 1))

    if measure_only:
        return chosen_scale, chosen_spacing, needed_fallback

    # 3. Draw (skip any section that got fully emptied by truncation --
    # an empty header with nothing underneath looks like a bug, not a
    # deliberate omission, so it's cleaner to drop the header too). No
    # truncation note is drawn on the label -- dropped_items is returned
    # instead so the caller can surface it (e.g. a review panel in the
    # app), per direct feedback against printing a disclaimer on the
    # label itself.
    cursor_y = y0 + pad
    for s in working_sections:
        if not s.content:
            continue
        if s.header:
            draw.text((cursor_x, cursor_y), s.header, font=hf, fill=fill_header)
            cursor_y += int(hf.size * chosen_spacing["header_ratio"])
        section_color = s.body_color or fill_body
        if s.kind == "text":
            body_font_for_section = _font("bold", bf.size) if s.body_bold else bf
            cursor_y = _draw_wrapped_text(draw, (cursor_x, cursor_y), s.content, body_font_for_section, section_color, max_w,
                                           line_spacing=chosen_spacing["line_spacing"])
        else:
            cursor_y = _draw_bulleted_list(draw, (cursor_x, cursor_y), s.content, bf, section_color, max_w, bullet=s.bullet,
                                            line_spacing=chosen_spacing["line_spacing"], bullet_gap=chosen_spacing["bullet_gap"])
        cursor_y += int(bf.size * chosen_spacing["gap"])

    return cursor_y, truncated, dropped_items


def render_compact_label(
    canvas_size_in,
    background_path,
    vertical_name,
    category,
    sds_data,
    tds_bullets_selected,
    product_name,
    sales_description,   # single bar, unlike the main template's two
    product_code,
    size_label,           # e.g. "13 oz/369 g"
    dimension_group,      # "8.25x6.5" | "11.5x3.5" | "12x4.125" -- selects
                          # which measured COMPACT_ZONES_* set to use (see
                          # layout_config.COMPACT_ZONE_SET_BY_DIMENSION_GROUP).
                          # Required -- Aerosol/22L/108L Canister are three
                          # different aspect ratios and do NOT share correct
                          # element proportions, so there's no safe default.
    baked_background_path=None,  # pre-rendered background (see
                          # template_config.get_template()) already
                          # containing everything that isn't specific to
                          # one product -- same meaning as in render_label.
                          # When None, falls back to drawing everything
                          # from scratch via background_path.
    badge_color=None,
    badge_icon_path=None,
    case_quantity=None,   # e.g. "QTY: 12" -- box-label variant only
    internal_label_number=None,
    lot_number="LOT#",
    force_exclude_response=False,  # proactively exclude P3xx (Response)
                          # precautionary statements for larger/more
                          # readable text, rather than only falling back
                          # to excluding them automatically as a last
                          # resort when content doesn't fit otherwise.
                          # P4xx/P5xx (Storage/Disposal) are always
                          # excluded regardless of this flag, since that
                          # content is shown separately either way.
    dpi=150,
    output_path=None,
):
    """Three-column layout used by Aerosol, 22L Canister, and 108L
    Canister -- confirmed via real label PDFs (AP1592/93/94/95) to be
    structurally different from the main two-column template. Left
    column: Directions/Storage & Handling. Center column: stacked logo,
    badge, product name, one sales bar, size. Right column: Signal
    Word/Hazard/Precautionary, then a fixed-position Contains/CAS-number
    section + pictograms anchored at the bottom.
    """
    from layout_config import (
        COLOR_NAVY, COLOR_ORANGE, COLOR_GREY_BOX, COLOR_WHITE, COLOR_DARK_TEXT,
        CATEGORY_ACCENT_COLOR, VERTICAL_BADGE_TEXT_COLOR, DEFAULT_BADGE_TEXT_COLOR,
        compact_zone_px,
    )

    w_in, h_in = canvas_size_in
    supersample = 2
    W, H = round(w_in * dpi) * supersample, round(h_in * dpi) * supersample
    canvas = Image.new("RGB", (W, H), COLOR_NAVY)
    draw = ImageDraw.Draw(canvas)

    using_baked_background = baked_background_path is not None

    if using_baked_background:
        # Everything fixed is already rendered into this image -- see the
        # equivalent note in render_label for the full list of what that
        # covers. Skip straight to drawing dynamic content on top of it.
        bg = Image.open(baked_background_path).convert("RGBA")
        bg_resized = bg.resize((W, H))
        canvas.paste(bg_resized, (0, 0))
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
    else:
        bg = Image.open(background_path).convert("RGBA")
        bg_resized = bg.resize((W, H))
        canvas.paste(bg_resized, (0, 0), bg_resized)

    accent_color = CATEGORY_ACCENT_COLOR[category] if not using_baked_background else None
    badge_text_color = VERTICAL_BADGE_TEXT_COLOR.get(vertical_name, DEFAULT_BADGE_TEXT_COLOR)

    lx0, ly0, lx1, ly1 = compact_zone_px("left_box", W, H, dimension_group=dimension_group)
    rx0, ry0, rx1, ry1 = compact_zone_px("right_box", W, H, dimension_group=dimension_group)

    # box_radius is needed below (orange_bar reuses it) regardless of
    # which branch runs, so it's computed unconditionally.
    box_radius = max(int(0.0056 * H), 1)

    if not using_baked_background:
        # Shadows behind both grey boxes.
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_offset = (max(int(0.006 * W), 2), max(int(0.008 * H), 2))
        shadow_blur = max(int(0.012 * H), 3)
        for (bx0, by0, bx1, by1) in [(lx0, ly0, lx1, ly1), (rx0, ry0, rx1, ry1)]:
            shadow_draw.rounded_rectangle(
                [bx0 + shadow_offset[0], by0 + shadow_offset[1], bx1 + shadow_offset[0], by1 + shadow_offset[1]],
                radius=box_radius, fill=(0, 0, 0, 110),
            )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow_layer).convert("RGB")
        draw = ImageDraw.Draw(canvas)

        draw.rounded_rectangle([lx0, ly0, lx1, ly1], radius=box_radius, fill=COLOR_GREY_BOX)
        draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=box_radius, fill=COLOR_GREY_BOX)

    pad = int(0.015 * (lx1 - lx0))
    header_font_size = int(0.022 * H)
    body_font_size = int(0.018 * H)

    # --- LEFT BOX: Directions for Use, then a manually-built "Storage
    # and Handling" block (this section has its own distinct structure
    # in the real label -- ONE orange header covering both subsections,
    # each with its own black ALL-CAPS sub-header, not two separate
    # orange-headed sections like the main template uses) ---
    directions_sections = [
        Section("DIRECTIONS FOR USE", "FOR INDUSTRIAL USE ONLY", kind="text", protected=True, body_bold=True),
        Section("", tds_bullets_selected, kind="bulleted", protected=True),
    ]
    # Reserve room at the bottom of the left box for the fixed footer
    # logo lockup -- content must stop before that zone starts, not an
    # arbitrary fraction.
    footer_fixed_y0 = compact_zone_px("footer_logo_fixed", W, H, dimension_group=dimension_group)[1]
    left_content_bottom = footer_fixed_y0 - int(0.01 * H)
    # Split point between "Directions" and "Storage and Handling" comes
    # directly from the real label's measured position (left_header2),
    # not a guessed fraction.
    directions_bottom = compact_zone_px("left_header2", W, H, dimension_group=dimension_group)[1] - int(0.005 * H)
    cursor_y, _, directions_dropped = fit_and_draw_box(
        draw, (lx0, ly0, lx1, directions_bottom), directions_sections,
        header_font_size, body_font_size, (lx1 - lx0) - 2 * pad,
        fill_header=COLOR_ORANGE,
    )

    if category != "Tape" and sds_data:
        max_w_left = (lx1 - lx0) - 2 * pad
        storage_text = sds_data.get("storage") or "N/A"
        disposal_text = sds_data.get("disposal") or "N/A"
        available_h = left_content_bottom - (directions_bottom + int(0.01 * H))

        def _measure_storage_block(scale):
            hf = _font("bold", max(int(header_font_size * scale), 1))
            sub_f = _font("bold", max(int(body_font_size * scale), 1))
            body_f = _font("regular", max(int(body_font_size * scale), 1))
            wrap_w = max(int(max_w_left / (body_f.size * 0.55)), 10)
            n_storage_lines = len(textwrap.wrap(storage_text, width=wrap_w))
            n_disposal_lines = len(textwrap.wrap(disposal_text, width=wrap_w))
            total = int(hf.size * 1.3) + int(sub_f.size * 1.25) + n_storage_lines * int(body_f.size * 1.25)
            total += int(body_f.size * 0.4) + int(sub_f.size * 1.25) + n_disposal_lines * int(body_f.size * 1.25)
            return total, hf, sub_f, body_f, wrap_w

        scale = 1.0
        total_h, hf, sub_f, body_f, wrap_w = _measure_storage_block(scale)
        while total_h > available_h and scale > 0.5:
            scale -= 0.05
            total_h, hf, sub_f, body_f, wrap_w = _measure_storage_block(scale)

        sh_y = directions_bottom + int(0.01 * H)
        draw.text((lx0 + pad, sh_y), "STORAGE AND HANDLING", font=hf, fill=COLOR_ORANGE)
        sh_y += int(hf.size * 1.3)
        draw.text((lx0 + pad, sh_y), "STORAGE", font=sub_f, fill=COLOR_DARK_TEXT)
        sh_y += int(sub_f.size * 1.25)
        for line in textwrap.wrap(storage_text, width=wrap_w):
            draw.text((lx0 + pad, sh_y), line, font=body_f, fill=COLOR_DARK_TEXT)
            sh_y += int(body_f.size * 1.25)
        sh_y += int(body_f.size * 0.4)
        draw.text((lx0 + pad, sh_y), "WASTE DISPOSAL", font=sub_f, fill=COLOR_DARK_TEXT)
        sh_y += int(sub_f.size * 1.25)
        for line in textwrap.wrap(disposal_text, width=wrap_w):
            draw.text((lx0 + pad, sh_y), line, font=body_f, fill=COLOR_DARK_TEXT)
            sh_y += int(body_f.size * 1.25)

    # --- RIGHT BOX: Signal Word / Hazard / Precautionary (top), then
    # Contains + pictograms anchored at a FIXED position at the bottom,
    # matching the real label exactly rather than flowing dynamically. ---
    pictogram_codes = sds_data.get("pictograms", []) if (category != "Tape" and sds_data) else []
    n_pics = len(pictogram_codes)

    contains_x0, contains_y0, _, _ = compact_zone_px("contains_header", W, H, dimension_group=dimension_group)
    top_section_bottom = contains_y0 - int(0.01 * H)

    if category != "Tape" and sds_data:
        signal_word = (sds_data.get("signal_word") or "N/A").upper()
        hazard_texts = [h["text"] for h in sds_data.get("hazard_statements", [])]
        space_safe_precautions = strip_redundant_precautions(sds_data.get("precautionary_statements", []))

        def _build_right_sections(precautions, add_note):
            secs = [
                Section("SIGNAL WORD", signal_word, kind="text"),
                Section("HAZARD STATEMENTS", hazard_texts, kind="bulleted", bullet=""),
                Section("PRECAUTIONARY STATEMENTS", [p["text"] for p in precautions], kind="bulleted"),
            ]
            if add_note:
                secs.append(Section(
                    "", "See SDS for additional precautionary information.",
                    kind="text", protected=True, body_color=COLOR_ORANGE,
                ))
            return secs

        if force_exclude_response:
            non_response, response = split_response_precautions(space_safe_precautions)
            right_sections = _build_right_sections(non_response, add_note=bool(response))
        else:
            right_sections = _build_right_sections(space_safe_precautions, add_note=False)
        right_box_bounds = (rx0, ry0, rx1, top_section_bottom)
        right_max_w = (rx1 - rx0) - 2 * pad
        _, _, needed_fallback = fit_and_draw_box(
            None, right_box_bounds, right_sections,
            header_font_size, body_font_size, right_max_w,
            fill_header=COLOR_ORANGE, min_scale=0.4, measure_only=True,
        )
        if needed_fallback and not force_exclude_response:
            non_response, response = split_response_precautions(space_safe_precautions)
            if response:
                right_sections = _build_right_sections(non_response, add_note=True)

        _, _, right_dropped = fit_and_draw_box(
            draw, right_box_bounds, right_sections,
            header_font_size, body_font_size, right_max_w,
            fill_header=COLOR_ORANGE,
            min_scale=0.4,
        )
    else:
        right_dropped = []

    # Pictograms reserve the right portion of this fixed bottom band; give
    # them real breathing room from the box's own border this time.
    pic_band_pad = int(0.05 * (rx1 - rx0))
    # Ratio calibrated against two real reference labels (AP363 22L
    # Canister, AP402 108L Canister), both showing a 2-icon cluster:
    # measured cluster width was ~22.6% and ~22.1% of box_right's own
    # width respectively (was 0.28, an uncalibrated guess).
    pic_col_w = int(0.223 * (rx1 - rx0)) if n_pics else 0
    contains_text_w = (rx1 - rx0) - 2 * pad - pic_col_w - pic_band_pad

    ingredients = sds_data.get("ingredients") or [] if (category != "Tape" and sds_data) else []
    if ingredients:
        available_h_contains = (ry1 - pad) - contains_y0

        def _measure_contains(scale):
            hf2 = _font("bold", max(int(header_font_size * scale), 1))
            bf2 = _font("regular", max(int(body_font_size * scale), 1))
            ing_h, _ = _measure_ingredient_list_height(ingredients, bf2, bf2, contains_text_w)
            total = int(hf2.size * 1.35) + ing_h
            return total, hf2, bf2

        scale = 1.0
        total_h, hf2, bf2 = _measure_contains(scale)
        while total_h > available_h_contains and scale > 0.45:
            scale -= 0.05
            total_h, hf2, bf2 = _measure_contains(scale)

        draw.text((rx0 + pad, contains_y0), "CONTAINS", font=hf2, fill=COLOR_ORANGE)
        line_y = contains_y0 + int(hf2.size * 1.35)
        _draw_ingredient_list(draw, (rx0 + pad, line_y), ingredients, bf2, bf2, COLOR_DARK_TEXT, COLOR_DARK_TEXT, contains_text_w)

    if n_pics:
        pic_size = int(pic_col_w / 1.9)
        base_gap = 5
        touch_offset = int(pic_size * 0.53)
        pic_center_x = rx1 - pad - pic_band_pad - pic_col_w / 2
        pic_bottom_y = ry1 - pad - pic_band_pad - pic_size
        col_span = pic_size + base_gap
        col_l_x = pic_center_x - col_span / 2 - pic_size / 2
        col_r_x = pic_center_x + col_span / 2 - pic_size / 2
        positions = _pictogram_positions(n_pics, pic_size, base_gap, touch_offset, col_l_x, col_r_x, pic_center_x, pic_bottom_y)
        for code, (px, py) in zip(pictogram_codes, positions):
            candidates = [f for f in os.listdir("pictograms") if f.startswith(code)]
            if not candidates:
                continue
            pic_img = Image.open(os.path.join("pictograms", candidates[0])).convert("RGBA").resize((pic_size, pic_size))
            canvas.paste(pic_img, (int(px), int(py)), pic_img)
    draw = ImageDraw.Draw(canvas)

    # --- CENTER COLUMN ---
    # Stacked logo (eagle above wordmark) -- confirmed from the real
    # label that this differs from the horizontal lockup used elsewhere.
    # Constrained to fit entirely ABOVE the orange divider line (which
    # sits between the logo and the vertical name at a SMALLER y than
    # vname_top -- constraining only against vname_top let the logo
    # extend past the divider into it).
    if not using_baked_background:
        logo_x0, logo_y0, logo_x1, logo_y1 = compact_zone_px("logo_lockup", W, H, dimension_group=dimension_group)
        divider_top = compact_zone_px("orange_divider", W, H, dimension_group=dimension_group)[1]
        logo_area_top = ly0
        logo_area_bottom = divider_top - int(0.015 * H)
        logo_img = Image.open("logos/bond_stacked_lockup.png").convert("RGBA")
        avail_w = logo_x1 - logo_x0
        avail_h = logo_area_bottom - logo_area_top
        logo_ratio = min(avail_w / logo_img.width, avail_h / logo_img.height)
        logo_resized = logo_img.resize((int(logo_img.width * logo_ratio), int(logo_img.height * logo_ratio)))
        logo_paste_x = logo_x0 + (avail_w - logo_resized.width) // 2
        logo_paste_y = logo_area_bottom - logo_resized.height
        canvas.paste(logo_resized, (logo_paste_x, logo_paste_y), logo_resized)

        div_x0, div_y0, div_x1, div_y1 = compact_zone_px("orange_divider", W, H, dimension_group=dimension_group)
        draw.rectangle([div_x0, div_y0, div_x1, div_y1], fill=accent_color)

        vx0, vy0, vx1, vy1 = compact_zone_px("vertical_name", W, H, dimension_group=dimension_group)
        draw.text((vx0, vy0), vertical_name, font=_font("kallisto", int(0.052 * H)), fill=COLOR_WHITE)

    # badge_box bounds are needed below regardless (product code text
    # still positions against the real badge box, baked or freshly drawn).
    bx0, by0, bx1, by1 = compact_zone_px("badge_box", W, H, dimension_group=dimension_group)
    if not using_baked_background:
        draw.rounded_rectangle([bx0, by0, bx1, by1], radius=int((by1 - by0) * 0.10), fill=COLOR_WHITE)

    # Icon position computed FIRST so the code/color text can center
    # within the space the icon actually leaves clear, not the full box.
    icon_x0 = bx1
    if badge_icon_path:
        ix0, iy0, ix1, iy1 = compact_zone_px("boat_icon", W, H, dimension_group=dimension_group)
        icon_x0 = ix0

    code_avail_w = (icon_x0 - int(0.01 * W)) - bx0
    code_font = _font("kallisto", int((by1 - by0) * 0.5))
    code_bbox = code_font.getbbox(product_code)
    code_w = code_font.getlength(product_code)
    code_x = bx0 + (code_avail_w - code_w) / 2
    draw.text((code_x, by0 + (by1 - by0) * 0.12 - code_bbox[1]), product_code, font=code_font, fill=badge_text_color)
    if badge_color:
        # Enforced all-caps as a defensive safeguard (app.py also
        # enforces this at input) -- uppercase letters, including J,
        # have no descender in Kallisto, while lowercase does, so this
        # guarantees the descender-overflow fix never has a reason to
        # trigger regardless of how badge_color reaches this function.
        badge_color = badge_color.upper()
        color_font = _font("kallisto", int((by1 - by0) * 0.28))
        color_bbox = color_font.getbbox(badge_color)
        color_w = color_font.getlength(badge_color)
        color_x = bx0 + (code_avail_w - color_w) / 2
        draw.text((color_x, by0 + (by1 - by0) * 0.62 - color_bbox[1]), badge_color, font=color_font, fill=badge_text_color)

    if badge_icon_path and not using_baked_background:
        icon_size = ix1 - ix0
        icon_img = Image.open(badge_icon_path).convert("RGBA").resize((icon_size, icon_size))
        icon_shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        icon_shadow_alpha = icon_img.split()[3].point(lambda a: 110 if a > 20 else 0)
        icon_shadow_shape = Image.new("RGBA", icon_img.size, (0, 0, 0, 255))
        icon_shadow_shape.putalpha(icon_shadow_alpha)
        icon_shadow_layer.paste(icon_shadow_shape, (ix0 + max(int(0.01 * icon_size), 2), iy0 + max(int(0.015 * icon_size), 3)), icon_shadow_shape)
        icon_shadow_layer = icon_shadow_layer.filter(ImageFilter.GaussianBlur(max(int(0.03 * icon_size), 4)))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), icon_shadow_layer).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        canvas.paste(icon_img, (ix0, iy0), icon_img)

    # Product name -- nudged down further from the badge box than before.
    pn_x0, pn_y0, pn_x1, pn_y1 = compact_zone_px("product_name", W, H, dimension_group=dimension_group)
    pn_y0 += int(0.02 * H)
    pn_font_size = int(0.036 * H)
    pn_font = _font("kallisto", pn_font_size)
    while pn_font.getlength(product_name) > (pn_x1 - pn_x0) and pn_font_size > 10:
        pn_font_size -= 1
        pn_font = _font("kallisto", pn_font_size)
    pn_bbox = pn_font.getbbox(product_name)
    pn_w = pn_font.getlength(product_name)
    draw.text((pn_x0 + ((pn_x1 - pn_x0) - pn_w) / 2, pn_y0 - pn_bbox[1]), product_name, font=pn_font, fill=COLOR_WHITE)

    ob_x0, ob_y0, ob_x1, ob_y1 = compact_zone_px("orange_bar", W, H, dimension_group=dimension_group)
    if not using_baked_background:
        draw.rounded_rectangle([ob_x0, ob_y0, ob_x1, ob_y1], radius=box_radius, fill=accent_color)
    bar_font_size = int(0.028 * H)
    bar_font = _font("bold", bar_font_size)
    sales_caps = sales_description.upper()
    while bar_font.getlength(sales_caps) > (ob_x1 - ob_x0) - 2 * pad and bar_font_size > 8:
        bar_font_size -= 1
        bar_font = _font("bold", bar_font_size)
    bar_bbox = bar_font.getbbox(sales_caps)
    bar_w = bar_font.getlength(sales_caps)
    bar_h = bar_bbox[3] - bar_bbox[1]
    draw.text((ob_x0 + ((ob_x1 - ob_x0) - bar_w) / 2, ob_y0 + ((ob_y1 - ob_y0) - bar_h) / 2 - bar_bbox[1]),
               sales_caps, font=bar_font, fill=COLOR_WHITE)

    sz_x0, sz_y0, sz_x1, sz_y1 = compact_zone_px("size_text", W, H, dimension_group=dimension_group)
    size_font = _font("bold", int(0.024 * H))
    size_line = f"SIZE: {size_label}"
    size_w = size_font.getlength(size_line)
    draw.text((sz_x0 + ((sz_x1 - sz_x0) - size_w) / 2, sz_y0), size_line, font=size_font, fill=COLOR_WHITE)
    if case_quantity:
        qz_x0, qz_y0, qz_x1, qz_y1 = compact_zone_px("qty_text", W, H, dimension_group=dimension_group)
        qty_w = size_font.getlength(case_quantity)
        draw.text((qz_x0 + ((qz_x1 - qz_x0) - qty_w) / 2, qz_y0), case_quantity, font=size_font, fill=COLOR_WHITE)

    # --- Footer logo lockup: FIXED position, size, and content every
    # time -- teal Forza wordmark (this sits on the light grey box, not
    # navy, so the white-recolored version doesn't work here), address
    # directly below it, USA badge placed to the right of the whole
    # logo+address block. All of it (through the disclaimer text) is
    # already baked into the background when using_baked_background. ---
    if not using_baked_background:
        flogo_x0, flogo_y0, flogo_x1, flogo_y1 = compact_zone_px("footer_logo_fixed", W, H, dimension_group=dimension_group)
        footer_logo_img = Image.open("logos/commercial_teal_logo.png").convert("RGBA")
        flogo_ratio = min((flogo_x1 - flogo_x0) / footer_logo_img.width, (flogo_y1 - flogo_y0) / footer_logo_img.height)
        flogo_resized = footer_logo_img.resize((int(footer_logo_img.width * flogo_ratio), int(footer_logo_img.height * flogo_ratio)))
        canvas.paste(flogo_resized, (flogo_x0, flogo_y0), flogo_resized)

        addr_x0, addr_y0, addr_x1, addr_y1 = compact_zone_px("footer_address_fixed", W, H, dimension_group=dimension_group)
        usa_x0_bound = compact_zone_px("footer_usa_badge_fixed", W, H, dimension_group=dimension_group)[0]
        addr_max_w = (usa_x0_bound - int(0.008 * H)) - addr_x0
        address_lines = [
            ("Forza Inc.", True),
            ("3211 Nebraska Ave, Suite 300,", False),
            ("Council Bluffs, IA 51501", False),
            ("www.forzabuilt.com", True),
        ]
        addr_font_size = int(0.017 * H)
        while addr_font_size > 6:
            addr_font_bold = _font("cotext_bold", addr_font_size)
            addr_font_regular = _font("cotext_light", addr_font_size)
            longest = max(
                (addr_font_bold if bold else addr_font_regular).getlength(text)
                for text, bold in address_lines
            )
            if longest <= addr_max_w:
                break
            addr_font_size -= 1
        ay = addr_y0
        for text, bold in address_lines:
            f = addr_font_bold if bold else addr_font_regular
            draw.text((addr_x0, ay), text, font=f, fill=COLOR_DARK_TEXT)
            ay += int(addr_font_size * 1.25)

        usa_x0, usa_y0, usa_x1, usa_y1 = compact_zone_px("footer_usa_badge_fixed", W, H, dimension_group=dimension_group)
        usa_img = Image.open("assets/made_in_usa_badge.png").convert("RGBA")
        usa_ratio = min((usa_x1 - usa_x0) / usa_img.width, (usa_y1 - usa_y0) / usa_img.height)
        usa_resized = usa_img.resize((int(usa_img.width * usa_ratio), int(usa_img.height * usa_ratio)))
        canvas.paste(usa_resized, (usa_x0, usa_y0), usa_resized)

        disc_max_w = (lx1 - pad) - usa_x0
        disc_font_size = int(0.013 * H)
        disc_font = _font("regular", disc_font_size)
        disc_text = "*Manufactured in the USA with domestic and limited foreign-sourced components."
        wrap_w = max(int(disc_max_w / (disc_font.size * 0.5)), 8)
        disc_lines = textwrap.wrap(disc_text, width=wrap_w)
        dy = usa_y0 + usa_resized.height + int(0.008 * H)
        for line in disc_lines:
            draw.text((usa_x0, dy), line, font=disc_font, fill=COLOR_DARK_TEXT)
            dy += int(disc_font.size * 1.25)

    # --- Bottom footer row: AP number (left) ... LOT# (right) ---
    fap_x0, fap_y0, fap_x1, fap_y1 = compact_zone_px("footer_ap", W, H, dimension_group=dimension_group)
    flot_x0, flot_y0, flot_x1, flot_y1 = compact_zone_px("footer_lot", W, H, dimension_group=dimension_group)
    footer_font = _font("kallisto", int(0.022 * H))
    if internal_label_number:
        draw.text((fap_x0, fap_y0), internal_label_number, font=footer_font, fill=COLOR_WHITE)
    draw.text((flot_x0, flot_y0), lot_number, font=footer_font, fill=COLOR_WHITE)

    final_w, final_h = round(w_in * dpi), round(h_in * dpi)
    canvas = canvas.resize((final_w, final_h), Image.LANCZOS)
    if output_path:
        canvas.save(output_path)
    dropped_content = {"left": directions_dropped, "right": right_dropped}
    return canvas, dropped_content


def render_label(
    *,
    canvas_size_in,        # (width_in, height_in)
    background_path,       # vertical background art -- only used as a
                           # fallback when baked_background_path is None
    baked_background_path=None,  # pre-rendered background (see
                           # template_config.get_template()) already
                           # containing the background art, drop shadows,
                           # category logo, vertical name, badge box,
                           # vertical icon, orange bars, grey boxes, the
                           # Made-in-USA badge/disclaimer, and the footer
                           # logo/address -- i.e. everything that isn't
                           # specific to one product. When given, all of
                           # that is skipped and only the dynamic,
                           # per-product content (product code, hazard/
                           # directions text, pictograms, footer SIZE/LOT/
                           # AP fields) is drawn on top of it. When None,
                           # falls back to drawing everything from scratch
                           # via background_path, for any vertical/category
                           # combination that doesn't have a baked
                           # background registered yet.
    vertical_name,          # e.g. "Construction"
    category,               # "Adhesive" | "Sealant" | "Tape"
    dimension_group=None,   # "8x6" | "8x8" | "6x4" | "8.25x6.25" -- selects
                            # the vertical-specific measured badge position
                            # (see layout_config.BADGE_ZONES_BY_VERTICAL).
                            # Only needed when baked_background_path is
                            # set; omitting it falls back to Marine's
                            # badge position for that vertical.
    sds_data=None,                # dict from parse_sds.parse_sds(), or None for Tape
    tds_bullets_selected,    # list[str], verbatim from parse_tds
    product_name,              # product TYPE description, e.g. "Pressure Sensitive Adhesive" -- appears below the code pill
    sales_description_1,
    sales_description_2,
    product_code,
    size_label,              # e.g. "5 Gallon Pail"
    badge_color=None,        # e.g. "WHITE" -- optional; if given, shown as the second, smaller line under the product code
    badge_icon_path=None,     # circular vertical-specific icon (e.g. hard hat, boat), overlaps the product-code pill's right edge
    internal_label_number=None,  # e.g. "APXXXX" -- Forza's internal label ID, shown in the FOOTER only (distinct from the customer-facing product_code shown in the badge box)
    case_quantity=None,       # optional -- only relevant for Box Labels on Cartridge/Sausage products; shown below the size in the footer when set
    lot_number="LOT#",
    force_exclude_response=False,  # proactively exclude P3xx (Response)
                          # precautionary statements for larger/more
                          # readable text, rather than only falling back
                          # to excluding them automatically as a last
                          # resort when content doesn't fit otherwise.
                          # P4xx/P5xx (Storage/Disposal) are always
                          # excluded regardless of this flag, since that
                          # content is shown separately either way.
    dpi=150,
    pictogram_dir="pictograms",
    output_path=None,
):
    w_in, h_in = canvas_size_in
    # Supersample at 2x internally, then downscale with high-quality
    # resampling at the very end -- PIL's shape drawing (rounded_rectangle
    # included) isn't anti-aliased on its own, so corners and curves come
    # out visibly jagged at native resolution. Rendering everything bigger
    # and shrinking it back down smooths every curve on the label at once
    # rather than patching each rounded box individually.
    supersample = 2
    W, H = round(w_in * dpi) * supersample, round(h_in * dpi) * supersample

    canvas = Image.new("RGB", (W, H), COLOR_NAVY)
    draw = ImageDraw.Draw(canvas)

    using_baked_background = baked_background_path is not None

    if using_baked_background:
        # Everything fixed (background art, drop shadows, category logo,
        # vertical name, badge box shape, vertical icon, orange bars,
        # grey box shapes, Made-in-USA badge/disclaimer, footer logo/
        # address) is already rendered into this image -- just use it as
        # the starting canvas and skip straight to drawing dynamic content.
        bg = Image.open(baked_background_path).convert("RGBA")
        bg_resized = bg.resize((W, H))
        canvas.paste(bg_resized, (0, 0))
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
    else:
        # --- Background art, stretched to cover the FULL label (not just the
        # header strip) -- the flat navy fill below the header was a stand-in
        # while the header-only version was being worked out, but the real
        # templates stretch the background artwork the entire way down. ---
        bg = Image.open(background_path).convert("RGBA")
        bg_resized = bg.resize((W, H))
        canvas.paste(bg_resized, (0, 0), bg_resized)

        # --- Drop shadows behind every box/bar element ---
        # Per direct reference from the real label: there's a soft drop
        # shadow behind the sales-description bars, the grey content boxes,
        # and the badge box -- visible on the bottom and right edges only
        # (offset down-right), not on top/left. This is invisible to a flat
        # vector-fill inspection because Illustrator drop-shadow effects
        # typically export as a separate blurred raster layer, not a fill
        # property on the shape itself. All shadow shapes are drawn onto one
        # transparent layer and blurred together, then composited once,
        # BEFORE any of the actual opaque boxes are drawn on top.
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_offset = (max(int(0.006 * W), 2), max(int(0.008 * H), 2))
        shadow_blur = max(int(0.012 * H), 3)
        shadow_opacity = 110
        box_corner_radius_preview = max(int(0.0056 * H), 1)
        badge_corner_radius_preview = int(0.02 * H)

        _sh_boxes = [
            (zone_px("orange_bar_left", W, H), box_corner_radius_preview),
            (zone_px("orange_bar_right", W, H), box_corner_radius_preview),
            (zone_px("box_left", W, H), box_corner_radius_preview),
            (zone_px("box_right", W, H), box_corner_radius_preview),
            (zone_px("badge", W, H), badge_corner_radius_preview),
        ]
        for (bx0, by0, bx1, by1), radius in _sh_boxes:
            shadow_draw.rounded_rectangle(
                [bx0 + shadow_offset[0], by0 + shadow_offset[1], bx1 + shadow_offset[0], by1 + shadow_offset[1]],
                radius=radius, fill=(0, 0, 0, shadow_opacity),
            )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow_layer).convert("RGB")
        draw = ImageDraw.Draw(canvas)

        # --- Badge: white box with the product code + optional color, two
        # lines, sized and spaced per exact measurements taken from a real
        # reference label (T-OS166 / WHITE) -- this is the widest product
        # code Forza expects, so its rendered width is used as the hard
        # ceiling other codes must fit within, shrinking font size if needed
        # rather than ever exceeding it.
        bx0, by0, bx1, by1 = zone_px("badge", W, H)
        # Measured directly off the reference: corner radius is ~10% of the
        # box's OWN height, not a fraction of the full canvas -- using H made
        # the ratio drift on different canvas/box proportions.
        corner_radius = int((by1 - by0) * 0.10)
        # Composites' icon has an irregular (turbine-blade) silhouette that
        # doesn't fully cover a box drawn all the way to the usual bx1 --
        # narrow just the drawn box's right edge here so it tucks fully
        # behind the icon, without changing bx1 for icon/text positioning
        # below (which already tested well at the current position).
        if vertical_name == "Composites":
            # A circle's left edge curves INWARD (rightward) away from its
            # own vertical center -- using the center's x-position (the
            # circle's widest point) to narrow the box left a visible
            # rectangular corner sticking out wherever the box's own
            # vertical range doesn't line up with that one widest row.
            # Instead, solve for the circle's actual left edge AT the
            # box's own bottom edge (by1), the tightest point against the
            # box's full height, using the circle equation directly.
            import math
            _box_h_for_icon = by1 - by0
            _icon_size_for_box = int(_box_h_for_icon * 1.733 * 1.15)
            _icon_radius = _icon_size_for_box / 2
            _icon_center_x_for_box = bx1 - _box_h_for_icon * 0.52
            _icon_top_for_box = by0 - _box_h_for_icon * 0.605
            _icon_center_y_for_box = _icon_top_for_box + _icon_radius
            _dy = by1 - _icon_center_y_for_box
            if abs(_dy) < _icon_radius:
                _dx = math.sqrt(_icon_radius ** 2 - _dy ** 2)
                _box_draw_bx1 = int(_icon_center_x_for_box - _dx)
            else:
                _box_draw_bx1 = int(_icon_center_x_for_box - _icon_radius)
        else:
            _box_draw_bx1 = bx1
        draw.rounded_rectangle([bx0, by0, _box_draw_bx1, by1], radius=corner_radius, fill=COLOR_WHITE)

        # --- Vertical name (e.g. "Industrial") ---
        # Positioned relative to the badge box's own top edge (just drawn
        # above) rather than a fixed zone position disconnected from it --
        # this keeps the name sitting snugly just above the badge
        # regardless of exactly where the badge box ends up. Font size
        # scales with the badge box height too, rather than a small fixed
        # size that didn't visually match the badge's own scale.
        vx0, _, _, _ = zone_px("vertical_name", W, H)
        box_h = by1 - by0
        # Same icon-position formula used below, inlined here so the
        # available width (vx0 to the icon's left edge) is known before
        # the icon itself is drawn -- per direct feedback, the name should
        # stretch to meet the icon, matching the real reference.
        _vn_icon_size = box_h * (1.733 if dimension_group != "8x8" else 1.733 * 0.85)
        _vn_icon_center_x = bx1 - box_h * 0.52
        _vn_icon_left = _vn_icon_center_x - _vn_icon_size / 2
        vert_name_avail_w = max(_vn_icon_left - vx0, 1)
        vert_name_max_h = (by1 - by0) * 0.55
        probe_size = 100
        probe_font = _font("kallisto", probe_size)
        probe_w = probe_font.getlength(vertical_name)
        vert_name_font_size = int(probe_size * vert_name_avail_w / probe_w)
        # Height cap, same reasoning as the product-code width/height cap:
        # a short vertical name stretched to the same width as a long one
        # would otherwise end up far taller than the badge area allows.
        vert_name_font_size = min(vert_name_font_size, int(vert_name_max_h / 0.78))
        vert_name_font = _font("kallisto", vert_name_font_size)
        vert_name_gap = int((by1 - by0) * 0.12)
        vn_bbox = vert_name_font.getbbox(vertical_name)
        vy0 = by0 - vert_name_gap - (vn_bbox[3] - vn_bbox[1]) - vn_bbox[1]
        draw.text((vx0, vy0), vertical_name, font=vert_name_font, fill=COLOR_WHITE)

    # badge_box bounds are needed below regardless of which branch ran
    # (the product code text still has to be positioned/sized against the
    # real badge box, baked or freshly drawn) -- this stays unconditional.
    # Uses the vertical-specific measured position when using a baked
    # background (each vertical's real badge box sits at its own
    # position, not Marine's, and was never moved to match) -- falls
    # back to Marine's zone_px result for the non-baked path, where
    # everything including the badge box is drawn fresh at Marine's
    # position anyway. Computed BEFORE the logo below, since the logo's
    # own alignment depends on this same vertical-specific position.
    if using_baked_background and dimension_group is not None:
        bx0, by0, bx1, by1 = badge_zone_px(vertical_name, dimension_group, W, H)
    else:
        bx0, by0, bx1, by1 = zone_px("badge", W, H)
    from layout_config import CATEGORY_ACCENT_COLOR
    accent_color = CATEGORY_ACCENT_COLOR[category]
    badge_text_color = VERTICAL_BADGE_TEXT_COLOR.get(vertical_name, DEFAULT_BADGE_TEXT_COLOR)

    # --- Logo (category-based: BOND/SEAL/TAPE lockup, per brand standards --
    # logo does NOT vary by vertical, only by product category) -- drawn
    # unconditionally (even with a baked background) so switching category
    # alone swaps the logo, rather than requiring a separate baked image
    # per category. Aligned to THIS vertical's own real badge position
    # (bx0-by1, just computed above), not a generic fallback -- using the
    # wrong one here previously caused the logo to overlap the bar below
    # it whenever a vertical's real badge position differed from Marine's.
    from layout_config import CATEGORY_LOGO
    lx0, ly0, lx1, ly1 = zone_px("logo", W, H)
    logo_path = CATEGORY_LOGO[category]
    logo = Image.open(logo_path).convert("RGBA")
    logo_ratio = min((lx1 - lx0) / logo.width, (ly1 - ly0) / logo.height)
    logo_resized = logo.resize((int(logo.width * logo_ratio), int(logo.height * logo_ratio)))
    logo_y = by1 - logo_resized.height
    canvas.paste(logo_resized, (lx0, logo_y), logo_resized)

    box_h = by1 - by0
    box_w = bx1 - bx0

    # Compute the icon's position FIRST, since the text needs to know
    # where the icon's left edge lands -- text must center/stretch within
    # the space from the box's left edge to the icon's left edge, not the
    # box's own right edge (which the icon overlaps well past).
    icon_x = bx1  # default: no icon, text can use the full box width
    if badge_icon_path:
        # Reverted -- the 1.27x/0.2735 remeasurement made things worse
        # per direct feedback. Back to the values already confirmed
        # through several rounds of direct iteration.
        #
        # icon_x/icon_size etc. are still computed even when using a
        # baked background (which already has the icon painted in) --
        # the product code text below needs icon_x to know where to
        # stop stretching, regardless of who actually drew the icon.
        # When a real measured icon position exists for this vertical/
        # dimension_group (the baked icon's own native position, not
        # Marine's formula-derived one), use that instead -- the formula
        # was calibrated against Marine's own badge box proportions, so
        # applying it to a vertical with different proportions silently
        # produces the wrong icon_x, which shrinks or enlarges the
        # calibrated product-code font size as a side effect.
        measured_icon = None
        if using_baked_background and dimension_group is not None:
            measured_icon = icon_zone_px(vertical_name, dimension_group, W, H)
        if measured_icon is not None:
            icon_x, icon_y, icon_x1, icon_y1 = measured_icon
            icon_size = icon_x1 - icon_x
        else:
            _icon_size_ratio = 1.733 if dimension_group != "8x8" else 1.733 * 0.85
            if vertical_name == "Composites":
                _icon_size_ratio *= 1.15
            icon_size = int(box_h * _icon_size_ratio)
            icon_top_offset = box_h * 0.605
            icon_center_x = bx1 - box_h * 0.52
            icon_x = int(icon_center_x - icon_size / 2)
            icon_y = int(by0 - icon_top_offset)

        if not using_baked_background:
            icon_img = Image.open(badge_icon_path).convert("RGBA").resize((icon_size, icon_size))

            # Soft drop shadow behind the icon -- matches the same offset/blur
            # style already used for the boxes/bars, replacing the flat grey
            # ring that was baked into the icon's original source artwork
            # (designed for the brand standards' grey page background, not
            # ours) and had to be stripped out during extraction.
            icon_shadow_offset = (max(int(0.01 * icon_size), 2), max(int(0.015 * icon_size), 3))
            icon_shadow_blur = max(int(0.03 * icon_size), 4)
            shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            shadow_alpha = icon_img.split()[3].point(lambda a: 110 if a > 20 else 0)
            shadow_shape = Image.new("RGBA", icon_img.size, (0, 0, 0, 255))
            shadow_shape.putalpha(shadow_alpha)
            shadow_layer.paste(shadow_shape, (icon_x + icon_shadow_offset[0], icon_y + icon_shadow_offset[1]), shadow_shape)
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(icon_shadow_blur))
            canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow_layer).convert("RGB")
            draw = ImageDraw.Draw(canvas)

            canvas.paste(icon_img, (icon_x, icon_y), icon_img)

    # Text is centered and sized within (bx0 to icon_x), NOT (bx0 to
    # bx1) -- the reference image's proportions were measured against a
    # badge where the icon barely overlaps the box, but our icon overlaps
    # much further in, so the actually-available width is narrower.
    # Asymmetric padding, matching the reference: T-OS166 has a real but
    # modest left margin (~4.7% of box width measured), but its right
    # edge sits almost flush against where the icon starts -- barely any
    # buffer at all. A symmetric pad was pulling the stretch point away
    # from the icon on the right when it should be hugging it closely.
    left_pad = int(0.047 * box_w)
    right_pad = int(0.006 * box_w)
    text_x0 = bx0 + left_pad
    # 10% safety margin -- confirmed via direct testing that product
    # code can overflow the box's left edge for some verticals (e.g.
    # Marine, which uses a fallback icon_x formula rather than a
    # precisely measured one) even though the shrink-to-fit math checks
    # out exactly on paper. Trading a slightly smaller font for
    # reliably staying contained.
    full_avail_w = (icon_x - right_pad) - text_x0
    avail_w = full_avail_w * 0.9

    # Both ratios measured directly against the reference image's actual
    # rendered glyph bounding boxes (not PIL's requested font-size, which
    # for this font renders at only ~78% of its nominal size -- matching
    # requested font-size to the target ratio alone left the text visibly
    # short). Width and height are now both explicit target dimensions.
    code_h_ratio = 0.419     # T-OS166 glyph height / box height
    color_h_ratio = 0.205    # WHITE glyph height / box height
    # The code line stretches to FILL the actual available width (all the
    # way to the icon's left edge) rather than a fixed ratio of box width
    # -- the fixed ratio was measured from the reference's own available
    # space, which is narrower than ours since our icon overlaps further
    # into the box, so it left a visible gap short of the icon instead of
    # truly stretching to that stopping point. WHITE keeps the same
    # relative proportion to the code line that the reference showed
    # (0.224/0.600), so it scales together with however wide the code
    # line ends up.
    color_to_code_w_ratio = 0.224 / 0.600
    top_pad = box_h * 0.162
    line_gap = box_h * 0.137

    # Calibrate a FIXED point size ONCE using "T-OS166" (the longest code
    # Forza expects) as the reference -- solve for the size where IT
    # naturally spans the available width, undistorted. Any actual product
    # code then renders at this SAME fixed size, no per-text
    # stretching/distortion -- a shorter code like "R-OS86" should just be
    # narrower as a natural consequence of having fewer characters, not
    # forced to match T-OS166's width.
    calibration_text = "T-OS166"
    probe_size = 100
    probe_font = _font("kallisto", probe_size)
    probe_w = probe_font.getlength(calibration_text)
    # Checked against four real references (Industrial "OS2", Transportation
    # "T-OS151", Construction "C-OA5", Insulation "R-OS8") -- none of them
    # follow one consistent rule (their real font sizes imply boost factors
    # from 1.18x to 1.42x over the raw T-OS166-fills-avail_w calibration),
    # meaning the actual designs weren't sized by a single formula. 1.3 is
    # the average across all four -- closer to every real example than the
    # unboosted calibration, though not an exact match to any single one.
    code_font_size_boost = 1.3
    code_font_size = max(int(probe_size * avail_w / probe_w * code_font_size_boost), 10)
    # Height cap: the width-based calibration above assumes a badge box
    # proportioned like the reference it was measured from -- a box that's
    # unusually wide relative to its own height (confirmed on Industrial's
    # 8x8) would otherwise produce a font tall enough to overflow the box
    # vertically even though it fits the available width fine. code_h_ratio
    # was already measured for exactly this (glyph height / box height) but
    # was never actually applied as a constraint until now.
    max_code_font_size = int(box_h * code_h_ratio / 0.78)  # /0.78 since this font renders glyphs at ~78% of nominal size
    code_font_size = min(code_font_size, max_code_font_size)
    code_font = _font("kallisto", code_font_size)
    # Safety shrink -- the calibration above assumes nothing is longer
    # than "T-OS166" (the longest code Forza expects), so an actual code
    # longer than that would overflow avail_w at this fixed size. Only
    # engages for codes that actually need it; normal-length codes are
    # unaffected since they're already narrower than avail_w here.
    while code_font.getlength(product_code) > avail_w and code_font_size > 10:
        code_font_size -= 1
        code_font = _font("kallisto", code_font_size)

    def _draw_fixed_size_text(text, font, x0, y, fill):
        """Draw text normally at its own natural width for the given
        (fixed, pre-calibrated) font size -- no resizing/distortion.
        Offsets for the font's own internal top padding (Kallisto reserves
        empty space above the cap-height that isn't part of the visible
        glyph) so the visible ink lands at y, not y-plus-padding. Returns
        the rendered width so callers can center other text relative to
        it."""
        bbox = font.getbbox(text)
        draw.text((x0, y - bbox[1]), text, font=font, fill=fill)
        return font.getlength(text)

    if badge_color:
        # Enforced all-caps as a defensive safeguard (app.py also
        # enforces this at input) -- uppercase letters, including J,
        # have no descender in Kallisto, while lowercase does, so this
        # guarantees the descender-overflow fix never has a reason to
        # trigger regardless of how badge_color reaches this function.
        badge_color = badge_color.upper()
        # Color font is similarly calibrated once using "WHITE" against
        # the calibrated code width's proportion, then applied fixed.
        color_probe_font = _font("kallisto", probe_size)
        color_probe_w = color_probe_font.getlength("WHITE")
        color_target_w = (code_font.getlength(calibration_text)) * color_to_code_w_ratio
        color_font_size = max(int(probe_size * color_target_w / color_probe_w), 8)
        color_font = _font("kallisto", color_font_size)

        # Center the WHOLE code+gap+color block within box_h (equal top
        # and bottom margins), using each line's ACTUAL rendered glyph
        # height (font.getbbox, not the nominal ratio) -- the previous
        # fixed top_pad offset left a bigger gap above the text than
        # below it on badge boxes whose real height differs from what
        # top_pad/code_h_ratio/etc. were originally calibrated against.
        code_bbox_h = code_font.getbbox(calibration_text)
        code_glyph_h = code_bbox_h[3] - code_bbox_h[1]
        # Actual badge_color text, not the "WHITE" calibration reference --
        # WHITE has no descenders, so real color text with descender
        # letters (j, g, y, p, q) would be under-allocated vertical space
        # here and could extend past the box's bottom edge.
        color_bbox_h = color_font.getbbox(badge_color)
        color_glyph_h = color_bbox_h[3] - color_bbox_h[1]
        total_content_h = code_glyph_h + line_gap + color_glyph_h
        top_margin = (box_h - total_content_h) / 2
        code_y = by0 + top_margin
        color_y = code_y + code_glyph_h + line_gap

        # Center the code's ACTUAL rendered width within the available
        # space (text_x0 to icon_x), rather than always left-anchoring at
        # text_x0 -- with a fixed calibrated size, a shorter code like
        # R-OS86 is narrower than T-OS166, and left-anchoring left it
        # hugging the edge with empty space to its right, which read as
        # not centered the same way T-OS166 (which fills nearly the whole
        # space either way) appeared to be. Centering makes both read
        # consistently regardless of how long the actual code is.
        code_w_natural = code_font.getlength(product_code)
        code_x0 = text_x0 + (full_avail_w - code_w_natural) / 2
        code_w_actual = _draw_fixed_size_text(product_code, code_font, code_x0, code_y, badge_text_color)
        # WHITE centers under the CODE's ACTUAL rendered position/width.
        color_w_actual = color_font.getlength(badge_color)
        color_x0 = code_x0 + code_w_actual / 2 - color_w_actual / 2
        _draw_fixed_size_text(badge_color, color_font, color_x0, color_y, badge_text_color)
    else:
        # No color variant -- the code has the WHOLE box height available
        # (not sharing it with a second line below it), so it should
        # render noticeably larger than the with-color case. Previously
        # this capped against code_font_size -- the width calibrated to
        # fit "T-OS166" (the longest code Forza expects) -- which wrongly
        # constrained SHORT codes like "OS2" to a much smaller size than
        # they could actually use, since a short code is nowhere near
        # overflowing the available width even at a much larger size.
        # Cap against THIS code's own width-fill size instead.
        # Calibrated against a real no-color reference: Construction's
        # "C-OA5" on the same 10.1oz Cartridge (8x6) dimension group has
        # an actual rendered glyph height of 46.72pt against that
        # vertical's own 52.8pt badge box height -- a 0.885 ratio.
        solo_target_h = box_h * 0.885
        probe_bbox = probe_font.getbbox(calibration_text)
        probe_glyph_h = probe_bbox[3] - probe_bbox[1]
        solo_font_size_by_height = int(probe_size * solo_target_h / probe_glyph_h)
        probe_code_w = probe_font.getlength(product_code)
        solo_font_size_by_width = int(probe_size * avail_w / probe_code_w)
        solo_font_size = max(min(solo_font_size_by_height, solo_font_size_by_width), 10)
        solo_font = _font("kallisto", solo_font_size)
        code_bbox = solo_font.getbbox(product_code)
        actual_glyph_h = code_bbox[3] - code_bbox[1]
        code_y = by0 + (box_h - actual_glyph_h) / 2
        code_w_natural = solo_font.getlength(product_code)
        code_x0 = text_x0 + (full_avail_w - code_w_natural) / 2
        _draw_fixed_size_text(product_code, solo_font, code_x0, code_y, badge_text_color)

    # --- Product name/type, below the badge ---
    # Anchored to THIS vertical's real badge position (bx0/bx1/by1,
    # already vertical-aware above), not Marine's fixed product_name
    # zone -- same mismatch as the badge box itself: a real reference
    # (Construction's "Performance Polymer") left-aligns exactly with
    # its own badge box's left edge, which differs from Marine's by
    # ~29pt on this dimension group. Right edge and top gap match
    # Marine's own relationship between product_name and its badge
    # (x1 sits almost exactly at the badge's own x1; a small gap below
    # the badge's bottom edge), just computed relative to THIS badge.
    px0 = bx0
    py0 = by1 + box_h * 0.123
    py1 = py0 + box_h * 0.5
    # Hard ceiling: product name text must never reach the bar below it,
    # regardless of font size or 1-line/2-line wrapping. Uses the SAME
    # per-vertical bar position the bar itself draws at (not the generic
    # fraction), so this stays correct for any vertical whose real bar
    # sits at a different position than the default.
    from layout_config import bar_box_zone_px as _bar_box_zone_px_pn
    if using_baked_background and dimension_group is not None:
        _, _bar_top_y, _, _ = _bar_box_zone_px_pn("orange_bar_left", vertical_name, dimension_group, W, H)
    else:
        _, _bar_top_y, _, _ = zone_px("orange_bar_left", W, H)
    product_name_max_bottom = _bar_top_y - int(0.012 * H)
    # Sized by TARGET WIDTH, not a fixed height ratio -- per feedback,
    # the text needs to start and end at the exact same left/right spots
    # as the reference, at one uniform (unstretched) point size. Target
    # right edge is measured relative to OUR OWN icon's left edge (not a
    # fixed ratio of canvas width guessed from a cropped reference image,
    # which can't be trusted for absolute scale) -- the reference shows
    # the text overlapping ~0.77x box-height PAST the icon's left edge.
    box_h_for_pn = by1 - by0
    target_right_edge = icon_x + 1.0 * box_h_for_pn
    target_w = target_right_edge - px0
    # Safety-shrink boundary matches this SAME target_right_edge, not the
    # badge box's own full right edge (bx1) -- the icon overlaps the
    # box's right portion, so bx1 sits well past where the icon actually
    # begins. Using bx1 here let long product names encroach visibly on
    # the icon before shrinking ever kicked in, confirmed on Composites.
    px1 = target_right_edge
    probe_size = 100
    probe_font = _font("kallisto", probe_size)
    probe_w = probe_font.getlength(product_name)
    pn_font_size = max(int(probe_size * target_w / probe_w), 10)
    # Cap the stretch -- a short single "word" with no spaces (no natural
    # break point to wrap or otherwise limit it) could otherwise stretch
    # to fill the full target width with no upper bound, producing an
    # oversized, overflowing result. Capped at the badge box's own
    # height, since product_name visually overflowing past the badge
    # text above it would look clearly disproportionate regardless of
    # what text produced it.
    pn_font_size = min(pn_font_size, int(box_h_for_pn))
    pn_font = _font("kallisto", pn_font_size)
    # Safety shrink -- longer product names still need to fit the zone
    # width rather than run off the canvas edge.
    while pn_font.getlength(product_name) > (px1 - px0) and pn_font_size > 10:
        pn_font_size -= 1
        pn_font = _font("kallisto", pn_font_size)

    # Wrap to a second line (max 2 lines, never more) once the name has
    # enough words that it reads as a long phrase rather than a short
    # product title. A computed-font-size signal (comparing the 1-line
    # result against a threshold, or against a 2-line alternative) proved
    # unreliable in testing: the stretch-to-fit size is confounded by
    # target_w and per-vertical icon position, so a "reasonable" nominal
    # size for one vertical can be too cramped for another, and splitting
    # into 2 lines almost always permits a bigger per-line size
    # regardless of whether 1 line was already fine. Word count is a
    # simpler, more direct proxy for "is this a long phrase" -- checked
    # against real examples: 2 and 4 words both read fine on one line,
    # 8 words does not. Character count added alongside it -- word count
    # alone misses a handful of genuinely long words (e.g. "Extraordinarily
    # Comprehensive Formulation" is only 3 words but 42 characters, and
    # reads just as cramped on one line as the 8-word case). Checked
    # against the same real examples: 37 characters ("Non-Flammable
    # Contact Adhesive Spray") still reads fine on one line, 42 does not.
    words = product_name.split()
    use_two_lines = False
    if len(words) >= 4 or len(product_name) >= 25:
        # Find the best 2-line split: the one whose longer line is
        # narrowest at probe_size, i.e. the most balanced split.
        best_split = None
        best_max_w = None
        for i in range(1, len(words)):
            line1, line2 = " ".join(words[:i]), " ".join(words[i:])
            w = max(probe_font.getlength(line1), probe_font.getlength(line2))
            if best_max_w is None or w < best_max_w:
                best_max_w = w
                best_split = (line1, line2)
        line1, line2 = best_split

        # Re-derive the font size for this 2-line arrangement the same
        # way as the single-line case -- stretch to fill target_w based
        # on the LONGER of the two lines, capped the same way, then
        # safety-shrunk to fit px1-px0 on both lines.
        probe_w_2line = max(probe_font.getlength(line1), probe_font.getlength(line2))
        pn_font_size_2line = max(int(probe_size * target_w / probe_w_2line), 10)
        pn_font_size_2line = min(pn_font_size_2line, int(box_h_for_pn * 0.62))
        pn_font_2line = _font("kallisto", pn_font_size_2line)
        while (pn_font_2line.getlength(line1) > (px1 - px0) or pn_font_2line.getlength(line2) > (px1 - px0)) and pn_font_size_2line > 10:
            pn_font_size_2line -= 1
            pn_font_2line = _font("kallisto", pn_font_size_2line)

        use_two_lines = True

    if use_two_lines:
        # Safety shrink: if this 2-line arrangement would visually reach
        # the bar below (checked against the bar's ACTUAL position, not
        # an assumed one), shrink both lines together until it clears --
        # same floor (10pt) as every other shrink-to-fit in this function.
        while True:
            line_gap = int(pn_font_size_2line * 0.08)
            bbox1 = pn_font_2line.getbbox(line1)
            bbox2 = pn_font_2line.getbbox(line2)
            line1_y = py0 - bbox1[1]
            line1_visible_bottom = line1_y + bbox1[3]
            line2_y = line1_visible_bottom + line_gap - bbox2[1]
            line2_visible_bottom = line2_y + bbox2[3]
            if line2_visible_bottom <= product_name_max_bottom or pn_font_size_2line <= 10:
                break
            pn_font_size_2line -= 1
            pn_font_2line = _font("kallisto", pn_font_size_2line)
        draw.text((px0, line1_y), line1, font=pn_font_2line, fill=COLOR_WHITE)
        draw.text((px0, line2_y), line2, font=pn_font_2line, fill=COLOR_WHITE)
    else:
        # Offset by the font's own internal top padding so the VISIBLE
        # glyph top lands exactly at py0, rather than py0 plus however
        # much empty space Kallisto reserves above the cap-height at
        # this size (that padding scales with font size, so it grew
        # along with the recent size increase -- without this
        # correction the gap to the box above keeps growing every time
        # the font gets bigger).
        # Same safety shrink as the 2-line case above, checked against
        # the bar's actual position.
        while True:
            pn_bbox = pn_font.getbbox(product_name)
            visible_bottom = py0 - pn_bbox[1] + pn_bbox[3]
            if visible_bottom <= product_name_max_bottom or pn_font_size <= 10:
                break
            pn_font_size -= 1
            pn_font = _font("kallisto", pn_font_size)
        draw.text((px0, py0 - pn_bbox[1]), product_name, font=pn_font, fill=COLOR_WHITE)

    # --- Orange bars + sales descriptions ---
    from layout_config import bar_box_zone_px
    if using_baked_background and dimension_group is not None:
        olx0, oly0, olx1, oly1 = bar_box_zone_px("orange_bar_left", vertical_name, dimension_group, W, H)
        orx0, ory0, orx1, ory1 = bar_box_zone_px("orange_bar_right", vertical_name, dimension_group, W, H)
    else:
        olx0, oly0, olx1, oly1 = zone_px("orange_bar_left", W, H)
        orx0, ory0, orx1, ory1 = zone_px("orange_bar_right", W, H)
    # Corner radius measured directly from the real .ai template (~10px
    # on a 2400x1800 canvas, i.e. ~0.0056*H) -- both the sales-description
    # bars and the grey content boxes below them use this same rounding.
    box_corner_radius = max(int(0.0056 * H), 1)
    draw.rounded_rectangle([olx0, oly0, olx1, oly1], radius=box_corner_radius, fill=accent_color)
    draw.rounded_rectangle([orx0, ory0, orx1, ory1], radius=box_corner_radius, fill=accent_color)

    def _fit_bar_text_size(text, bar_width, base_size, min_size_ratio=0.5):
        """Return the largest font size (not yet a font object) that fits
        this text within bar_width, without going below the safety floor."""
        size = base_size
        min_size = max(int(base_size * min_size_ratio), 1)
        font = _font("bold", size)
        while font.getlength(text) > bar_width and size > min_size:
            size -= 1
            font = _font("bold", size)
        return size

    bar_pad = 15 * supersample
    # Re-calibrated against real Industrial/Transportation/Construction
    # references (9.9-11pt text on 432-576pt canvases, ~0.019-0.023 of H)
    # -- the old 0.0392 ratio was measured from Marine specifically and
    # rendered roughly 2x too large everywhere else, per direct feedback.
    bar_base_size = int(0.022 * H)
    sales_description_1_caps = sales_description_1.upper()
    sales_description_2_caps = sales_description_2.upper()

    # If either bar's text is long enough to need shrinking below the
    # shared base size, shrink BOTH to that same smaller size together --
    # otherwise one bar ends up visibly smaller than the other, which is
    # exactly the mismatch being fixed here.
    size_1 = _fit_bar_text_size(sales_description_1_caps, (olx1 - olx0) - 2 * bar_pad, bar_base_size)
    size_2 = _fit_bar_text_size(sales_description_2_caps, (orx1 - orx0) - 2 * bar_pad, bar_base_size)
    shared_bar_size = min(size_1, size_2, bar_base_size)
    bar_font_1 = _font("bold", shared_bar_size)
    bar_font_2 = _font("bold", shared_bar_size)

    def _draw_centered_bar_text(text, font, bx0, by0, bx1, by1):
        # Use the font's ACTUAL rendered bounding box, not font.size --
        # this font renders visible glyphs at only ~78% of its nominal
        # size, so sizing the vertical centering off font.size pushes
        # the text off-true-center (allocating space for a taller glyph
        # than what's actually drawn).
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        tx = bx0 + ((bx1 - bx0) - text_w) / 2 - bbox[0]
        ty = by0 + ((by1 - by0) - text_h) / 2 - bbox[1]
        draw.text((tx, ty), text, font=font, fill=COLOR_WHITE)

    _draw_centered_bar_text(sales_description_1_caps, bar_font_1, olx0, oly0, olx1, oly1)
    _draw_centered_bar_text(sales_description_2_caps, bar_font_2, orx0, ory0, orx1, ory1)

    # --- Grey boxes ---
    if using_baked_background and dimension_group is not None:
        blx0, bly0, blx1, bly1 = bar_box_zone_px("box_left", vertical_name, dimension_group, W, H)
        brx0, bry0, brx1, bry1 = bar_box_zone_px("box_right", vertical_name, dimension_group, W, H)
    else:
        blx0, bly0, blx1, bly1 = zone_px("box_left", W, H)
        brx0, bry0, brx1, bry1 = zone_px("box_right", W, H)
    if not using_baked_background:
        draw.rounded_rectangle([blx0, bly0, blx1, bly1], radius=box_corner_radius, fill=COLOR_GREY_BOX)
        draw.rounded_rectangle([brx0, bry0, brx1, bry1], radius=box_corner_radius, fill=COLOR_GREY_BOX)

    header_font_size = int(0.026 * H)
    body_font_size = int(0.020 * H)
    pad = int(0.015 * W)
    max_w_left = (blx1 - blx0) - 2 * pad

    # Reserve a dedicated column for pictograms on the right side of
    # box_right, spanning its FULL height (not just where icons actually
    # sit) -- this guarantees text never overlaps the icons regardless of
    # how long the content runs, rather than only reserving space at a
    # fixed vertical position and having long text collide with it.
    pic_x0, pic_y0, pic_x1, pic_y1 = zone_px("pictograms", W, H)

    # Column/apex x-positions use the SAME spacing as the current 2-icon
    # layout (base_gap, unchanged) -- per feedback, size and spacing must
    # stay exactly proportionate to how the current two are. The NEW
    # icons added for 3/4/5 use a separate, much more compact offset
    # (touch_offset) so they overlap/touch like the reference images,
    # without needing the base icon size to shrink to fit.
    #
    # Uses the module-level _pictogram_positions() (defined near the top
    # of this file) rather than a local copy -- this function used to
    # have its own nested duplicate of that exact logic, which meant the
    # two-column layout (this function) and the compact layout
    # (render_compact_label) each had their own copy of the diamond/
    # triangle arrangement math with nothing keeping them in sync. They
    # happened to still match, but a future edit to one copy and not the
    # other would have silently made the two layouts inconsistent with
    # each other. Now there's exactly one definition both call, so that
    # can't happen.

    # The pictogram row can hold a variable number of icons depending on
    # the product's actual hazard classification (0, 1, 2, or more), so
    # the column reserved for them must scale with that count -- reserving
    # width for only one icon-width caused a 2-icon row to spill past the
    # reserved boundary and overlap the text column.
    pictogram_codes = sds_data.get("pictograms", []) if (category != "Tape" and sds_data) else []
    n_pics = len(pictogram_codes)
    pic_size_by_height = pic_y1 - pic_y0
    pic_size = pic_size_by_height  # ALWAYS the same size as the 2-icon case -- never shrunk
    base_gap = 5  # unchanged from the original 2-icon spacing
    # Compact touch/overlap offset for the icons ADDED beyond the base
    # two, sized so the diamond shapes actually touch/overlap like the
    # reference images without needing extra vertical room that isn't
    # there -- this is deliberately smaller than a full icon-width step.
    # The 3-icon arrangement is derived directly from the (already
    # correct) 4-icon diamond: take the bottom point out, and shift
    # everything else down so the two wings land exactly where the
    # standard 2-icon layout sits. That means this offset must match the
    # diamond's own wing offset (0.53x size) for the two shapes to be
    # visually consistent with each other, not an independently-measured
    # value.
    touch_offset = int(pic_size * 0.53)

    def _footprint_width(n, size, base_gap, touch_offset):
        if n <= 1:
            return size
        col_span = size + base_gap
        col_l, col_r, apex = -col_span / 2, col_span / 2, 0.0
        positions = _pictogram_positions(n, size, base_gap, touch_offset, col_l, col_r, apex, 0)
        xs = [p[0] for p in positions]
        return (max(xs) + size) - min(xs)

    footprint_w = _footprint_width(n_pics, pic_size, base_gap, touch_offset)

    # The Made-in-USA badge is sized independently of icon count and is
    # often WIDER than a single icon's footprint -- reserving text-column
    # width based only on the icon footprint (as before) left too little
    # room when there's just 1 icon, letting text creep right into where
    # the badge actually needs to sit. Reserve whichever is wider.
    reserved_w = footprint_w
    if category in ("Adhesive", "Sealant") and n_pics:
        usa_x0_check, _, usa_x1_check, _ = zone_px("made_in_usa", W, H)
        reserved_w = max(reserved_w, usa_x1_check - usa_x0_check)

    max_w_right = (brx1 - reserved_w - pad) - (brx0 + pad) if n_pics else (brx1 - pad) - (brx0 + pad)

    # LEFT BOX: Signal Word / Hazard Statements / Precautionary Statements
    # Skipped entirely for Tape -- no SDS exists for tape products.
    if category != "Tape" and sds_data:
        # Signal word must always display in ALL CAPS per GHS convention,
        # regardless of how the source SDS formatted it (some use "WARNING",
        # others "Warning") -- this is a presentation rule applied at
        # render time, not a change to what the parser extracted.
        signal_word = (sds_data.get("signal_word") or "N/A").upper()
        hazard_texts = [h["text"] for h in sds_data.get("hazard_statements", [])]
        # P4xx/P5xx always stripped (genuine duplication with the right
        # box's STORAGE/WASTE DISPOSAL, which comes from a different SDS
        # field entirely). P2xx/P3xx both stay in for now -- P3xx is only
        # conditionally dropped below, if this doesn't fit otherwise.
        space_safe_precautions = strip_redundant_precautions(sds_data.get("precautionary_statements", []))

        def _build_left_sections(precautions, add_note):
            secs = [
                Section("SIGNAL WORD", signal_word, kind="text"),
                Section("HAZARD STATEMENTS", hazard_texts, kind="bulleted", bullet=""),
                Section("PRECAUTIONARY STATEMENTS", [p["text"] for p in precautions], kind="bulleted"),
            ]
            if add_note:
                secs.append(Section(
                    "", "See SDS for additional precautionary information.",
                    kind="text", protected=True, body_color=COLOR_ORANGE,
                ))
            return secs

        if force_exclude_response:
            non_response, response = split_response_precautions(space_safe_precautions)
            left_sections = _build_left_sections(non_response, add_note=bool(response))
        else:
            left_sections = _build_left_sections(space_safe_precautions, add_note=False)
    elif category == "Tape":
        body_font = _font("regular", body_font_size)
        draw.text((blx0 + pad, bly0 + pad), "No SDS required for Tape products.",
                   font=body_font, fill=COLOR_DARK_TEXT)
    else:
        # category requires an SDS but sds_data is None -- genuinely
        # different situation from Tape (which never needs one at all),
        # so this needs its own message rather than reusing Tape's.
        # Wrapped (not a single draw.text line) since this message is
        # long enough to overflow the box width unwrapped.
        body_font = _font("regular", body_font_size)
        _draw_wrapped_text(draw, (blx0 + pad, bly0 + pad),
                            "SDS not yet parsed -- upload and parse an SDS above to see hazard information here.",
                            body_font, COLOR_DARK_TEXT, (blx1 - blx0) - 2 * pad)

    # RIGHT BOX: Directions for Use / Storage / Waste Disposal / Pictograms
    # (pictogram column already excluded from max_w_right above, so the
    # text box below can safely use the box's FULL height, bry0 to bry1)
    #
    # Everything now goes through ONE fit_and_draw_box call so header
    # sizing is consistent throughout the box (previously "DIRECTIONS FOR
    # USE" was drawn separately at a fixed size, which could end up
    # visibly larger than the other headers once they auto-shrunk).
    #
    # "FOR INDUSTRIAL USE ONLY" is fixed regulatory wording -- it does NOT
    # vary by vertical market, unlike the vertical-specific "FOR MARINE
    # USE ONLY" I used previously. It's sized like body text but stays
    # bold (via body_bold), and protected since it's required, fixed text.
    #
    # The old "APPLICATION INSTRUCTIONS" header is dropped entirely per
    # feedback -- it was redundant and not part of the original label,
    # and removing it frees up real vertical space. The bullets
    # themselves stay, just with no header line above them.
    remaining_sections = [
        Section("DIRECTIONS FOR USE", "FOR INDUSTRIAL USE ONLY", kind="text", protected=True, body_bold=True),
        Section("", tds_bullets_selected, kind="bulleted", protected=True),
    ]
    if category != "Tape" and sds_data:
        remaining_sections.append(Section("STORAGE", sds_data.get("storage") or "N/A", kind="text"))
        remaining_sections.append(Section("WASTE DISPOSAL", sds_data.get("disposal") or "N/A", kind="text", protected=True))

    dropped_content = {"left": [], "right": []}

    if category != "Tape" and sds_data:
        # Two-pass sync: measure each box's own required scale first (no
        # drawing), then draw both at whichever is smaller, so the two
        # boxes end up visually consistent instead of each independently
        # maximizing its own fit.
        left_scale, _, left_needed_fallback = fit_and_draw_box(
            None, (blx0, bly0, blx1, bly1), left_sections,
            header_font_size, body_font_size, max_w_left,
            fill_header=COLOR_ORANGE, measure_only=True,
        )
        if left_needed_fallback and not force_exclude_response:
            # Full (P2xx+P3xx) precautions didn't fit even at tightest
            # spacing/smallest font -- conditionally drop P3xx (Response)
            # as a space-saving fallback and re-measure. P2xx and hazard
            # statements are never touched regardless of space.
            non_response, response = split_response_precautions(space_safe_precautions)
            if response:
                left_sections = _build_left_sections(non_response, add_note=True)
                left_scale, _, _ = fit_and_draw_box(
                    None, (blx0, bly0, blx1, bly1), left_sections,
                    header_font_size, body_font_size, max_w_left,
                    fill_header=COLOR_ORANGE, measure_only=True,
                )
        right_scale, _, _ = fit_and_draw_box(
            None, (brx0, bry0, brx1, bry1), remaining_sections,
            header_font_size, body_font_size, max_w_right,
            fill_header=COLOR_ORANGE, measure_only=True,
        )
        shared_scale = min(left_scale, right_scale)

        _, left_truncated, dropped_content["left"] = fit_and_draw_box(
            draw, (blx0, bly0, blx1, bly1), left_sections,
            header_font_size, body_font_size, max_w_left,
            fill_header=COLOR_ORANGE, forced_scale=shared_scale,
        )
        _, right_truncated, dropped_content["right"] = fit_and_draw_box(
            draw, (brx0, bry0, brx1, bry1), remaining_sections,
            header_font_size, body_font_size, max_w_right,
            fill_header=COLOR_ORANGE, forced_scale=shared_scale,
        )
    else:
        _, right_truncated, dropped_content["right"] = fit_and_draw_box(
            draw, (brx0, bry0, brx1, bry1), remaining_sections,
            header_font_size, body_font_size, max_w_right,
            fill_header=COLOR_ORANGE,
        )

    # Center the pictogram row on the SAME fixed x-position the
    # Made-in-USA badge uses (zone_px("made_in_usa",...)), not a
    # content-dependent gap between the text column and the box edge --
    # that gap shifts with however much text ended up in max_w_right, so
    # pictograms would drift left/right relative to the badge depending on
    # content length even though both are meant to align with each other.
    usa_x0_fixed, _, usa_x1_fixed, _ = zone_px("made_in_usa", W, H)
    gap_center_x = (usa_x0_fixed + usa_x1_fixed) / 2

    if pictogram_codes:
        # pic_size already computed above (shared with the text-width
        # reservation so the two can never disagree with each other)
        col_span = pic_size + base_gap
        # Bug fix: col_l_x/col_r_x are PASTE positions (top-left corners),
        # so the two icons' combined VISUAL bounding box (left edge of the
        # left icon to right edge of the right icon) was landing centered
        # gap_center_x + pic_size/2 -- shifted right by half an icon width
        # from where the badge actually centers itself. Subtracting
        # pic_size/2 here centers the true bounding box on gap_center_x.
        row_center_x = gap_center_x - pic_size / 2
        col_l_x = row_center_x - col_span / 2
        col_r_x = row_center_x + col_span / 2
        # apex_x stays as the UNCORRECTED gap_center_x -- the top icon in
        # the 3-icon case must stay exactly where it already is; only the
        # bottom pair moves to the newly-corrected centered position.
        positions = _pictogram_positions(
            n_pics, pic_size, base_gap, touch_offset, col_l_x, col_r_x, gap_center_x, pic_y0
        )
        import os
        for code, (px, py) in zip(pictogram_codes, positions):
            candidates = [f for f in os.listdir(pictogram_dir) if f.startswith(code)]
            if not candidates:
                continue
            pic_img = Image.open(os.path.join(pictogram_dir, candidates[0])).convert("RGBA")
            pic_img = pic_img.resize((pic_size, pic_size))
            canvas.paste(pic_img, (int(px), int(py)), pic_img)

    # --- Made in USA badge + disclaimer, below the pictograms ---
    # Per feedback: required on Adhesive (BOND) and Sealant (SEAL) labels.
    # Fit within its own zone by whichever dimension (width or height) is
    # more constraining, so it can never overflow into the footer. Centered
    # under the pictogram row (same gap_center_x), not right-aligned.
    # Already baked into the background when using_baked_background --
    # it's always the same fixed image/text regardless of product, so
    # there's nothing dynamic here to redraw in that case.
    if category in ("Adhesive", "Sealant") and not using_baked_background:
        usa_x0, usa_y0, usa_x1, usa_y1 = zone_px("made_in_usa", W, H)
        usa_badge = Image.open("assets/made_in_usa_badge.png").convert("RGBA")
        avail_w, avail_h = usa_x1 - usa_x0, usa_y1 - usa_y0
        scale = min(avail_w / usa_badge.width, avail_h / usa_badge.height)
        badge_w, badge_h = int(usa_badge.width * scale), int(usa_badge.height * scale)
        usa_badge_resized = usa_badge.resize((badge_w, badge_h))
        usa_x = int(gap_center_x - badge_w / 2)
        # Clamp so the badge can never spill past the box edges -- when
        # very few icons are reserved (e.g. just 1), the gap they're
        # centered in narrows and shifts, and gap_center_x alone can push
        # the badge past brx1 before this safety check.
        usa_x = max(brx0 + pad, min(usa_x, brx1 - pad - badge_w))
        canvas.paste(usa_badge_resized, (usa_x, usa_y0), usa_badge_resized)

        # Exact two-line break, matching the real label word-for-word
        # (not auto-wrapped, which squeezed it to three cramped lines).
        disclaimer_font = _font("regular", int(0.011 * H))
        disclaimer_line_h = int(disclaimer_font.size * 1.2)
        disclaimer_lines = [
            "*Manufactured in the USA with domestic",
            "and limited foreign- sourced components.",
        ]
        disclaimer_y = usa_y0 + badge_h + int(0.006 * H)
        for line in disclaimer_lines:
            line_w = disclaimer_font.getlength(line)
            line_x = gap_center_x - line_w / 2
            line_x = max(brx0 + pad, min(line_x, brx1 - pad - line_w))
            draw.text((line_x, disclaimer_y), line, font=disclaimer_font, fill=COLOR_DARK_TEXT)
            disclaimer_y += disclaimer_line_h

    # --- Footer ---
    fx0, fy0, fx1, fy1 = zone_px("footer", W, H)
    # No flat fill here -- the background gradient already stretches the
    # full canvas height, so it should show through continuously into the
    # footer instead of getting cut off by a flat navy block. Text/logo
    # draw directly on top of it below.
    footer_font = _font("kallisto", int(0.018 * H))

    # Size label / product code+lot / address block all share the SAME
    # top y (measured directly: all sit within 393.4-394.8pt of a 432pt
    # page, i.e. y-fraction ~0.911) -- previously the address block was
    # vertically CENTERED in the footer band while these were top-anchored
    # at a fixed y, which put them at different heights. Now everything
    # anchors to this one shared y.
    footer_text_y = int(0.9110 * H)
    sl_x0, _, _, _ = zone_px("footer_size_label", W, H)
    draw.text((sl_x0, footer_text_y), size_label, font=footer_font, fill=COLOR_WHITE)
    if case_quantity:
        # Box Label case: an extra line directly below the size. Correct
        # verbiage is "Case Quantity:" for Cartridges and "QTY:" for
        # Sausages -- app.py builds the full display string with the
        # right label already attached, so this just draws it as-is.
        case_qty_y = footer_text_y + int(footer_font.size * 1.15)
        draw.text((sl_x0, case_qty_y), case_quantity, font=footer_font, fill=COLOR_WHITE)
    pc_x0, _, _, _ = zone_px("footer_product_code", W, H)
    label_number_display = internal_label_number if internal_label_number else product_code
    draw.text((pc_x0, footer_text_y), f"{label_number_display}    {lot_number}", font=footer_font, fill=COLOR_WHITE)

    # --- Forza logo + company address, bottom-right of the footer ---
    # Fixed content (same logo, same address, every label) -- already
    # baked into the background when using_baked_background, so skip
    # redrawing it in that case.
    if not using_baked_background:
        footer_logo = Image.open("assets/footer_logo.png").convert("RGBA")
        # (text, is_bold) -- per the real template: company name and website
        # are bold, the two address lines in between are regular weight.
        address_lines = [
            ("Forza Inc.", True),
            ("3211 Nebraska Ave, Suite 300,", False),
            ("Council Bluffs, IA 51501", False),
            ("www.forzabuilt.com", True),
        ]
        addr_size = int(0.0133 * H)
        addr_font_bold = _font("cotext_bold", addr_size)
        addr_font_regular = _font("cotext_light", addr_size)
        addr_line_h = int(addr_size * 1.08)
        addr_block_h = addr_line_h * len(address_lines)

        # Fixed left edge measured directly from the PDF text objects (x=486.65
        # of a 576pt page -> fraction 0.8449), cross-validated against a second
        # clean reference image -- this is reliable ground truth, not an
        # estimate. Verify it still fits within the canvas at current font
        # settings; only fall back to a computed position if it would overflow.
        addr_x0 = int(0.8449 * W)
        max_line_w = max(
            (addr_font_bold if bold else addr_font_regular).getlength(text)
            for text, bold in address_lines
        )
        right_margin = int(0.02 * W)
        if addr_x0 + max_line_w > W - right_margin:
            addr_x0 = int(W - right_margin - max_line_w)
        ay = footer_text_y

        # Logo height tied to the address block's height (measured ratio
        # ~0.93). Gap between the logo's right edge and the address block's
        # left edge measured directly at ~0.0094 of page width -- a much
        # tighter gap than previously used.
        logo_h = int(addr_block_h * 0.93)
        logo_ratio = logo_h / footer_logo.height
        logo_w = int(footer_logo.width * logo_ratio)
        footer_logo_resized = footer_logo.resize((logo_w, logo_h))
        gap_px = int(0.0094 * W)
        logo_x = addr_x0 - gap_px - logo_w
        logo_y = ay + (addr_block_h - logo_h) // 2  # vertically centered on the address block
        canvas.paste(footer_logo_resized, (logo_x, logo_y), footer_logo_resized)

        for text, bold in address_lines:
            font = addr_font_bold if bold else addr_font_regular
            draw.text((addr_x0, ay), text, font=font, fill=COLOR_WHITE)
            ay += addr_line_h

    final_w, final_h = round(w_in * dpi), round(h_in * dpi)
    canvas = canvas.resize((final_w, final_h), Image.LANCZOS)
    if output_path:
        canvas.save(output_path)
    return canvas, dropped_content


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from parse_sds import parse_sds
    from parse_tds import extract_product_application_bullets

    sds_data = parse_sds("/mnt/user-data/uploads/ForzaEagle_T-OS164_Transportation_Sealant_SDS_V1_08_11_2026.pdf")
    tds_bullets = extract_product_application_bullets("/mnt/user-data/uploads/FORZA_V2_M-C227_TDS_Marine_DrumAerosol_06_28_26.pdf")

    render_label(
        canvas_size_in=(8.25, 6.25),
        background_path="templates_incoming/LABEL TEMPLATES/Construction/Construction Background.png",
        vertical_name="Construction",
        category="Adhesive",
        sds_data=sds_data,
        tds_bullets_selected=tds_bullets,
        product_name="Contact Adhesive",
        sales_description_1="High Strength Contact Adhesive",
        sales_description_2="Directions for Use",
        product_code="C-C330",
        size_label="5 Gallon Pail",
        badge_icon_path="construction_badge_icon.png",
        output_path="test_render_construction.png",
    )
    print("Rendered test_render_construction.png")


def render_tape_label(
    *,
    canvas_size_in=(8, 4),   # Tape always uses this single canvas size,
                             # regardless of the tape product's own
                             # physical width/length -- confirmed across
                             # all 5 real reference labels measured.
    background_path,
    baked_background_path=None,
    vertical_name,           # e.g. "Industrial" -- determines the
                             # product-code text color (see
                             # TAPE_CODE_COLOR_BY_VERTICAL below)
    sds_data=None,           # None/empty is the common case for tape
                             # (most Forza tape products are non-hazardous)
    tds_bullets_selected,
    product_name,            # e.g. "High Bond Tape" -- below the badge,
                             # same 2-line-wrap behavior as the other layouts
    sales_description_1,     # left bar text (spans columns 1+2 combined)
    sales_description_2,     # right bar text (column 3 only)
    product_code,
    size_label,              # e.g. "3/4in x 108ft" -- tape's own format,
                             # NOT a product_type/dimension_group string
    case_quantity,           # ALWAYS shown for tape (no "Box Label?"
                             # toggle -- unlike Cartridge/Sausage, this is
                             # not conditional)
    internal_label_number=None,
    lot_number="LOT#",
    badge_icon_path=None,
    tds_storage_info=None,  # Storage text parsed from the TDS (tape has
                             # no SDS to pull Storage from) -- see
                             # parse_tds.extract_storage_info
    force_exclude_response=False,
    dpi=300,
    output_path=None,
):
    """Three-column layout used for all Tape products, confirmed
    structurally distinct from both the main two-column layout
    (Cartridge/Sausage/Pail/Drum) and the compact three-column layout
    (Aerosol/22L/108L Canister) via 5 real reference labels spanning
    Industrial, Marine, Construction, Insulation, and Transportation.

    Key structural differences from the other two layouts:
    - Bars are asymmetric: the left bar spans columns 1+2 combined width,
      the right bar covers column 3 alone -- not two equal-width bars.
    - Badge box shows ONLY the product code (no second "color" line --
      none of the 5 real references have one).
    - Product-code text color varies BY VERTICAL (navy/teal/orange/
      magenta/red), unlike the other layouts' fixed navy.
    - Middle box holds STORAGE, WASTE DISPOSAL, and CONTAINS together
      (ingredient/CAS list) -- a combination not used elsewhere.
    - Footer always shows Case Quantity (no Box Label toggle).
    """
    from layout_config import COLOR_ORANGE, COLOR_DARK_TEXT, COLOR_WHITE, COLOR_NAVY, COLOR_GREY_BOX

    # Exact RGB values measured directly from the 5 real reference PDFs'
    # Kallisto-Heavy product-code text spans -- not inferred from the
    # brand standards' industry *background* colors, which turned out to
    # differ from the actual code text color in several cases.
    TAPE_CODE_COLOR_BY_VERTICAL = {
        "Industrial": (13, 67, 105),
        "Marine": (17, 121, 118),
        "Construction": (241, 168, 79),
        "Insulation": (208, 21, 125),
        "Transportation": (184, 59, 53),
    }
    TAPE_BAR_COLOR = (209, 24, 31)  # Tape's category red, per brand standards -- always this color regardless of vertical

    # Badge box position measured directly per-vertical -- confirmed
    # these genuinely differ (Marine's real box is taller and starts
    # lower than Transportation's), so a single hardcoded position
    # doesn't work universally. Falls back to Transportation's
    # measurement for any vertical not yet individually measured.
    TAPE_BADGE_ZONE_BY_VERTICAL = {
        "Transportation": (380.8, 24.4, 504.7, 51.9),
        "Marine": (379.8, 30.4, 501.5, 64.2),
        "Insulation": (379.7, 28.8, 475.2, 62.4),
    }
    badge_zone = TAPE_BADGE_ZONE_BY_VERTICAL.get(vertical_name, TAPE_BADGE_ZONE_BY_VERTICAL["Transportation"])

    w_in, h_in = canvas_size_in
    supersample = 2
    W, H = round(w_in * dpi) * supersample, round(h_in * dpi) * supersample
    scale = W / 576.0  # measurements below are in pt at a 576x288 (8x4in @ 72dpi) reference

    def px(v):
        return v * scale

    canvas = Image.new("RGB", (W, H), COLOR_NAVY)
    draw = ImageDraw.Draw(canvas)

    using_baked_background = baked_background_path is not None
    if using_baked_background:
        bg = Image.open(baked_background_path).convert("RGBA")
        bg_resized = bg.resize((W, H))
        canvas.paste(bg_resized, (0, 0))
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
    else:
        bg = Image.open(background_path).convert("RGB").resize((W, H))
        canvas.paste(bg, (0, 0))
        draw = ImageDraw.Draw(canvas)

        # --- Forza TAPE logo (category lockup, per brand standards --
        # same logo regardless of vertical) -- position measured from
        # the real AP848 (Transportation) blank reference.
        from layout_config import CATEGORY_LOGO
        logo = Image.open(CATEGORY_LOGO["Tape"]).convert("RGBA")
        logo_target_w = px(160)
        logo_ratio = logo_target_w / logo.width
        logo_resized = logo.resize((int(logo.width * logo_ratio), int(logo.height * logo_ratio)))
        canvas.paste(logo_resized, (int(px(20)), int(px(10))), logo_resized)
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)

    # Grey boxes and bars drawn fresh regardless of using_baked_background
    # -- the raw Tape blanks (background art/logo/vertical-name/badge-box/
    # icon only) strip these out just like every other vertical's blanks
    # did, so they're not pre-baked here yet. Positions measured directly
    # from the real AP848 (Transportation) reference.
    for box in [(47.9, 94.1, 206.3, 244.9), (213.3, 94.1, 371.7, 244.9), (379.4, 94.1, 537.9, 244.9)]:
        x0, y0, x1, y1 = [px(v) for v in box]
        draw.rounded_rectangle([x0, y0, x1, y1], radius=int(0.01 * W), fill=COLOR_GREY_BOX)
    for box in [(47.4, 74.3, 371.5, 89.0), (379.5, 74.3, 538.0, 89.0)]:
        x0, y0, x1, y1 = [px(v) for v in box]
        draw.rounded_rectangle([x0, y0, x1, y1], radius=int(0.006 * W), fill=TAPE_BAR_COLOR)

    code_text_color = TAPE_CODE_COLOR_BY_VERTICAL.get(vertical_name, COLOR_NAVY)

    # --- Vertical name, badge box (code only, no color line), product name ---
    bx0, by0, bx1, by1 = [px(v) for v in badge_zone]
    if not using_baked_background:
        vx0, vy0 = px(380.6), px(7.3)
        draw.text((vx0, vy0), vertical_name, font=_font("kallisto", int(0.045 * H)), fill=COLOR_WHITE)
        draw.rounded_rectangle([bx0, by0, bx1, by1], radius=int(0.01 * W), fill=COLOR_WHITE)

        # --- Vertical icon (circular, overlapping the badge box's right
        # edge) -- drawn AFTER the badge box specifically so it overlaps
        # on top, matching the other two layouts' visual pattern; drawing
        # it before the box (as this used to) left it almost entirely
        # covered.
        if badge_icon_path:
            icon_size = int(px(60))
            icon = Image.open(badge_icon_path).convert("RGBA").resize((icon_size, icon_size))
            icon_x = int(px(501)) - icon_size // 2
            icon_y = int(px(20))
            canvas.paste(icon, (icon_x, icon_y), icon)
            draw = ImageDraw.Draw(canvas)

    box_h = by1 - by0
    code_font_size = int(box_h * 0.85)
    code_font = _font("kallisto", code_font_size)
    avail_code_w = (bx1 - bx0) * 0.92
    while code_font.getlength(product_code) > avail_code_w and code_font_size > 10:
        code_font_size -= 1
        code_font = _font("kallisto", code_font_size)
    code_bbox = code_font.getbbox(product_code)
    code_w = code_font.getlength(product_code)
    code_x = bx0 + ((bx1 - bx0) - code_w) / 2
    code_y = by0 + (box_h - (code_bbox[3] - code_bbox[1])) / 2 - code_bbox[1]
    draw.text((code_x, code_y), product_code, font=code_font, fill=code_text_color)

    # Product name below the badge -- same 2-line-wrap-at-5+-words
    # behavior as the other layouts, for consistency.
    pn_x0 = bx0
    pn_y0 = by1 + px(1.0)
    pn_target_w = (bx1 - bx0)
    probe_size = 100
    probe_font = _font("kallisto", probe_size)
    probe_w = probe_font.getlength(product_name)
    pn_font_size = max(int(probe_size * pn_target_w / probe_w), 10)
    # Cap by ACTUAL available space (gap to the bar below, which sits at
    # a fixed y regardless of this vertical's own badge box height) --
    # a fixed box_h ratio isn't safe here since box_h varies per vertical
    # (confirmed Marine's real box is taller than Transportation's),
    # which could push product_name down into the bar for any vertical
    # with a taller box than the one this ratio was tuned against.
    available_pn_h = px(74.3) - (by1 + px(1.0))
    pn_font_size = min(pn_font_size, int(box_h * 0.5), int(available_pn_h * 0.75))
    pn_font = _font("kallisto", pn_font_size)
    while pn_font.getlength(product_name) > pn_target_w and pn_font_size > 10:
        pn_font_size -= 1
        pn_font = _font("kallisto", pn_font_size)
    words = product_name.split()
    if len(words) >= 5 or len(product_name) >= 40:
        best_split, best_max_w = None, None
        for i in range(1, len(words)):
            l1, l2 = " ".join(words[:i]), " ".join(words[i:])
            w = max(probe_font.getlength(l1), probe_font.getlength(l2))
            if best_max_w is None or w < best_max_w:
                best_max_w, best_split = w, (l1, l2)
        l1, l2 = best_split
        probe_w_2 = max(probe_font.getlength(l1), probe_font.getlength(l2))
        pn_size_2 = max(int(probe_size * pn_target_w / probe_w_2), 10)
        pn_size_2 = min(pn_size_2, int(box_h * 0.32), int(available_pn_h * 0.75))
        pn_font_2 = _font("kallisto", pn_size_2)
        while (pn_font_2.getlength(l1) > pn_target_w or pn_font_2.getlength(l2) > pn_target_w) and pn_size_2 > 10:
            pn_size_2 -= 1
            pn_font_2 = _font("kallisto", pn_size_2)
        gap = int(pn_size_2 * 0.1)
        b1, b2 = pn_font_2.getbbox(l1), pn_font_2.getbbox(l2)
        y1_ = pn_y0 - b1[1]
        y2_ = y1_ + (b1[3] - b1[1]) + gap - b2[1]
        draw.text((pn_x0, y1_), l1, font=pn_font_2, fill=COLOR_WHITE)
        draw.text((pn_x0, y2_), l2, font=pn_font_2, fill=COLOR_WHITE)
    else:
        pn_bbox = pn_font.getbbox(product_name)
        draw.text((pn_x0, pn_y0 - pn_bbox[1]), product_name, font=pn_font, fill=COLOR_WHITE)

    # --- Bar text ---
    bar_font_size = int(0.0324 * H)
    bar_font = _font("bold", bar_font_size)
    for text, box in [(sales_description_1.upper(), (47.4, 74.3, 371.5, 89.0)), (sales_description_2.upper(), (379.5, 74.3, 538.0, 89.0))]:
        x0, y0, x1, y1 = [px(v) for v in box]
        f = bar_font
        fs = bar_font_size
        while f.getlength(text) > (x1 - x0) * 0.92 and fs > 8:
            fs -= 1
            f = _font("bold", fs)
        bbox = f.getbbox(text)
        tx = x0 + ((x1 - x0) - f.getlength(text)) / 2
        ty = y0 + ((y1 - y0) - (bbox[3] - bbox[1])) / 2 - bbox[1]
        draw.text((tx, ty), text, font=f, fill=COLOR_WHITE)

    # --- Three grey boxes ---
    header_font_size = int(0.028 * H)
    body_font_size = int(0.020 * H)
    pad = int(0.012 * W)

    hazard_texts = [h["text"] for h in (sds_data or {}).get("hazard_statements", [])] if sds_data else ["NON-HAZARDOUS"]
    signal_word = ((sds_data or {}).get("signal_word") or "NON-HAZARDOUS").upper() if sds_data else "NON-HAZARDOUS"
    space_safe_precautions = strip_redundant_precautions((sds_data or {}).get("precautionary_statements", [])) if sds_data else []
    precaution_texts_raw = space_safe_precautions or [{"text": "NON-HAZARDOUS", "code": "P000"}]

    def _build_left(precautions, add_note):
        secs = [
            Section("SIGNAL WORD", signal_word, kind="text"),
            Section("HAZARD STATEMENTS", hazard_texts if sds_data else ["NON-HAZARDOUS"], kind="bulleted", bullet=""),
            Section("PRECAUTIONARY STATEMENTS", [p["text"] for p in precautions], kind="bulleted"),
        ]
        if add_note:
            secs.append(Section("", "See SDS for additional precautionary information.", kind="text", protected=True, body_color=COLOR_ORANGE))
        return secs

    left_sections = _build_left(precaution_texts_raw, add_note=False)

    # Tape has no SDS to pull Storage/Disposal from. Storage comes from
    # the TDS instead (tds_storage_info, parsed separately since it's not
    # in the Product Application bullets). Disposal is always this fixed
    # boilerplate -- not conditional on sds_data, since tape genuinely
    # never has an SDS to override it with.
    storage_text = tds_storage_info or (sds_data or {}).get("storage") or "Keep it in the original container."
    disposal_text = "Dispose of waste materials in accordance with applicable local and national laws and regulations."
    ingredients = (sds_data or {}).get("ingredients") or [] if sds_data else []
    contains_lines = [f"{ing['chemical_name']}   CAS #: {ing['cas_number']}" for ing in ingredients] or ["NON-HAZARDOUS"]
    middle_sections = [
        Section("STORAGE", storage_text, kind="text"),
        Section("WASTE DISPOSAL", disposal_text, kind="text"),
        Section("CONTAINS", contains_lines, kind="bulleted", bullet=""),
    ]

    right_sections = [
        Section("DIRECTIONS FOR USE", "FOR INDUSTRIAL USE ONLY", kind="text", protected=True, body_bold=True),
        Section("", tds_bullets_selected, kind="bulleted", protected=True),
    ]
    if tds_bullets_selected:
        right_sections.append(Section("", "See technical data sheet for more information.", kind="text", protected=True))

    box_bounds = {
        "left": tuple(px(v) for v in (47.9, 94.1, 206.3, 244.9)),
        "middle": tuple(px(v) for v in (213.3, 94.1, 371.7, 244.9)),
        "right": tuple(px(v) for v in (379.4, 94.1, 537.9, 244.9)),
    }
    max_w = {
        "left": box_bounds["left"][2] - box_bounds["left"][0] - 2 * pad,
        "middle": box_bounds["middle"][2] - box_bounds["middle"][0] - 2 * pad,
        "right": box_bounds["right"][2] - box_bounds["right"][0] - 2 * pad,
    }

    left_scale, _, left_needed_fallback = fit_and_draw_box(
        None, box_bounds["left"], left_sections, header_font_size, body_font_size, max_w["left"],
        fill_header=COLOR_ORANGE, header_ratio_boost=1.4, gap_boost=1.5, measure_only=True,
    )
    if left_needed_fallback and not force_exclude_response:
        non_response, response = split_response_precautions(precaution_texts_raw) if sds_data else ([], [])
        if response:
            left_sections = _build_left(non_response, add_note=True)
            left_scale, _, _ = fit_and_draw_box(
                None, box_bounds["left"], left_sections, header_font_size, body_font_size, max_w["left"],
                fill_header=COLOR_ORANGE, header_ratio_boost=1.4, gap_boost=1.5, measure_only=True,
            )
    elif force_exclude_response and sds_data:
        non_response, response = split_response_precautions(precaution_texts_raw)
        left_sections = _build_left(non_response, add_note=bool(response))
        left_scale, _, _ = fit_and_draw_box(
            None, box_bounds["left"], left_sections, header_font_size, body_font_size, max_w["left"],
            fill_header=COLOR_ORANGE, header_ratio_boost=1.4, gap_boost=1.5, measure_only=True,
        )
    middle_scale, _, _ = fit_and_draw_box(
        None, box_bounds["middle"], middle_sections, header_font_size, body_font_size, max_w["middle"],
        fill_header=COLOR_ORANGE, header_ratio_boost=1.4, gap_boost=1.5, measure_only=True,
    )
    right_scale, _, _ = fit_and_draw_box(
        None, box_bounds["right"], right_sections, header_font_size, body_font_size, max_w["right"],
        fill_header=COLOR_ORANGE, header_ratio_boost=1.4, measure_only=True,
    )
    shared_scale = min(left_scale, middle_scale, right_scale)

    dropped_content = {"left": [], "middle": [], "right": []}
    _, _, dropped_content["left"] = fit_and_draw_box(
        draw, box_bounds["left"], left_sections, header_font_size, body_font_size, max_w["left"],
        fill_header=COLOR_ORANGE, header_ratio_boost=1.4, gap_boost=1.5, forced_scale=shared_scale,
    )
    _, _, dropped_content["middle"] = fit_and_draw_box(
        draw, box_bounds["middle"], middle_sections, header_font_size, body_font_size, max_w["middle"],
        fill_header=COLOR_ORANGE, header_ratio_boost=1.4, gap_boost=1.5, forced_scale=shared_scale,
    )
    _, _, dropped_content["right"] = fit_and_draw_box(
        draw, box_bounds["right"], right_sections, header_font_size, body_font_size, max_w["right"],
        fill_header=COLOR_ORANGE, forced_scale=shared_scale,
    )

    # --- Footer (SIZE/Case Quantity always shown -- no Box Label toggle
    # for tape, unlike Cartridge/Sausage) ---
    footer_font_size = int(0.018 * H)
    footer_font = _font("kallisto", footer_font_size)
    fy0 = px(250.0)
    draw.text((px(52.9), fy0), f"SIZE: {size_label}", font=footer_font, fill=COLOR_WHITE)
    draw.text((px(52.9), fy0 + footer_font_size * 1.15), f"Case Quantity: {case_quantity}", font=footer_font, fill=COLOR_WHITE)
    draw.text((px(217.1), fy0), lot_number, font=footer_font, fill=COLOR_WHITE)
    label_display = internal_label_number if internal_label_number else product_code
    draw.text((px(333.6), fy0), label_display, font=footer_font, fill=COLOR_WHITE)

    final_w, final_h = round(w_in * dpi), round(h_in * dpi)
    canvas = canvas.resize((final_w, final_h), Image.LANCZOS)
    if output_path:
        canvas.save(output_path)
    return canvas, dropped_content
