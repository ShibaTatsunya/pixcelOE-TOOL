# -*- coding: utf-8 -*-
"""与产线脚本的**逐像素一致性**测试。

这是本工具最重要的一道验收：工具内部的算法必须与
``mengshi-art-workflow/scripts/`` 下的产线脚本**完全等价**，否则"可视化调参"得出的
结果与产线产出就不是同一套东西。

验证方式不是"看起来像"，而是：
    用真实 CLI 在真实图片上跑一遍 -> 与 core 的输出做逐像素比对 -> 必须 0 个像素不同。

运行：
    python tests/test_consistency.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.pipeline import ExpandCache, Params, convert  # noqa: E402

WF = ROOT.parent / "mengshi-art-workflow"
PIXELIZE = WF / "scripts" / "pixelize_oe.py"
POSTERIZE = WF / "scripts" / "posterize.py"
SAMPLE_DIR = WF / "experiments" / "E048-front-light" / "outputs" / "canon_ps" / "bag_a"
SRC_RGB = SAMPLE_DIR / "01_crop.png"      # 原始 RGB 大图
SRC_POST4 = SAMPLE_DIR / "02_post4.png"   # 已做过 4 档色调分离的图

PASS: list[str] = []
FAIL: list[str] = []
SKIP: list[str] = []


def load(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGB"))


def compare(a: np.ndarray, b: np.ndarray, label: str) -> None:
    if a.shape != b.shape:
        FAIL.append(f"{label}: 尺寸不同 {a.shape} vs {b.shape}")
        return
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    n = int((d.max(axis=2) > 0).sum())
    if n == 0:
        PASS.append(f"{label}（{a.shape[1]}x{a.shape[0]}，逐像素完全一致）")
    else:
        worst = int(d.max())
        FAIL.append(f"{label}: {n} 个像素不同（最大通道差 {worst}，占比 {n / (a.shape[0] * a.shape[1]) * 100:.3f}%）")


def run_cli(script: Path, args: list[str]) -> None:
    cmd = [sys.executable, str(script)] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"CLI 失败：{' '.join(cmd)}\n{r.stdout}\n{r.stderr}")


# --------------------------------------------------------------------------
# 用例 1：pixelize_oe.py（输入已是分档灰图）
# --------------------------------------------------------------------------
PIXELIZE_CASES = [
    ("pixelize / 默认（bridge）", [], dict()),
    ("pixelize / skew + dark-line 0.12", ["--downsample", "skew", "--dark-line", "0.12"],
     dict(downsample="skew", dark_tol=0.12)),
    ("pixelize / dark", ["--downsample", "dark"], dict(downsample="dark")),
    ("pixelize / median + levels 4", ["--downsample", "median", "--levels", "4"],
     dict(downsample="median", quantize_levels=4)),
    ("pixelize / edge + keep-thin + t1 p3",
     ["--downsample", "edge", "--keep-thin", "--thickness", "1", "--patch", "3"],
     dict(downsample="edge", keep_thin=True, thickness=1, patch=3)),
]


def test_pixelize(tmpdir: Path) -> None:
    if not (SRC_POST4.exists() and PIXELIZE.exists()):
        SKIP.append("pixelize 用例：缺少样例图或产线脚本")
        return
    src = load(SRC_POST4)
    cache = ExpandCache()
    # 必须显式对齐 CLI 默认值，否则比的是「默认值差异」而不是算法差异
    base = dict(factor=4, posterize_skip=True, palette_kind="character",
                thickness=2, patch=2, dark_tol=0.06, downsample="bridge", quantize_levels=0)
    for label, cli_extra, kw in PIXELIZE_CASES:
        out = tmpdir / (label.replace("/", "_").replace(" ", "_").replace("（", "").replace("）", "") + ".png")
        run_cli(PIXELIZE, [str(SRC_POST4), "--palette", "character", "--factor", "4",
                           "--out", str(out), "--force"] + cli_extra)
        params = Params(**{**base, **kw})
        res = convert(src, params, cache=cache)
        compare(load(out), res.final, label)


# --------------------------------------------------------------------------
# 用例 2：posterize.py（原始 RGB -> 分档灰图）
# --------------------------------------------------------------------------
POSTERIZE_CASES = [
    ("posterize / levels4 ps hsl", ["--levels", "4", "--mode", "ps", "--desat", "hsl"],
     dict(levels=4, mode="ps", desat="hsl")),
    ("posterize / levels4 + contrast 60", ["--levels", "4", "--mode", "ps", "--contrast", "60"],
     dict(levels=4, contrast=60.0)),
    ("posterize / levels5 palette rec709 gamma1.2",
     ["--levels", "5", "--mode", "palette", "--desat", "rec709", "--gamma", "1.2"],
     dict(levels=5, mode="palette", desat="rec709", gamma=1.2)),
]


def test_posterize(tmpdir: Path) -> None:
    if not (SRC_RGB.exists() and POSTERIZE.exists()):
        SKIP.append("posterize 用例：缺少样例图或产线脚本")
        return
    src = load(SRC_RGB)
    from core.pipeline import RenderResult, plan_crop  # noqa: F401
    from core.algorithm import desaturate_posterize
    from core.palette import gray_rgb, load_palette

    pal = load_palette()
    for i, (label, cli_extra, kw) in enumerate(POSTERIZE_CASES):
        out = tmpdir / f"post_{i}.png"
        run_cli(POSTERIZE, [str(SRC_RGB), "--palette", "character", "--out", str(out), "--force"] + cli_extra)
        mine = desaturate_posterize(src, palette=gray_rgb(pal, "character"), **kw)
        compare(load(out), mine, label)


# --------------------------------------------------------------------------
# 用例 3：端到端（posterize -> pixelize 两个 CLI）对照 pipeline.convert
# --------------------------------------------------------------------------
def test_end_to_end(tmpdir: Path) -> None:
    if not (SRC_RGB.exists() and PIXELIZE.exists() and POSTERIZE.exists()):
        SKIP.append("端到端用例：缺少样例图或产线脚本")
        return
    mid = tmpdir / "e2e_post.png"
    gold = tmpdir / "e2e_final.png"
    run_cli(POSTERIZE, [str(SRC_RGB), "--palette", "character", "--levels", "4",
                        "--mode", "ps", "--desat", "hsl", "--out", str(mid), "--force"])
    run_cli(PIXELIZE, [str(mid), "--palette", "character", "--factor", "4",
                       "--out", str(gold), "--force"])
    params = Params(factor=4, posterize_levels=4, posterize_mode="ps", desat="hsl",
                    palette_kind="character", thickness=2, patch=2, quantize_levels=0)
    res = convert(load(SRC_RGB), params, cache=ExpandCache())
    compare(load(gold), res.final, "端到端 / posterize.py + pixelize_oe.py -> convert()")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        test_pixelize(tmpdir)
        test_posterize(tmpdir)
        test_end_to_end(tmpdir)

    print("=" * 78)
    for s in PASS:
        print(f"  [PASS] {s}")
    for s in SKIP:
        print(f"  [SKIP] {s}")
    for s in FAIL:
        print(f"  [FAIL] {s}")
    print("=" * 78)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)} / 跳过 {len(SKIP)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
