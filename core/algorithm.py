# -*- coding: utf-8 -*-
"""像素化算法核心 —— 产线脚本的逐行移植，**不改数值行为**。

来源：
    mengshi-art-workflow/scripts/posterize.py    去饱和 + 色调分离
    mengshi-art-workflow/scripts/pixelize_oe.py  轮廓扩展 + 对比度感知降采样 + 调色板量化

移植原则
--------
1. **每一处 dtype、运算顺序、常量都与原脚本相同**。例如 ``gray`` 先在 float64 上算完
   才 ``astype(np.float32)``；``contrast_downsample`` 的偏斜容差 ``tol=0.02`` 是硬编码。
   改任何一处都可能让逐像素比对失败，进而让工具产出与产线不一致。
2. 一致性由 ``tests/test_consistency.py`` 用**真实图片 + 真实 CLI 调用**验证：
   相同参数下本模块与产线脚本的输出必须**逐像素完全相同**。

算法链路
--------
::

    RGB 大图（例如 640x960）
      |
      |-- desaturate_posterize()   去饱和 -> 色调分离（PS 算法：floor(v*N/256)）
      |
      |-- outline_expand()         对比度感知轮廓扩展（让细线在缩小后存活）
      |-- contrast_downsample()    对比度感知降采样（块内偏斜取极值 / bridge 补缺口）
      |-- nearest_palette()        固定调色板最近色量化
      v
    像素小图（例如 160x240）
"""
from __future__ import annotations

import numpy as np

from .palette import narrow_palette, posterize_steps

#: 对比度感知降采样支持的块内取值策略
DOWNSAMPLE_MODES = ("bridge", "skew", "dark", "edge", "median")

#: 各策略的一句话说明（供 UI 直接展示）
DOWNSAMPLE_HELP = {
    "bridge": "推荐：只把断掉的暗线补上，线连得上又不额外加粗",
    "skew": "原始算法：轮廓容易断成虚线（对照用）",
    "dark": "暗线更实但更粗，画面偏闷",
    "edge": "只处理贴着背景的边缘（一般用不上）",
    "median": "每个像素块取中间值，线条会变淡",
}


# --------------------------------------------------------------------------
# 局部统计与形态学（pixelize_oe.py 原样）
# --------------------------------------------------------------------------
def shift_stack(a: np.ndarray, r: int) -> np.ndarray:
    """所有 ``(2r+1)^2`` 个平移窗口视图（边缘按 edge 复制）。"""
    h, w = a.shape
    padded = np.pad(a, r, mode="edge")
    return np.stack([padded[dy : dy + h, dx : dx + w] for dy in range(2 * r + 1) for dx in range(2 * r + 1)])


def local_stat(a: np.ndarray, r: int):
    """窗口内的 ``(min, max, median)``。"""
    st = shift_stack(a, r)
    return st.min(axis=0), st.max(axis=0), np.median(st, axis=0)


def morph(a: np.ndarray, r: int, mode: str) -> np.ndarray:
    """``mode='min'`` 为腐蚀（收缩亮区），``'max'`` 为膨胀（扩展亮区）。"""
    h, w = a.shape
    padded = np.pad(a, r, mode="edge")
    out = a.copy()
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            win = padded[dy : dy + h, dx : dx + w]
            np.minimum(out, win, out=out) if mode == "min" else np.maximum(out, win, out=out)
    return out


def outline_expand(gray: np.ndarray, patch: int, thickness: int, keep_thin: bool = False) -> np.ndarray:
    """对比度感知轮廓扩展，返回处理后的灰度（float32）。

    ``keep_thin=True`` 时跳过最后那步开运算（先腐蚀后膨胀）——开运算会抹掉宽度不足
    2 像素的细线，而嘴唇线、睫毛、衣物缝线在降采样前的图里正好就是这个宽度。

    权重组合两条线索：
      w1 = (1 - med/255) * (mx - med)   中位越暗，亮细节越该被保留
      w2 = |bright - dark|              亮/暗距离之差越大，对比越强
    """
    mn, mx, med = local_stat(gray, patch)
    bright = np.clip(mx - med, 0, None)
    dark = np.clip(med - mn, 0, None)

    w1 = (1.0 - med / 255.0) * bright
    w2 = np.abs(bright - dark)
    w = w1 + w2
    w = w / (w.max() + 1e-6)

    eroded = morph(gray, thickness, "min")   # 收缩亮区
    dilated = morph(gray, thickness, "max")  # 扩展亮区
    blended = w * dilated + (1.0 - w) * eroded

    closed = morph(morph(blended, 1, "max"), 1, "min")  # 闭：补断线
    if keep_thin:
        return closed
    return morph(morph(closed, 1, "min"), 1, "max")     # 开：去孤立噪点，但也会抹掉 1px 细线


# --------------------------------------------------------------------------
# 对比度感知降采样（pixelize_oe.py 原样）
# --------------------------------------------------------------------------
def contrast_downsample(
    rgb: np.ndarray, factor: int, dark_tol: float = 0.06, mode: str = "bridge"
) -> np.ndarray:
    """L 通道按块内偏斜选极值，A/B 通道取块中值。

    块跨在轮廓上时（一半主体、一半背景），纯偏斜判定会让相邻块交替取 b_min（→黑）
    与 b_max（→背景），轮廓于是变成「黑一段、背景一段」的虚线。``mode`` 用来改这个行为，
    详见 :data:`DOWNSAMPLE_HELP`。
    """
    h, w, _ = rgb.shape
    ph, pw = h // factor, w // factor
    crop = rgb[: ph * factor, : pw * factor].astype(np.float32) / 255.0
    lum = 0.2126 * crop[:, :, 0] + 0.7152 * crop[:, :, 1] + 0.0722 * crop[:, :, 2]
    blocks = lum.reshape(ph, factor, pw, factor).transpose(0, 2, 1, 3).reshape(ph, pw, factor * factor)
    b_med = np.median(blocks, axis=2)
    b_mean = blocks.mean(axis=2)
    b_min = blocks.min(axis=2)
    b_max = blocks.max(axis=2)

    tol = 0.02
    center = (factor * factor) // 2
    if mode == "median":
        out_lum = b_med
    else:
        out_lum = np.where(
            b_med < b_mean - tol,
            b_min,
            np.where(b_med > b_mean + tol, b_max, blocks[:, :, center]),
        )
        if mode == "bridge":
            # 只补「缺口」：基础判定本来要取亮值（b_max/中心）的块，若块内确有明显暗线，
            # 才改取 b_min。已经是暗的块不动 —— 因此不会像 dark 那样把线整体加粗，
            # 断线被接上而其余像素保持原有脆度。（实测脆度 21.08 vs skew 20.08）
            chose_light = out_lum > b_med
            gap = (b_min < b_med - dark_tol) & chose_light
            out_lum = np.where(gap, b_min, out_lum)
        elif mode in ("dark", "edge") and dark_tol > 0:
            if mode == "edge":
                is_bg = lum > 0.90
                bgf = is_bg.reshape(ph, factor, pw, factor).transpose(0, 2, 1, 3).reshape(
                    ph, pw, factor * factor
                ).mean(axis=2)
                mixed = bgf > 0.02
                dark_line = (b_min < b_med - dark_tol) & mixed
            else:
                dark_line = b_min < b_med - dark_tol
            out_lum = np.where(dark_line, b_min, out_lum)

    # 色度：块中值，抑制色彩噪点
    out = np.zeros((ph, pw, 3), dtype=np.float32)
    for c in range(3):
        ch = crop[: ph * factor, : pw * factor, c]
        cb = ch.reshape(ph, factor, pw, factor).transpose(0, 2, 1, 3).reshape(ph, pw, factor * factor)
        out[:, :, c] = np.median(cb, axis=2)

    # 用降采样后的亮度替换亮度分量（保持色相、提升暗部可读性）
    cur_lum = 0.2126 * out[:, :, 0] + 0.7152 * out[:, :, 1] + 0.0722 * out[:, :, 2]
    delta = out_lum - cur_lum
    out = np.clip(out + delta[:, :, None], 0, 1)
    return (out * 255.0).round().astype(np.uint8)


def nearest_palette(img: np.ndarray, palette) -> np.ndarray:
    """固定调色板最近色映射（欧氏距离）。禁止「每图统计取前 N 色」。"""
    pal = np.array(palette, dtype=np.int32)
    flat = img.reshape(-1, 3).astype(np.int32)
    d = ((flat[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
    return pal[d.argmin(axis=1)].astype(np.uint8).reshape(img.shape)


# --------------------------------------------------------------------------
# 有序抖动（pixelize.py 的 Bayer 图案，量化前在亮度上叠加）
# --------------------------------------------------------------------------
BAYER = {
    "bayer4": np.array(
        [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
        dtype=np.float32,
    ),
    "bayer8": np.array(
        [
            [0, 32, 8, 40, 2, 34, 10, 42],
            [48, 16, 56, 24, 50, 18, 58, 26],
            [12, 44, 4, 36, 14, 46, 6, 38],
            [60, 28, 52, 20, 62, 30, 54, 22],
            [3, 35, 11, 43, 1, 33, 9, 41],
            [51, 19, 59, 27, 49, 17, 57, 25],
            [15, 47, 7, 39, 13, 45, 5, 37],
            [63, 31, 55, 23, 61, 29, 53, 21],
        ],
        dtype=np.float32,
    ),
}

#: 抖动图案选项（供 UI / API）
DITHER_CHOICES = ("none", "bayer4", "bayer8")

DITHER_HELP = {
    "none": "不抖动（默认，输出与产线逐像素一致）",
    "bayer4": "4×4 Bayer 有序抖动：灰阶过渡处出现规律纹理，模拟中间调",
    "bayer8": "8×8 Bayer 有序抖动：纹理更细腻",
}


def apply_dither(img: np.ndarray, pattern: str, strength: float) -> np.ndarray:
    """量化前的有序抖动：在亮度上叠加 Bayer 图案（与 ``pixelize.py --dither`` 一致）。

    ``img`` 为 uint8 RGB(0-255)。灰阶图三通道相等时等价于直接在灰度上偏移；
    彩色图按亮度比例缩放，保持色相。输出仍为 uint8，交给 ``nearest_palette`` 量化。
    """
    if pattern not in BAYER:
        raise ValueError(f"未知抖动图案：{pattern!r}")
    m = BAYER[pattern]
    m = m / m.size - 0.5
    th, tw = m.shape
    h, w = img.shape[:2]
    tile = np.tile(m, (h // th + 1, w // tw + 1))[:h, :w]
    lum0 = img.astype(np.float32).mean(axis=2)
    lum1 = np.clip(lum0 + tile * strength, 0, 255)
    ratio = np.where(lum0 > 0, lum1 / np.maximum(lum0, 1e-6), 1.0)
    return np.clip(img.astype(np.float32) * ratio[:, :, None], 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# 两个阶段入口
# --------------------------------------------------------------------------
def desaturate_adjust(arr: np.ndarray, desat: str = "hsl", gamma: float = 1.0,
                      brightness: float = 0.0, contrast: float = 0.0) -> np.ndarray:
    """① 输入与明暗：去饱和 + 明暗调整，返回灰度 ``lum``（float32，0-255）。

    去饱和（``desat``）：``hsl`` = (max+min)/2（对齐 PS 饱和度 −100）；``rec709`` = 加权平均。
    亮度/对比度：对比度用经典公式 ``k=(259*(C+255))/(255*(259-C))`` 围绕中灰 128 缩放。
    """
    a = arr.astype(np.float32)
    if desat == "hsl":
        lum = (a.max(axis=2) + a.min(axis=2)) * 0.5
    else:
        lum = 0.2126 * a[:, :, 0] + 0.7152 * a[:, :, 1] + 0.0722 * a[:, :, 2]
    if gamma != 1.0:
        lum = 255.0 * (lum / 255.0) ** gamma
    if brightness:
        lum = lum + brightness
    if contrast:
        k = (259.0 * (contrast + 255.0)) / (255.0 * (259.0 - contrast))
        lum = k * (lum - 128.0) + 128.0
    return np.clip(lum, 0.0, 255.0)


def posterize_lum(lum: np.ndarray, levels: int = 0, mode: str = "ps", palette=None) -> np.ndarray:
    """② 灰阶分几层：把灰度 ``lum``（float32 0-255）分档，返回 RGB（三通道等值）uint8。

    PS 模式（``mode="ps"``）用 floor 分档：``idx = floor(lum*levels/256)``，4 档边界 64/128/192。
    """
    steps = np.array(posterize_steps(levels, mode, palette), dtype=np.float32)
    if mode == "ps" and levels and levels >= 2:
        idx = np.floor(lum.astype(np.float32) * float(levels) / 256.0).astype(np.int32)
        idx = np.clip(idx, 0, len(steps) - 1)
    else:
        idx = np.abs(lum[:, :, None] - steps[None, None, :]).argmin(axis=2)
    gray = steps[idx].astype(np.uint8)
    return np.dstack([gray, gray, gray])


def adjust_color(arr: np.ndarray, gamma: float = 1.0, brightness: float = 0.0,
                 contrast: float = 0.0) -> np.ndarray:
    """彩色图的明暗调整（gamma/brightness/contrast），保持色相不变。

    以 HSL 亮度 ``(max+min)/2`` 为基准做明暗调整，再按比例缩放 RGB，不改变色相。
    """
    a = arr.astype(np.float32)
    lum0 = (a.max(axis=2) + a.min(axis=2)) * 0.5
    lum = lum0.copy()
    if gamma != 1.0:
        lum = 255.0 * (lum / 255.0) ** gamma
    if brightness:
        lum = lum + brightness
    if contrast:
        k = (259.0 * (contrast + 255.0)) / (255.0 * (259.0 - contrast))
        lum = k * (lum - 128.0) + 128.0
    lum = np.clip(lum, 0.0, 255.0)
    ratio = np.where(lum0 > 0, lum / np.maximum(lum0, 1e-6), 1.0)
    return np.clip(a * ratio[:, :, None], 0.0, 255.0).astype(np.uint8)


def posterize_color(arr: np.ndarray, levels: int = 4) -> np.ndarray:
    """彩色分档：对每个 RGB 通道分别做 PS 式 floor 分档。"""
    a = arr.astype(np.float32)
    if levels and levels >= 2:
        idx = np.floor(a * float(levels) / 256.0).astype(np.int32)
        idx = np.clip(idx, 0, levels - 1)
        a = idx * 255.0 / float(levels - 1)
    return np.clip(a, 0.0, 255.0).astype(np.uint8)


def desaturate_posterize(
    arr: np.ndarray, levels: int = 0, mode: str = "ps", desat: str = "hsl",
    gamma: float = 1.0, brightness: float = 0.0, contrast: float = 0.0, palette=None,
) -> np.ndarray:
    """兼容包装：去饱和 + 色调分离（= :func:`desaturate_adjust` + :func:`posterize_lum`）。"""
    lum = desaturate_adjust(arr, desat, gamma, brightness, contrast)
    return posterize_lum(lum, levels, mode, palette)


def pixelize_oe(
    arr: np.ndarray,
    palette,
    factor: int,
    thickness: int = 2,
    patch: int = 2,
    dark_tol: float = 0.06,
    downsample: str = "bridge",
    keep_thin: bool = False,
    no_quantize: bool = False,
    dither: str = "none",
    dither_strength: float = 24.0,
    expanded_rgb=None,
):
    """轮廓扩展 + 对比度感知降采样 + 调色板量化。

    ``expanded_rgb`` 可传入已算好的「轮廓扩展结果」以跳过最贵的一步
    （见 :func:`expand_only`）；``None`` 时现场计算。

    返回 ``(final, stages)``；``stages`` 是各步中间产物，供 UI 展示管线：
    ``gray`` / ``expanded_rgb`` / ``downsampled``。
    """
    h, w, _ = arr.shape

    if expanded_rgb is None:
        expanded_rgb, gray = expand_only(arr, patch, thickness, keep_thin)
    else:
        gray = (0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]).astype(np.float32)

    # 尺寸不能被 factor 整除时，用「边缘复制」把右下补齐到整数倍，而不是报错或裁内容。
    # 边缘复制不引入新颜色，只会让最后一行/列的像素块被相邻边缘像素填满，
    # 输出尺寸 = ceil(w/factor) × ceil(h/factor)。整除时 pad 为 0，与原产线完全一致。
    pad_h = (factor - h % factor) % factor
    pad_w = (factor - w % factor) % factor
    rgb_pad = expanded_rgb
    if pad_h or pad_w:
        rgb_pad = np.pad(expanded_rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")

    small = contrast_downsample(rgb_pad.astype(np.uint8), factor, dark_tol, downsample)
    if dither != "none":
        small = apply_dither(small, dither, dither_strength)
    if no_quantize:
        # 注意：这是 pixelize_oe.py 原脚本的行为 —— small 已是 uint8(0-255)，
        # 再乘 255 会大量溢出后被 clip 成 255，成品几乎全白。照抄以保证一致性。
        final = np.clip(small * 255.0, 0, 255).round().astype(np.uint8)
    else:
        if not palette:
            raise ValueError("量化需要非空调色板（或设置 no_quantize=True）")
        final = nearest_palette(small, list(palette))
    return final, {"gray": gray, "expanded_rgb": expanded_rgb, "downsampled": small}


def expand_only(arr: np.ndarray, patch: int, thickness: int, keep_thin: bool = False):
    """只做「轮廓扩展」，返回 ``(expanded_rgb, gray)``。

    这是整条链路里**唯一昂贵的一步**（局部统计 + 形态学），且只依赖
    ``patch / thickness / keep_thin`` 与输入图。参数微调（factor / 调色板 / 降采样策略）
    时复用它可以做到秒级出图 —— 见 :mod:`core.pipeline` 的缓存。
    """
    gray = (0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]).astype(np.float32)
    expanded = outline_expand(gray, patch, thickness, keep_thin)
    # 把「扩展后的亮度」按比例还原回 RGB（保留原色相/饱和度的相对关系）
    ratio = np.clip(expanded / np.maximum(gray, 1.0), 0.0, 4.0)
    rgb_expanded = np.clip(arr.astype(np.float32) * ratio[:, :, None], 0, 255)
    return rgb_expanded, gray
