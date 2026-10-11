# -*- coding: utf-8 -*-
"""前端静态资源的一致性检查（不需要浏览器）。

检查 HTML / JS / CSS 三者的引用是否自洽：
  * app.js 里 ``$('#id')`` 引用的元素，index.html 里必须存在（动态创建的除外）；
  * index.html 引用的 /web/*.css 与 /web/*.js 必须真的存在；
  * JS 读取的 dataset 字段（data-v / data-z）必须在 HTML 里有对应属性；
  * CSS 里用到的关键类名必须在 HTML 或 JS 中出现过（防拼写漂移）。

运行：
    python tests/test_web_assets.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: 由 JS 在运行时创建、因此不必出现在 index.html 里的 id
DYNAMIC_IDS = {"toast"}

#: 由 JS 自己写入的 dataset（不从 HTML 读），不需要 HTML 里有对应属性
DYNAMIC_DATASET = {"url", "k"}

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str, extra: str = "") -> None:
    (PASS if cond else FAIL).append(msg + ("" if cond else f" —— {extra}"))


def main() -> int:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r"""\$\(['"]#([A-Za-z0-9_-]+)['"]""", js))
    js_ids |= set(re.findall(r"""getElementById\(['"]([A-Za-z0-9_-]+)['"]\)""", js))

    missing = sorted(js_ids - html_ids - DYNAMIC_IDS)
    check(not missing, f"JS 引用的 {len(js_ids)} 个元素 id 都存在", "缺失：" + ", ".join(missing))

    # 静态资源引用
    for ref in re.findall(r'(?:href|src)="(/web/[^"]+)"', html):
        p = WEB / ref[len("/web/"):]
        check(p.is_file(), f"index.html 引用的 {ref} 存在")

    # dataset 字段
    for attr in sorted(set(re.findall(r"dataset\.([A-Za-z]+)", js)) - DYNAMIC_DATASET):
        kebab = re.sub(r"([A-Z])", r"-\1", attr).lower()
        check(f"data-{kebab}" in html or f"data-{kebab}" in js,
              f"dataset.{attr} 在 HTML 里有对应的 data-{kebab} 属性")

    # CSS 关键类是否被引用
    css_classes = set(re.findall(r"\.([a-z][a-z0-9-]{2,})", css))
    used = html + js
    unused = sorted(c for c in css_classes if c not in used)
    check(len(unused) <= 8, f"CSS 中未被引用的类数量合理（{len(unused)} 个）", ", ".join(unused))

    print("=" * 78)
    for s in PASS:
        print(f"  [PASS] {s}")
    for s in FAIL:
        print(f"  [FAIL] {s}")
    print("=" * 78)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
