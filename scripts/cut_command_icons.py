#!/usr/bin/env python3
"""切底部 5 命令物件透明图为独立 PNG（按 alpha 列空隙分割 + 裁紧包围盒）。"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

SRC = Path("web/public/ui/exact/auto-code-image-11687.png")
OUT = Path("web/public/ui/exact/cmd")
NAMES = ["奏疏", "邸报", "密令", "史册", "拟诏"]  # 左→右
ALPHA_T = 16   # alpha 阈值，> 视为有内容
MIN_GAP = 30   # 列空隙 >= 此宽视为物件分界
PAD = 6        # 裁紧后留边像素

def main():
    im = Image.open(SRC).convert("RGBA")
    a = np.array(im)[:, :, 3]
    H, W = a.shape
    col_has = (a > ALPHA_T).any(axis=0)  # 每列是否有内容

    # 找连续有内容的列段（物件）
    segs = []
    start = None
    gap = 0
    for x in range(W):
        if col_has[x]:
            if start is None:
                start = x
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap >= MIN_GAP:
                    segs.append((start, x - gap + 1))
                    start = None
                    gap = 0
    if start is not None:
        segs.append((start, W))

    print(f"源 {W}x{H}，找到 {len(segs)} 个物件列段：")
    for i, (x0, x1) in enumerate(segs):
        print(f"  [{i}] x {x0}..{x1} 宽{x1-x0}")

    if len(segs) != len(NAMES):
        print(f"!! 物件数 {len(segs)} != 预期 {len(NAMES)}。调 MIN_GAP/ALPHA_T。", file=sys.stderr)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    for (x0, x1), name in zip(segs, NAMES):
        # 该列段内裁紧上下
        sub = a[:, x0:x1]
        rows = np.where((sub > ALPHA_T).any(axis=1))[0]
        y0, y1 = rows[0], rows[-1] + 1
        bx0 = max(0, x0 - PAD); bx1 = min(W, x1 + PAD)
        by0 = max(0, y0 - PAD); by1 = min(H, y1 + PAD)
        crop = im.crop((bx0, by0, bx1, by1))
        dst = OUT / f"{name}.png"
        crop.save(dst)
        print(f"  -> {dst}  {crop.width}x{crop.height}")

if __name__ == "__main__":
    main()
