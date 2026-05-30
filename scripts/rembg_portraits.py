#!/usr/bin/env python3
"""Use rembg to cut out character subjects for selected portrait PNG files.

The script restores each selected file from _original_before_cutout when present,
then runs rembg subject segmentation and resizes the result to a 512px long edge.
It intentionally requires --only-list or --only to avoid touching old portraits.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from PIL import Image
from rembg import new_session, remove

ROOT = Path.cwd() if (Path.cwd() / "web" / "public" / "portraits").exists() else Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "portraits"
BACKUP = OUT / "_original_before_cutout"


def selected_files(only_list: str | None, only: str) -> list[Path]:
    if only_list:
        wanted = [x.strip() for x in Path(only_list).read_text("utf-8").splitlines() if x.strip()]
        files = [OUT / name for name in wanted]
    elif only:
        files = sorted(p for p in OUT.glob("*.png") if only in p.name)
    else:
        raise SystemExit("请指定 --only-list 或 --only，避免误处理旧图。")
    missing = [p.name for p in files if not p.exists() and not (BACKUP / p.name).exists()]
    if missing:
        raise SystemExit(f"缺少文件：{missing}")
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-list", help="逐行列出要处理的 PNG 文件名")
    ap.add_argument("--only", default="", help="只处理文件名包含此文本的 PNG")
    ap.add_argument("--size", type=int, default=512, help="输出长边像素")
    ap.add_argument("--model", default="isnet-general-use", help="rembg model/session name")
    ap.add_argument("--no-alpha-matting", action="store_true")
    args = ap.parse_args()

    files = selected_files(args.only_list, args.only)
    session = new_session(args.model)

    for idx, dst in enumerate(files, start=1):
        src = BACKUP / dst.name if (BACKUP / dst.name).exists() else dst
        if src != dst:
            shutil.copy2(src, dst)
        with Image.open(src) as im:
            result = remove(
                im,
                session=session,
                alpha_matting=not args.no_alpha_matting,
                alpha_matting_foreground_threshold=240,
                alpha_matting_background_threshold=10,
                alpha_matting_erode_size=10,
            ).convert("RGBA")
            result.thumbnail((args.size, args.size), Image.LANCZOS)
            result.save(dst, format="PNG", optimize=True)
        with Image.open(dst) as check:
            alpha = check.convert("RGBA").split()[-1]
            print(f"[{idx:02d}/{len(files)}] {dst.name} {check.size} alpha={alpha.getextrema()} {dst.stat().st_size//1024}KB")


if __name__ == "__main__":
    main()
