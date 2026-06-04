from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path("/Users/wangwei/project/ming-salvage-sim")
SRC = ROOT / "output/imagegen/steam-library"
OUT = ROOT / "web/public/steam-stock/generated"
OUT.mkdir(parents=True, exist_ok=True)

XINGKAI = Path(
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
    "13b8ce423f920875b28b551f9406bf1014e0a656.asset/AssetData/Xingkai.ttc"
)
PALATINO = Path("/System/Library/Fonts/Palatino.ttc")

GOLD = (246, 211, 104, 255)
LIGHT_GOLD = (255, 238, 160, 255)
DARK = (23, 9, 2, 255)
SHADOW = (0, 0, 0, 190)


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt, stroke_width=0)
    return box[2] - box[0], box[3] - box[1]


def fit_font(draw: ImageDraw.ImageDraw, text: str, path: Path, start: int, max_w: int) -> ImageFont.FreeTypeFont:
    size = start
    while size > 18:
        fnt = font(path, size)
        width, _ = text_size(draw, text, fnt)
        if width <= max_w:
            return fnt
        size = int(size * 0.94)
    return font(path, size)


def cover(src: Path, target: tuple[int, int], focus_y: float = 0.5) -> Image.Image:
    img = Image.open(src).convert("RGB")
    tw, th = target
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - tw) // 2)
    top = max(0, round((nh - th) * focus_y))
    return img.crop((left, top, left + tw, top + th))


def draw_gold_text(
    layer: Image.Image,
    xy: tuple[int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont,
    stroke: int,
) -> None:
    draw = ImageDraw.Draw(layer)
    x, y = xy
    draw.text((x + stroke, y + stroke), text, font=fnt, fill=SHADOW, stroke_width=stroke, stroke_fill=SHADOW)
    draw.text((x, y), text, font=fnt, fill=DARK, stroke_width=stroke + 2, stroke_fill=DARK)
    draw.text((x, y), text, font=fnt, fill=GOLD, stroke_width=max(1, stroke // 3), stroke_fill=LIGHT_GOLD)


def make_logo(lang: str, size: tuple[int, int] = (1280, 720)) -> Image.Image:
    w, h = size
    logo = Image.new("RGBA", size, (0, 0, 0, 0))
    scratch = ImageDraw.Draw(logo)

    if lang == "schinese":
        path = XINGKAI
        lines = [("明末", int(h * 0.36)), ("力挽狂澜", int(h * 0.22))]
        max_w = int(w * 0.82)
        gap = int(h * 0.035)
        strokes = [12, 8]
    else:
        path = PALATINO
        lines = [("Ming Dynasty", int(h * 0.24)), ("Last Stand", int(h * 0.18))]
        max_w = int(w * 0.86)
        gap = int(h * 0.03)
        strokes = [9, 7]

    fitted = [(text, fit_font(scratch, text, path, start, max_w)) for text, start in lines]
    sizes = [text_size(scratch, text, fnt) for text, fnt in fitted]
    total_h = sum(item[1] for item in sizes) + gap * (len(fitted) - 1)
    y = (h - total_h) // 2

    for idx, ((text, fnt), (tw, th)) in enumerate(zip(fitted, sizes)):
        x = (w - tw) // 2
        draw_gold_text(logo, (x, y), text, fnt, strokes[idx])
        y += th + gap

    glow = logo.filter(ImageFilter.GaussianBlur(radius=2))
    out = Image.alpha_composite(glow, logo)
    return out


def paste_logo(base: Image.Image, logo: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    x, y, max_w, max_h = box
    bbox = logo.getbbox()
    if not bbox:
        return base
    trimmed = logo.crop(bbox)
    scale = min(max_w / trimmed.width, max_h / trimmed.height)
    resized = trimmed.resize((round(trimmed.width * scale), round(trimmed.height * scale)), Image.Resampling.LANCZOS)
    canvas = base.convert("RGBA")
    canvas.alpha_composite(resized, (x + (max_w - resized.width) // 2, y + (max_h - resized.height) // 2))
    return canvas.convert("RGB")


def export() -> None:
    logos = {
        "schinese": make_logo("schinese"),
        "english": make_logo("english"),
    }

    for lang, logo in logos.items():
        logo.resize((1280, 720), Image.Resampling.LANCZOS).save(OUT / f"library_logo_{lang}.png")

    # Same no-text home background for both languages; Steam localization uses filenames.
    home = cover(SRC / "base_home.png", (3840, 1240), focus_y=0.45)
    home.save(OUT / "library_home_schinese.png")
    home.save(OUT / "library_home_english.png")

    for lang, logo in logos.items():
        capsule = cover(SRC / "base_capsule.png", (600, 900), focus_y=0.5)
        capsule = paste_logo(capsule, logo, (35, 620, 530, 210))
        capsule.save(OUT / f"library_capsule_{lang}.png")

        hero = cover(SRC / "base_hero.png", (920, 430), focus_y=0.42)
        hero = paste_logo(hero, logo, (35, 250, 470, 145))
        hero.save(OUT / f"library_hero_{lang}.png")

    print(f"Wrote Steam library assets to {OUT}")


if __name__ == "__main__":
    export()
