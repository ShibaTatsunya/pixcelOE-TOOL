# -*- coding: utf-8 -*-
"""把各步串成一次转换，并缓存可复用的中间结果。

缓存的意义
----------
整条链路里只有 **轮廓扩展**（``expand_only``）是昂贵的（局部统计 + 形态学，
640x960 上约 2~6 秒），而它**只依赖 ``patch / thickness / keep_thin`` 和输入图**。
后面所有参数（factor、降采样策略、dark_tol、调色板、收档数）都在它**之后**，
所以只要原始图与那三个参数没变，就能直接复用 —— 拖动 factor / 策略滑块时可以秒级出图。
"""
from __future__ import annotations

import hashlib
import itertools
import time
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np

from .algorithm import (DOWNSAMPLE_MODES, apply_dither, contrast_downsample,
                        desaturate_adjust, expand_only, nearest_palette, posterize_lum)
from .palette import gray_rgb, load_palette, narrow_palette, posterize_steps

#: 单张上传图的最大像素数（防止把 8K 图丢进来把内存吃光）
MAX_PIXELS = 40_000_000


# --------------------------------------------------------------------------
# 参数
# --------------------------------------------------------------------------
@dataclass
class Params:
    """一次转换的全部可调参数（字段名即 API 字段名）。"""

    # 预设标识（仅用于回显，不参与计算）
    preset: str = "character"

    # ---- 大步骤开关（每步可单独关闭，实时看效果）----
    enable_input: bool = True           # ① 输入与明暗
    enable_posterize: bool = True       # ② 灰阶分几层
    enable_outline: bool = True         # ③ 轮廓与线条
    enable_downsample: bool = True      # ④ 像素块大小
    enable_quantize: bool = True        # ⑤ 颜色

    # ---- 输入预处理 ----
    crop: list[int] | None = None      # [left, top, right, bottom]，None / 空 = 不裁
    desat: str = "hsl"                 # hsl | rec709
    gamma: float = 1.0
    brightness: float = 0.0            # PS 亮度 -150..150
    contrast: float = 0.0              # PS 对比度 -50..100

    # ---- 色调分离 ----
    posterize_skip: bool = False       # True = 输入已是分档灰图，跳过本步
    posterize_levels: int = 4          # 0 = 按调色板原样
    posterize_mode: str = "ps"         # ps | palette

    # ---- 轮廓扩展 ----
    patch: int = 2
    thickness: int = 1
    keep_thin: bool = False

    # ---- 对比度感知降采样 ----
    factor: int = 4
    downsample: str = "bridge"
    dark_tol: float = 0.06

    # ---- 量化 ----
    palette_kind: str = "character"    # character | scene
    quantize_levels: int = 4           # 0 = 用完整调色板
    no_quantize: bool = False
    dither: str = "none"               # none | bayer4 | bayer8（量化前有序抖动）
    dither_strength: float = 24.0

    # ---- 输出 ----
    canvas: str | None = None          # "160x240"，None = 不做尺寸校验

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Params":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (d or {}).items() if k in known}
        p = cls(**clean)
        p.normalize()
        return p

    def normalize(self) -> None:
        """把参数夹到合法范围，避免脏输入把后端打挂。"""
        self.factor = max(1, min(16, int(self.factor)))
        self.patch = max(1, min(4, int(self.patch)))
        self.thickness = max(0, min(4, int(self.thickness)))
        self.posterize_levels = max(0, min(8, int(self.posterize_levels)))
        self.quantize_levels = max(0, min(8, int(self.quantize_levels)))
        self.downsample = self.downsample if self.downsample in DOWNSAMPLE_MODES else "bridge"
        self.desat = self.desat if self.desat in ("hsl", "rec709") else "hsl"
        self.posterize_mode = self.posterize_mode if self.posterize_mode in ("ps", "palette") else "ps"
        self.palette_kind = self.palette_kind if self.palette_kind in ("character", "scene") else "character"
        self.gamma = float(max(0.2, min(3.0, self.gamma)))
        self.brightness = float(max(-150.0, min(150.0, self.brightness)))
        self.contrast = float(max(-50.0, min(100.0, self.contrast)))
        self.dark_tol = float(max(0.0, min(0.5, self.dark_tol)))
        self.dither = self.dither if self.dither in ("none", "bayer4", "bayer8") else "none"
        self.dither_strength = float(max(0.0, min(100.0, self.dither_strength)))
        if self.crop is not None:
            c = [int(v) for v in self.crop]
            self.crop = c if len(c) == 4 and c[2] > c[0] and c[3] > c[1] else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# 缓存
# --------------------------------------------------------------------------
class ExpandCache:
    """按 ``(图像指纹, patch, thickness, keep_thin)`` 缓存轮廓扩展结果。

    条目里存的是 ``(expanded_rgb float32, gray float32)``；640x960 时每条约 15 MB，
    默认只留 3 条。
    """

    def __init__(self, maxsize: int = 3):
        self.maxsize = maxsize
        self._d: OrderedDict[tuple, tuple[np.ndarray, np.ndarray]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.last_ms: float | None = None

    @staticmethod
    def fingerprint(arr: np.ndarray) -> str:
        return hashlib.blake2b(np.ascontiguousarray(arr).tobytes(), digest_size=12).hexdigest()

    def get_or_compute(self, arr: np.ndarray, patch: int, thickness: int, keep_thin: bool):
        key = (self.fingerprint(arr), patch, thickness, keep_thin)
        if key in self._d:
            self._d.move_to_end(key)
            self.hits += 1
            return self._d[key], True
        t0 = time.perf_counter()
        val = expand_only(arr, patch, thickness, keep_thin)
        self.last_ms = (time.perf_counter() - t0) * 1000
        self.misses += 1
        self._d[key] = val
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)
        return val, False


# --------------------------------------------------------------------------
# 转换
# --------------------------------------------------------------------------
@dataclass
class RenderResult:
    final: np.ndarray
    stages: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    cached_expand: bool = False
    input_size: tuple[int, int] = (0, 0)      # (w, h)
    applied_crop: list[int] | None = None
    warned: list[str] = field(default_factory=list)


def plan_crop(arr: np.ndarray, params: Params) -> tuple[np.ndarray, list[str]]:
    """按参数裁切输入图，并给出「尺寸不能被 factor 整除」的友好提示。"""
    warned: list[str] = []
    h, w, _ = arr.shape
    if params.crop:
        l, t, r, b = params.crop
        l, t = max(0, l), max(0, t)
        r, b = min(w, r), min(h, b)
        if r - l > 0 and b - t > 0:
            arr = arr[t:b, l:r]
            if (l, t, r, b) != tuple(params.crop):
                warned.append(f"裁剪框已夹到画面内：[{l}, {t}, {r}, {b}]")

    # 不再要求宽高能被 factor 整除，也不再自动裁边：不整除的部分由
    # pixelize_oe 内部用「边缘复制补齐」处理，输出尺寸取 ceil，不丢内容。
    return arr, warned


def convert(
    arr: np.ndarray,
    params: Params,
    palette: dict | None = None,
    cache: ExpandCache | None = None,
) -> RenderResult:
    """执行一次完整转换。``arr`` 为 HxWx3 的 uint8 RGB。"""
    pal = palette or load_palette()
    params.normalize()
    cache = cache if cache is not None else ExpandCache()

    t_all = time.perf_counter()
    timings: dict[str, float] = {}

    src, warned = plan_crop(arr, params)
    in_w, in_h = src.shape[1], src.shape[0]

    # ① 输入与明暗：去饱和 + 亮度/对比度 → 灰度 lum（float32）
    t0 = time.perf_counter()
    if params.posterize_skip:
        post = np.ascontiguousarray(src[:, :, :3])
        lum = src.astype(np.float32).mean(axis=2)
    elif params.enable_input:
        lum = desaturate_adjust(src, params.desat, params.gamma, params.brightness, params.contrast)
    else:
        lum = src.astype(np.float32).mean(axis=2)
    timings["input"] = (time.perf_counter() - t0) * 1000

    # ② 灰阶分几层：色调分离 → post（uint8）
    t0 = time.perf_counter()
    if not params.posterize_skip:
        if params.enable_posterize:
            post = posterize_lum(lum, params.posterize_levels, params.posterize_mode,
                                 gray_rgb(pal, params.palette_kind))
        else:
            post = np.dstack([lum, lum, lum]).astype(np.uint8)
    timings["posterize"] = (time.perf_counter() - t0) * 1000

    # ③ 轮廓与线条：轮廓扩展（跳过时直接进降采样）
    t0 = time.perf_counter()
    if params.enable_outline:
        (expanded_rgb, gray), hit = cache.get_or_compute(post, params.patch, params.thickness, params.keep_thin)
    else:
        expanded_rgb = post.astype(np.float32)
        gray = post.astype(np.float32).mean(axis=2)
        hit = False
    timings["expand"] = (time.perf_counter() - t0) * 1000

    # ④ 像素块大小：降采样（跳过时保持原尺寸）
    t0 = time.perf_counter()
    if params.enable_downsample:
        h, w = expanded_rgb.shape[:2]
        pad_h = (params.factor - h % params.factor) % params.factor
        pad_w = (params.factor - w % params.factor) % params.factor
        rgb_pad = expanded_rgb
        if pad_h or pad_w:
            rgb_pad = np.pad(expanded_rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
        small = contrast_downsample(rgb_pad.astype(np.uint8), params.factor, params.dark_tol, params.downsample)
    else:
        small = np.clip(expanded_rgb, 0, 255).astype(np.uint8)
    timings["downsample"] = (time.perf_counter() - t0) * 1000

    # ⑤ 颜色：抖动 + 调色板量化（跳过时保留降采样原值）
    t0 = time.perf_counter()
    if params.enable_quantize:
        if params.dither != "none":
            small = apply_dither(small, params.dither, params.dither_strength)
        if params.no_quantize:
            final = np.clip(small * 255.0, 0, 255).round().astype(np.uint8)
        else:
            pal_rgb = narrow_palette(gray_rgb(pal, params.palette_kind), params.quantize_levels)
            final = nearest_palette(small, list(pal_rgb))
    else:
        # ⑤关闭：不量化到项目调色板，但收敛回②的分档值。否则③轮廓扩展的浮点运算
        # 会把②的分档抹平成上万种连续灰度，用户调②（灰阶分几层）就看不出效果了。
        if params.enable_posterize:
            steps = np.array(posterize_steps(params.posterize_levels, params.posterize_mode,
                                             gray_rgb(pal, params.palette_kind)), dtype=np.float32)
            lum = small.astype(np.float32).mean(axis=2)
            idx = np.abs(lum[:, :, None] - steps[None, None, :]).argmin(axis=2)
            g = steps[idx].astype(np.uint8)
            final = np.dstack([g, g, g])
        else:
            final = small.copy()
    timings["quantize"] = (time.perf_counter() - t0) * 1000
    timings["total"] = (time.perf_counter() - t_all) * 1000

    return RenderResult(
        final=final,
        stages={
            "input": np.dstack([lum, lum, lum]).astype(np.uint8),
            "posterized": post,
            "expanded": np.clip(expanded_rgb, 0, 255).astype(np.uint8),
            "downsampled": small,
            "final": final,
        },
        timings=timings,
        cached_expand=hit,
        input_size=(in_w, in_h),
        applied_crop=params.crop,
        warned=warned,
    )
