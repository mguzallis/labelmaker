"""4x2in two-column label (Dual Cartridge item label, small format).

Same look as the main two-column layout (render_label) but condensed to fit a
2in tall label: the left box carries Signal Word + Hazard Statements (no
precautionary statements -- a short "see SDS" line stands in), the right box
carries the selected Directions plus a one-paragraph Storage and Disposal.
Drawn fresh on the vertical's background art (no baked template needed), so it
works for every vertical.
"""
import os
import re

from PIL import Image, ImageDraw, ImageOps

from layout_config import (
    COLOR_NAVY, COLOR_GREY_BOX, COLOR_WHITE, COLOR_DARK_TEXT,
    CATEGORY_ACCENT_COLOR, CATEGORY_LOGO, VERTICAL_BADGE_TEXT_COLOR, DEFAULT_BADGE_TEXT_COLOR,
)
from label_renderer import _font, _apply_text_shadow, Section, fit_and_draw_box

SMALL_DIMENSION = (4, 2)
SEE_SDS_LINE = "See the SDS for precautionary statements and first aid."


def _first_sentences(text, n=1):
    text = re.sub(r"^\s*Product\s+(?=Dispose)", "", text or "", flags=re.I).strip()
    if not text:
        return ""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text) if p]
    return " ".join(parts[:n])


def _fit_image(path, box):
    img = Image.open(path).convert("RGBA")
    scale = min((box[2] - box[0]) / img.width, (box[3] - box[1]) / img.height)
    return img.resize((max(int(img.width * scale), 1), max(int(img.height * scale), 1)), Image.LANCZOS)


def render_small_label(
    *, canvas_size_in, background_path, vertical_name, category, sds_data,
    tds_bullets_selected, product_name, sales_description_1, sales_description_2,
    product_code, size_label, badge_color=None, badge_icon_path=None,
    internal_label_number=None, lot_number="LOT#", output_path=None, dpi=300,
    **_ignored,
):
    w_in, h_in = canvas_size_in
    W, H = 1200, 600   # fixed working grid (4x2 at 300dpi); resized at the end if dpi differs
    canvas = ImageOps.fit(Image.open(background_path).convert("RGB"), (W, H), Image.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    accent = CATEGORY_ACCENT_COLOR.get(category, CATEGORY_ACCENT_COLOR["Adhesive"])
    code_color = VERTICAL_BADGE_TEXT_COLOR.get(vertical_name, DEFAULT_BADGE_TEXT_COLOR)

    # ---- top: logo | vertical name + badge pill + product name
    logo = _fit_image(CATEGORY_LOGO[category], (0, 0, 410, 186))
    # Justified to the sides like the 6x4: the logo's visible left edge and the icon's right
    # edge sit the same distance from their label edges.
    SIDE = 80
    lbox = logo.getchannel("A").getbbox() or (0, 0, logo.width, logo.height)
    canvas.paste(logo, (SIDE - lbox[0], 14 + (186 - logo.height) // 2), logo)
    DX = (W - SIDE) - 1069     # puts the icon's right edge SIDE px from the label's right edge
    # Badge cluster: every dimension is the real 6x4 label's, scaled by 0.9 (measured off
    # the approved 6x4 R519 label) so the 4x2 keeps the same proportions -- vertical name
    # from the box's left edge to the icon, box ~13% tall with slightly rounded corners
    # running under the icon, icon ~1.7x the box height, product name left-aligned below.
    ICON = 159
    icon_x, icon_y = 910 + DX, 12
    px0, px1, py0, py1 = 588 + DX, 996 + DX, 68, 162
    vavail = icon_x - px0 - 6
    vsize = 100
    vf = _font("kallisto", vsize)
    vsize = min(int(vsize * vavail / vf.getlength(vertical_name)), 100, int(44 / 0.78))   # cap height <= ~44px
    vf = _font("kallisto", vsize)
    vbb = vf.getbbox(vertical_name)
    vy = py0 - 10 - (vbb[3] - vbb[1]) - vbb[1]
    items = [((px0, vy), vertical_name, vf)]
    # product name: one line, shrunk to fit under the box (reaches the icon's right edge)
    pn_avail = (icon_x + ICON) - px0
    psize = 32
    pf = _font("bold", psize)
    while pf.getlength(product_name or "") > pn_avail and psize > 18:
        psize -= 1
        pf = _font("bold", psize)
    pbb = pf.getbbox(product_name or "A")
    items.append(((px0, 174 - pbb[1]), product_name or "", pf))
    canvas = _apply_text_shadow(canvas, items, W, H)
    draw = ImageDraw.Draw(canvas)
    draw.text(items[0][0], vertical_name, font=vf, fill=COLOR_WHITE)
    for (xy, l, f) in items[1:]:
        draw.text(xy, l, font=f, fill=COLOR_WHITE)

    draw.rounded_rectangle((px0, py0, px1, py1), 10, fill=COLOR_WHITE)
    code_cx = (px0 + icon_x) // 2
    code_avail = (icon_x - px0) - 30
    size = 92 if not badge_color else 70
    cf = _font("kallisto", size)
    while cf.getlength(product_code) > code_avail and size > 18:
        size -= 1
        cf = _font("kallisto", size)
    if badge_color:
        sf = _font("kallisto", max(int(size * 0.42), 12))
        bb = cf.getbbox(product_code); sb = sf.getbbox(badge_color.upper())
        total = (bb[3] - bb[1]) + 6 + (sb[3] - sb[1])
        y0 = py0 + ((py1 - py0) - total) // 2
        draw.text((code_cx - cf.getlength(product_code) / 2, y0 - bb[1]), product_code, font=cf, fill=code_color)
        draw.text((code_cx - sf.getlength(badge_color.upper()) / 2, y0 + (bb[3] - bb[1]) + 6 - sb[1]),
                  badge_color.upper(), font=sf, fill=code_color)
    else:
        draw.text((code_cx, (py0 + py1) // 2), product_code, font=cf, fill=code_color, anchor="mm")
    if badge_icon_path and os.path.exists(badge_icon_path):
        icon = Image.open(badge_icon_path).convert("RGBA").resize((ICON, ICON), Image.LANCZOS)
        canvas.paste(icon, (icon_x, icon_y), icon)
        draw = ImageDraw.Draw(canvas)

    # ---- orange bars
    bar_f = _font("bold", 20)
    for (x0, x1, text) in ((12, 590, sales_description_1), (610, 1188, sales_description_2)):
        draw.rounded_rectangle((x0, 216, x1, 250), 6, fill=accent)
        t = (text or "").upper()
        s = 20
        f = bar_f
        while f.getlength(t) > (x1 - x0) - 24 and s > 12:
            s -= 1; f = _font("bold", s)
        draw.text(((x0 + x1) // 2, 233), t, font=f, fill=COLOR_WHITE, anchor="mm")

    # ---- grey boxes
    LB = (12, 258, 590, 520)
    RB = (610, 258, 1188, 520)
    for b in (LB, RB):
        draw.rounded_rectangle(b, 8, fill=COLOR_GREY_BOX)

    sds = sds_data or {}
    hazards = [h["text"] for h in sds.get("hazard_statements", []) if h.get("text")]
    left_sections = []
    if sds.get("signal_word"):
        left_sections.append(Section("SIGNAL WORD", sds["signal_word"].upper(), kind="text", protected=True))
    if hazards:
        left_sections.append(Section("HAZARD STATEMENTS", hazards, kind="bulleted", bullet="", protected=True))
    # Storage and Waste Disposal are required, so they get the full SDS text -- in the
    # left box, which has the room (the right box carries the directions).
    if sds.get("storage"):
        left_sections.append(Section("STORAGE", sds["storage"], kind="text", protected=True))
    disposal = re.sub(r"^\s*Product\s+(?=Dispose)", "", sds.get("disposal") or "", flags=re.I).strip()
    if disposal:
        left_sections.append(Section("WASTE DISPOSAL", disposal, kind="text", protected=True))
    left_sections.append(Section("", SEE_SDS_LINE, kind="text", body_bold=True, protected=True))

    right_sections = [
        Section("DIRECTIONS FOR USE", "FOR INDUSTRIAL USE ONLY", kind="text", protected=True, body_bold=True),
        Section("", tds_bullets_selected, kind="bulleted", protected=True),
    ]
    pics = list(sds.get("pictograms", []))
    pic_size = 70 if len(pics) <= 4 else 58
    has_usa = category in ("Adhesive", "Sealant")
    pic_col_w = 216 if (pics or has_usa) else 0   # wide enough for the two-line USA disclaimer
    hdr, body = int(0.027 * H), int(0.0225 * H)
    # same scale for both boxes, like the main layout
    ls, _, _ = fit_and_draw_box(None, LB, left_sections, hdr, body, LB[2] - LB[0] - 24,
                                fill_header=accent, min_scale=0.7, measure_only=True)
    rs, _, _ = fit_and_draw_box(None, RB, right_sections, hdr, body, RB[2] - RB[0] - pic_col_w - 24,
                                fill_header=accent, min_scale=0.7, measure_only=True)
    shared = min(ls, rs)
    _, _, dl = fit_and_draw_box(draw, LB, left_sections, hdr, body, LB[2] - LB[0] - 24,
                                fill_header=accent, min_scale=0.7, forced_scale=shared)
    _, _, dr = fit_and_draw_box(draw, RB, right_sections, hdr, body, RB[2] - RB[0] - pic_col_w - 24,
                                fill_header=accent, min_scale=0.7, forced_scale=shared)

    # ---- pictograms + Made in USA badge/disclaimer (right edge of right box)
    pdir = "pictograms"
    DIS = ["*Manufactured in the USA with domestic", "and limited foreign- sourced components."]
    dfont = _font("regular", 10)
    col_w = pic_col_w
    cx_mid = RB[2] - 10 - col_w / 2
    usa_top = RB[3] - 8
    if has_usa:
        dis_h = len(DIS) * 12
        usa = _fit_image("assets/made_in_usa_badge.png", (0, 0, 120, 56))
        usa_y = RB[3] - 8 - dis_h - 3 - usa.height
        canvas.paste(usa, (int(cx_mid - usa.width / 2), usa_y), usa)
        dy = usa_y + usa.height + 3
        for line in DIS:
            lw = dfont.getlength(line)
            draw.text((max(RB[0] + 8, min(cx_mid - lw / 2, RB[2] - 6 - lw)), dy), line, font=dfont, fill=COLOR_DARK_TEXT)
            dy += 12
        usa_top = usa_y
    rows_n = (len(pics) + 1) // 2
    block_h = rows_n * pic_size + max(rows_n - 1, 0) * 4
    y = max(usa_top - 8 - block_h, RB[1] + 6)   # sits just above the flag badge
    for i, code in enumerate(pics):
        cand = [f for f in os.listdir(pdir) if f.startswith(code)]
        if not cand:
            continue
        img = Image.open(os.path.join(pdir, cand[0])).convert("RGBA").resize((pic_size, pic_size), Image.LANCZOS)
        col, row = i % 2, i // 2
        n_in_row = 2 if (row + 1) * 2 <= len(pics) else len(pics) - row * 2
        row_w = n_in_row * pic_size + (n_in_row - 1) * 12
        canvas.paste(img, (int(cx_mid - row_w / 2 + col * (pic_size + 12)), y + row * (pic_size + 4)), img)

    # ---- footer
    ff = _font("kallisto", 22)
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 552), size_label, font=ff, fill=COLOR_WHITE)
    draw.text((330, 552), f"{internal_label_number or product_code}    {lot_number}", font=ff, fill=COLOR_WHITE)
    fl = _fit_image("assets/footer_logo.png", (860, 530, 1190, 596))
    canvas.paste(fl, (1190 - fl.width, 596 - fl.height), fl)

    final = (round(w_in * dpi), round(h_in * dpi))
    if final != (W, H):
        canvas = canvas.resize(final, Image.LANCZOS)
    if output_path:
        canvas.save(output_path)
    return canvas, {"left": dl, "right": dr}
