#!/usr/bin/env python3
"""抠白底并压缩 web/public/portraits/ 立绘，原图备份后原地覆盖。

默认处理全部 PNG：白/近白背景转透明，长边缩到 512px，PNG optimize。
可重跑；首次运行会把原图复制到 web/public/portraits/_original_before_cutout/。
"""
from __future__ import annotations

import argparse
from collections import deque
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path.cwd() if (Path.cwd() / "web" / "public" / "portraits").exists() else Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "portraits"
BACKUP = OUT / "_original_before_cutout"


def alpha_for_pixel(r: int, g: int, b: int, threshold: int, soft: int) -> int:
    # Distance from white in Chebyshev space. White/near-white becomes transparent;
    # farther colors become opaque with a soft transition to avoid jagged outlines.
    d = max(255 - r, 255 - g, 255 - b)
    if d <= threshold:
        return 0
    if d >= threshold + soft:
        return 255
    return round(255 * (d - threshold) / soft)


def is_bg(r: int, g: int, b: int, threshold: int) -> bool:
    return max(255 - r, 255 - g, 255 - b) <= threshold


def cutout_white(im: Image.Image, threshold: int, soft: int) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    pix = im.load()
    bg = set()
    q = deque()

    def push(x: int, y: int) -> None:
        if (x, y) in bg:
            return
        r, g, b, a = pix[x, y]
        if a == 0 or is_bg(r, g, b, threshold):
            bg.add((x, y))
            q.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                push(nx, ny)

    # Soften only pixels adjacent to connected background; do not remove internal whites.
    edge_pixels = {}
    for x, y in bg:
        pix[x, y] = (*pix[x, y][:3], 0)
        for nx in range(max(0, x - 1), min(w, x + 2)):
            for ny in range(max(0, y - 1), min(h, y + 2)):
                if (nx, ny) not in bg:
                    r, g, b, a = pix[nx, ny]
                    edge_alpha = alpha_for_pixel(r, g, b, threshold, soft)
                    if edge_alpha < a:
                        edge_pixels[(nx, ny)] = min(edge_pixels.get((nx, ny), a), edge_alpha)
    for (x, y), a in edge_pixels.items():
        r, g, b, old_a = pix[x, y]
        pix[x, y] = (r, g, b, max(32, a))
    return im


def resize_to_max(im: Image.Image, size: int) -> Image.Image:
    w, h = im.size
    scale = size / max(w, h)
    if scale >= 1:
        return im
    return im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=512, help="输出长边像素")
    ap.add_argument("--threshold", type=int, default=14, help="离纯白多近时视为背景")
    ap.add_argument("--soft", type=int, default=42, help="边缘透明过渡宽度")
    ap.add_argument("--only", default="", help="只处理文件名包含此文本的 PNG")
    ap.add_argument("--only-list", help="逐行列出要处理的 PNG 文件名")
    ap.add_argument("--all", action="store_true", help="处理全部 PNG")
    ap.add_argument("--dry", action="store_true", help="只打印计划，不写入")
    args = ap.parse_args()

    if args.only_list:
        wanted = {x.strip() for x in Path(args.only_list).read_text("utf-8").splitlines() if x.strip()}
        files = sorted(OUT / name for name in wanted)
    elif args.only:
        files = sorted(p for p in OUT.glob("*.png") if args.only in p.name)
    elif args.all:
        files = sorted(OUT.glob("*.png"))
    else:
        raise SystemExit("请指定 --only-list、--only 或 --all，避免误处理全目录。")
    if not files:
        raise SystemExit("未找到匹配 PNG")
    missing = [p.name for p in files if not p.exists()]
    if missing:
        raise SystemExit(f"缺少文件：{missing}")

    if not args.dry:
        BACKUP.mkdir(parents=True, exist_ok=True)

    before_total = after_total = 0
    for path in files:
        before = path.stat().st_size
        before_total += before
        with Image.open(path) as src:
            w, h = src.size
            im = resize_to_max(cutout_white(src, args.threshold, args.soft), args.size)
            nw, nh = im.size

            if args.dry:
                print(f"{path.name:34} {w}x{h} {before//1024}KB -> {nw}x{nh} cutout")
                continue

            backup = BACKUP / path.name
            if not backup.exists():
                shutil.copy2(path, backup)
            im.save(path, format="PNG", optimize=True)

        after = path.stat().st_size
        after_total += after
        pct = 0 if before == 0 else round(100 * (before - after) / before)
        print(f"{path.name:34} {w}x{h} {before//1024}KB -> {nw}x{nh} {after//1024}KB  -{pct}%")

    if not args.dry:
        print(f"\n总计：{before_total//1024//1024}MB -> {after_total//1024//1024}MB")


if __name__ == "__main__":
    main()
