# -*- coding: utf-8 -*-
"""调色板加载与档位推导。

调色板来源优先级：
    1. 调用方显式传入的 palette.json 路径；
    2. 工具内置的 ``data/palette.json``（随工具分发，保证自包含、离线可用）。

内置调色板与 ``mengshi-art-workflow/assets/palette/palette.json`` 内容相同，
两套灰阶来自美术规格契约（AGENTS.md §2.4）：

    角色套 8 档  #0F0F0F #232323 #3A3A3A #565656 #787878 #9E9E9E #CACACA #F2F2F2
    场景套 7 档  #000000 #282828 #5F5F5F #919191 #B9B9B9 #DCDCDC #FFFFFF
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

#: 工具自带的调色板文件
BUILTIN_PALETTE = Path(__file__).resolve().parent.parent / "data" / "palette.json"

#: 支持的资产类型（= 调色板键名）
KINDS = ("character", "scene")


def load_palette(path: str | Path | None = None) -> dict:
    """读取调色板 JSON。``path`` 为空时用内置调色板。"""
    p = Path(path) if path else BUILTIN_PALETTE
    if not p.exists():
        raise FileNotFoundError(f"找不到调色板文件：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    """``#RRGGBB`` -> ``(r, g, b)``。"""
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(c: Iterable[int]) -> str:
    r, g, b = c
    return f"#{r:02X}{g:02X}{b:02X}"


def gray_hex(pal: dict, kind: str) -> list[str]:
    """取某套灰阶的 hex 列表（大写）。"""
    if kind not in pal.get("gray", {}):
        raise KeyError(f"调色板里没有灰阶套：{kind!r}（可用：{list(pal.get('gray', {}))}）")
    return [h.upper() for h in pal["gray"][kind]["hex"]]


def gray_rgb(pal: dict, kind: str) -> list[tuple[int, int, int]]:
    """取某套灰阶的 RGB 列表。"""
    return [hex_to_rgb(h) for h in gray_hex(pal, kind)]


def narrow_palette(palette: list[tuple[int, int, int]], levels: int) -> list[tuple[int, int, int]]:
    """在给定调色板内**等距抽 N 档**（与 ``pixelize_oe.py --levels`` 完全一致）。

    ``levels`` 为 0 或 >= 调色板长度时原样返回。
    角色 8 档抽 4 档 -> 索引 ``linspace(0, 7, 4).round() = [0, 2, 5, 7]``
    -> ``#0F0F0F #3A3A3A #9E9E9E #F2F2F2``。
    """
    n = len(palette)
    if levels <= 0 or levels >= n:
        return list(palette)
    import numpy as np

    idx = np.linspace(0, n - 1, levels).round().astype(int)
    return [palette[int(i)] for i in idx]


def posterize_steps(levels: int, mode: str = "ps", palette: list[tuple[int, int, int]] | None = None) -> list[int]:
    """色调分离用的**档位值**（0-255 的灰度）。

    ``mode="ps"``（默认）—— Photoshop「色调分离」的原始算法：全范围等距分档，
        档位 = ``round(i * 255/(N-1))``；N=4 -> ``0 / 85 / 170 / 255``。
    ``mode="palette"`` —— 在调色板 min~max 之间等距重采样（旧行为，
        产出不含纯黑/纯白，仍落在项目灰阶范围内）。

    ``levels<=0`` 时若给了 ``palette``，直接返回调色板灰阶值。
    """
    if levels and mode == "ps":
        step = 255.0 / (levels - 1)
        return [int(round(i * step)) for i in range(levels)]
    if palette is None:
        palette = gray_rgb(load_palette(), "character")
    vals = [int(c[0]) for c in palette]  # 灰阶三通道等值，取 R 即可
    if levels and levels != len(vals):
        lo, hi = min(vals), max(vals)
        vals = [round(lo + (hi - lo) * i / (levels - 1)) for i in range(levels)]
    return sorted(set(int(v) for v in vals))
