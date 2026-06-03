"""
Steam store assets generator.
- No badge, no dark panel
- Pure text logo with thick stroke for legibility over any background
- Small capsule: left art / right text, logo ~50% width
- All others: large centered text in lower third
"""

from PIL import Image, ImageDraw, ImageFont
import os

ASSETS = "/Users/wangwei/project/ming-salvage-sim/web/public/steam_assets"
OUT    = os.path.join(ASSETS, "output")
os.makedirs(OUT, exist_ok=True)

XINGKAI  = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/13b8ce423f920875b28b551f9406bf1014e0a656.asset/AssetData/Xingkai.ttc"
PALATINO = "/System/Library/Fonts/Palatino.ttc"

GOLD  = (255, 235, 130)
DGOLD = (255, 205,  55)
DARK  = ( 30,  10,   0)   # near-black stroke

def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def smart_crop(src, tw, th, focus_top=0.5):
    img = Image.open(src).convert("RGB")
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top  = int((nh - th) * focus_top)
    return img.crop((left, top, left + tw, top + th))

def stamp(draw, x, y, text, fnt, sw=7):
    """Gold text with dark stroke, no background."""
    draw.text((x, y), text, font=fnt, fill=DARK,
              stroke_width=sw, stroke_fill=DARK)
    draw.text((x, y), text, font=fnt, fill=GOLD)

def hline(draw, cx, y, half_w, color=(210, 170, 55), width=2):
    draw.line([(cx - half_w, y), (cx + half_w, y)], fill=color, width=width)

def text_size(draw, text, fnt):
    bb = draw.textbbox((0, 0), text, font=fnt)
    return bb[2] - bb[0], bb[3] - bb[1]

def fit_font(draw, text, path, start_size, max_w):
    sz = start_size
    while sz > 10:
        fnt = font(path, sz)
        w, _ = text_size(draw, text, fnt)
        if w <= max_w:
            return fnt
        sz = int(sz * 0.93)
    return font(path, sz)

# ─────────────────────────────────────────────────────────────────
# overlay_logo  —  used by main / header / vertical capsules
# Places "明末" large + "力挽狂澜" below, centered horizontally,
# vertically in the lower third.  No panel, no badge.
# ─────────────────────────────────────────────────────────────────
def overlay_logo(img, lang="cn"):
    W, H = img.size
    max_w = int(W * 0.82)

    if lang == "cn":
        path = XINGKAI
        t1, t2 = "明末", "力挽狂澜"
        sz1, sz2 = int(H * 0.30), int(H * 0.17)
    else:
        path = PALATINO
        t1, t2 = "Ming Dynasty", "Last Stand"
        sz1, sz2 = int(H * 0.22), int(H * 0.13)

    draw = ImageDraw.Draw(img)
    f1 = fit_font(draw, t1, path, sz1, max_w)
    f2 = fit_font(draw, t2, path, sz2, max_w)

    t1w, t1h = text_size(draw, t1, f1)
    t2w, t2h = text_size(draw, t2, f2)
    gap = int(H * 0.03)
    block_h = t1h + gap + t2h

    # bottom-third placement
    ty1 = H - block_h - int(H * 0.08)
    ty2 = ty1 + t1h + gap
    mid = W // 2
    lw  = max(t1w, t2w) // 2 + int(W * 0.03)

    stamp(draw, mid - t1w // 2, ty1, t1, f1, sw=8)
    stamp(draw, mid - t2w // 2, ty2, t2, f2, sw=6)

    return img

# ─────────────────────────────────────────────────────────────────
# make_small_capsule  —  left half art / right half pure text logo
# ─────────────────────────────────────────────────────────────────
def make_small_capsule(lang):
    W, H = 462, 174
    bg = smart_crop(os.path.join(ASSETS, "小宣传图.jpg"), W, H)
    draw = ImageDraw.Draw(bg)

    split = W // 2          # text lives in right half
    logo_w = W - split - 8  # available text width

    if lang == "schinese":
        path = XINGKAI
        t1, t2 = "明末", "力挽狂澜"
        sz1, sz2 = 68, 36
    else:
        path = PALATINO
        t1, t2 = "Ming Dynasty", "Last Stand"
        sz1, sz2 = 42, 28

    f1 = fit_font(draw, t1, path, sz1, logo_w)
    f2 = fit_font(draw, t2, path, sz2, logo_w)

    t1w, t1h = text_size(draw, t1, f1)
    t2w, t2h = text_size(draw, t2, f2)
    gap = 6
    block_h = t1h + gap + t2h
    ty1 = (H - block_h) // 2
    ty2 = ty1 + t1h + gap

    mid = split + logo_w // 2 + 4
    lw  = logo_w // 2 - 4

    stamp(draw, mid - t1w // 2, ty1, t1, f1, sw=5)
    stamp(draw, mid - t2w // 2, ty2, t2, f2, sw=3)

    fname = f"capsule_sm_{lang}.jpg"
    bg.save(os.path.join(OUT, fname), quality=95)
    print(f"✓ Small Capsule 462x174 {lang.upper()}")

# ─────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────
make_small_capsule("schinese")
make_small_capsule("english")

for lang in ("schinese", "english"):
    lcode = "cn" if lang == "schinese" else "en"

    img = smart_crop(os.path.join(ASSETS, "主宣传图.jpg"), 1232, 706, focus_top=0.3)
    overlay_logo(img, lcode).save(os.path.join(OUT, f"capsule_main_{lang}.jpg"), quality=95)
    print(f"✓ Main Capsule 1232x706 {lang}")

    img = smart_crop(os.path.join(ASSETS, "形象图.jpg"), 920, 430, focus_top=0.4)
    overlay_logo(img, lcode).save(os.path.join(OUT, f"header_{lang}.jpg"), quality=95)
    print(f"✓ Header Capsule 920x430 {lang}")

    img = smart_crop(os.path.join(ASSETS, "竖向宣传图.jpg"), 748, 896, focus_top=0.2)
    overlay_logo(img, lcode).save(os.path.join(OUT, f"portrait_{lang}.jpg"), quality=95)
    print(f"✓ Vertical Capsule 748x896 {lang}")

print(f"\nDone -> {OUT}/")
