"""把 44 头像大图切割为 44 张独立 PNG（圆形浅灰背景 + 黑白线条）。

用法：
    python scripts/slice_persona_avatars.py

输入：
    assets/notion_avatars_44.png  （或从 -i 指定）
输出：
    web/public/avatars/p01.png … p44.png  （每张 200×200，透明圆形蒙版）

设计：
    - 原图 1024×1024，6 行布局，每行中心 y=[87, 252, 417, 582, 747, 912]
    - 前 5 行 8 头像（中心 x=[64, 192, 320, 448, 576, 704, 832, 960]）
    - 第 6 行 4 头像居中（中心 x=[320, 448, 576, 704]）
    - 每张头像裁剪 110×110 → 放大到 200×200 后做圆形透明蒙版
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROW_CENTERS_Y = [87, 252, 417, 582, 747, 912]
COLS_FULL_X = [64, 192, 320, 448, 576, 704, 832, 960]
COLS_LAST_X = [320, 448, 576, 704]
CROP_HALF = 55
OUT_SIZE = 200


def build_mapping() -> list[tuple[int, int, int]]:
    """返回 [(idx_1based, x_center, y_center), ...] 共 44 项。"""
    mapping: list[tuple[int, int, int]] = []
    idx = 1
    for row_i in range(5):
        for cx in COLS_FULL_X:
            mapping.append((idx, cx, ROW_CENTERS_Y[row_i]))
            idx += 1
    for cx in COLS_LAST_X:
        mapping.append((idx, cx, ROW_CENTERS_Y[5]))
        idx += 1
    assert idx == 45, f"应该刚好生成 44 个，got idx={idx - 1}"
    return mapping


def round_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input",
        default=r"assets\notion_avatars_44.png",
        help="44 头像大图路径",
    )
    parser.add_argument(
        "-o", "--out-dir",
        default=r"web\public\avatars",
        help="输出目录",
    )
    args = parser.parse_args()

    src_path = Path(args.input)
    if not src_path.exists():
        raise SystemExit(f"找不到输入图: {src_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(src_path).convert("RGBA")
    mapping = build_mapping()
    mask = round_mask(OUT_SIZE)

    for idx, cx, cy in mapping:
        bbox = (cx - CROP_HALF, cy - CROP_HALF, cx + CROP_HALF, cy + CROP_HALF)
        crop = img.crop(bbox)
        crop = crop.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
        canvas = Image.new("RGBA", (OUT_SIZE, OUT_SIZE), (0, 0, 0, 0))
        canvas.paste(crop, (0, 0), mask)
        out_path = out_dir / f"p{idx:02d}.png"
        canvas.save(out_path, format="PNG", optimize=True)
        print(f"  saved {out_path}  ({bbox})")

    print(f"DONE: 44 个头像 → {out_dir.resolve()}")


if __name__ == "__main__":
    main()
