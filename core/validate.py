# -*- coding: utf-8 -*-
"""交付验收 —— 复刻 ``mengshi-art-workflow/scripts/validate_asset.py`` 的机械硬性检查。

对应 AGENTS.md §6.1，共 4 项：

===== ============= ==========================================================
名称    含义          判定
===== ============= ==========================================================
canvas  画布尺寸      输出尺寸 == 期望画布（给了 ``canvas`` 时才检查）
alpha   alpha 二值    所有 alpha ∈ {0,255}（无软边/半透明）
palette 调色板        所有不透明像素的颜色都落在「灰阶套 ∪ 登记强调色」内，越界数须为 0
hardness 平涂纯色     非灰阶色像素必须是登记过的平涂纯色（不得出现未登记的过渡色）
===== ============= ==========================================================

本工具产出的是 RGB（背景为平坦白），因此 ``alpha`` 恒为 PASS；
保留这一项是为了与产线验收口径一致、输出可对照。
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .palette import gray_rgb, hex_to_rgb, rgb_to_hex

#: 判定「灰阶」的容差（与 validate_asset.py 相同：三通道极差 <= 8）
GRAY_TOLERANCE = 8


def is_gray(c: tuple[int, int, int]) -> bool:
    return max(c) - min(c) <= GRAY_TOLERANCE


def validate(
    arr: np.ndarray,
    kind: str,
    palette: dict,
    canvas: str | None = None,
    extra_colors: list[str] | None = None,
    enforce_accent_ratio: bool = False,
) -> dict:
    """对成品 RGB 图做验收，返回结构化结果。

    ``arr`` 为 HxWx3（或 HxWx4）uint8。
    """
    extra_hex = [c.strip().upper() for c in (extra_colors or []) if c and c.strip()]
    extra_rgb = {hex_to_rgb(h) for h in extra_hex}
    gray_hex = [h.upper() for h in palette["gray"][kind]["hex"]]
    gray_set = {hex_to_rgb(h) for h in gray_hex}
    ref = palette.get("accent", {}).get("area_ratio_reference_range", [0.001, 0.05])

    a = np.asarray(arr)
    h, w = a.shape[0], a.shape[1]
    if a.ndim == 3 and a.shape[2] == 4:
        alpha = a[:, :, 3]
        rgb = a[:, :, :3]
    else:
        alpha = np.full((h, w), 255, dtype=np.uint8)
        rgb = a[:, :, :3]

    opaque = alpha == 255
    n_total = h * w
    n_opaque = int(opaque.sum())

    checks: list[dict] = []

    # 1) canvas
    if canvas:
        try:
            cw, ch = (int(v) for v in canvas.lower().split("x"))
            checks.append(
                {
                    "name": "canvas",
                    "label": "尺寸符合画布",
                    "pass": (w, h) == (cw, ch),
                    "detail": f"实际 {w}x{h}，要求 {cw}x{ch}",
                }
            )
        except Exception:
            checks.append(
                {"name": "canvas", "label": "尺寸符合画布", "pass": False, "detail": f"画布格式无法解析：{canvas!r}"}
            )

    # 2) alpha 二值
    soft = int(((alpha != 0) & (alpha != 255)).sum())
    alpha_vals = sorted(set(np.unique(alpha).tolist()))
    checks.append(
        {
            "name": "alpha",
            "label": "边缘无半透明",
            "pass": soft == 0,
            "detail": f"半透明像素={soft}（alpha 取值 {alpha_vals}）",
        }
    )

    # 3) palette
    flat = rgb[opaque][:, :3]
    colors = Counter(map(tuple, flat.tolist()))
    allowed = set(gray_set) | extra_rgb
    out_of_palette = {c: n for c, n in colors.items() if c not in allowed}
    checks.append(
        {
            "name": "palette",
            "label": "用色都在灰阶内",
            "pass": len(out_of_palette) == 0,
            "detail": f"灰阶之外的用色有 {len(out_of_palette)} 种"
            + (
                "，top=" + str([(rgb_to_hex(c), n) for c, n in sorted(out_of_palette.items(), key=lambda kv: -kv[1])[:10]])
                if out_of_palette
                else ""
            ),
        }
    )

    # 4) hardness
    accent_counter = Counter({c: n for c, n in colors.items() if not is_gray(c)})
    unregistered = {c: n for c, n in accent_counter.items() if c not in extra_rgb}
    accent_px = sum(accent_counter.values())
    accent_ratio = accent_px / n_opaque if n_opaque else 0.0
    checks.append(
        {
            "name": "hardness",
            "label": "无杂色",
            "pass": len(unregistered) == 0,
            "detail": f"杂色有 {len(unregistered)} 种"
            + (" " + str([rgb_to_hex(c) for c in unregistered]) if unregistered else ""),
        }
    )

    if enforce_accent_ratio:
        lo, hi = ref
        ok = (accent_px == 0) or (lo <= accent_ratio <= hi)
        checks.append(
            {
                "name": "accent-ratio",
                "label": "强调色占比",
                "pass": ok,
                "detail": f"{accent_ratio * 100:.3f}%（参考区间 {lo * 100:.2f}–{hi * 100:.2f}%）",
            }
        )

    unique_sorted = [
        {"hex": rgb_to_hex(c), "rgb": list(c), "px": n, "ratio": n / n_opaque if n_opaque else 0.0, "gray": is_gray(c)}
        for c, n in colors.most_common()
    ]

    return {
        "pass": all(c["pass"] for c in checks),
        "checks": checks,
        "details": {
            "size": [w, h],
            "opaque_pixels": n_opaque,
            "total_pixels": n_total,
            "unique_colors": len(colors),
            "out_of_palette": len(out_of_palette),
            "palette_hex": gray_hex,
            "gray_levels_used": [rgb_to_hex(c) for c in sorted(colors, key=lambda c: sum(c)) if is_gray(c)],
            "accent_pixels": accent_px,
            "accent_ratio": accent_ratio,
            "colors": unique_sorted,
        },
    }
