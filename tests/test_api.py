# -*- coding: utf-8 -*-
"""端到端 API 测试：真的把 ``app.py`` 起起来，用 HTTP 走一遍完整流程。

覆盖：静态页面 -> 元信息 -> 上传 -> 取原图 -> 转换 -> 报告 -> 导出 -> 错误分支。

运行：
    python tests/test_api.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT.parent / "mengshi-art-workflow"
SAMPLE = WF / "experiments" / "E048-front-light" / "outputs" / "canon_ps" / "bag_a" / "01_crop.png"

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"

PASS: list[str] = []
FAIL: list[str] = []
SKIP: list[str] = []


def ok(msg: str) -> None:
    PASS.append(msg)


def bad(msg: str) -> None:
    FAIL.append(msg)


def check(cond: bool, msg: str, extra: str = "") -> None:
    (ok if cond else bad)(msg + ("" if cond else f" —— {extra}"))


def post_raw(path: str, data: bytes, ctype: str = "application/octet-stream"):
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": ctype}, method="POST")
    return urllib.request.urlopen(req, timeout=180)


def post_json(path: str, obj: dict):
    return post_raw(path, json.dumps(obj).encode("utf-8"), "application/json")


def get(path: str):
    return urllib.request.urlopen(BASE + path, timeout=180)


def wait_up(timeout: float = 40.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with get("/api/meta") as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.35)
    return False


def main() -> int:
    if not SAMPLE.exists():
        print(f"缺少样例图：{SAMPLE}")
        return 2

    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py"), "--port", str(PORT), "--no-browser"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        if not wait_up():
            out = proc.stdout.read() if proc.stdout else ""
            print("服务未能启动。输出：\n" + out)
            return 2
        ok("服务启动并响应 /api/meta")

        # 1) 静态资源
        with get("/") as r:
            html = r.read().decode("utf-8")
        check("pixcelOE" in html and "<title>" in html, "GET / 返回前端页面", html[:120])
        with get("/web/app.js") as r:
            js = r.read().decode("utf-8")
        check("renderNow" in js, "GET /web/app.js 返回脚本")
        with get("/web/style.css") as r:
            css = r.read().decode("utf-8")
        check("--accent" in css, "GET /web/style.css 返回样式")

        # 2) 元信息
        with get("/api/meta") as r:
            meta = json.loads(r.read().decode("utf-8"))
        check(len(meta.get("downsample", [])) == 5, "元信息含 5 种降采样策略")
        check(meta["palette"]["character"][0] == "#0F0F0F", "元信息含角色调色板", str(meta["palette"]["character"][:2]))

        # 3) 上传
        raw = SAMPLE.read_bytes()
        with post_raw("/api/upload", raw) as r:
            up = json.loads(r.read().decode("utf-8"))
        check("id" in up and up["width"] > 0, f"上传成功：{up.get('width')}x{up.get('height')}", str(up))
        iid = up["id"]

        # 4) 原图
        with get(f"/api/original?id={iid}") as r:
            ob = r.read()
        check(ob[:8] == b"\x89PNG\r\n\x1a\n", "GET /api/original 返回 PNG", str(ob[:8]))

        # 5) 转换（角色预设参数）
        params = {
            "posterize_levels": 4, "posterize_mode": "ps", "desat": "hsl", "contrast": 60,
            "patch": 2, "thickness": 2, "factor": 4, "downsample": "bridge",
            "dark_tol": 0.06, "palette_kind": "character", "quantize_levels": 0,
            "canvas": "160x240",
        }
        with post_json("/api/render", {"id": iid, "params": params}) as r:
            png = r.read()
            size = r.headers.get("X-Out-Size")
            ms = r.headers.get("X-Render-Ms")
        check(png[:8] == b"\x89PNG\r\n\x1a\n" and size == "160x240",
              f"POST /api/render 输出 {size}（{ms} ms）", size or "无 X-Out-Size")

        # 5b) factor 不整除时自动补齐边缘（不裁内容、不报错），输出尺寸取 ceil
        with post_json("/api/render", {"id": iid, "params": {
                "factor": 3, "posterize_skip": True, "palette_kind": "character", "quantize_levels": 0}}) as r:
            png2 = r.read()
            size2 = r.headers.get("X-Out-Size")
        check(png2[:8] == b"\x89PNG\r\n\x1a\n" and size2 == "214x320",
              f"factor=3 不整除时自动补齐到 {size2}", size2 or "无 X-Out-Size")

        # 6) 报告（应命中渲染缓存，第二次很快）
        t0 = time.time()
        with post_json("/api/report", {"id": iid, "params": params}) as r:
            rep = json.loads(r.read().decode("utf-8"))
        dt = (time.time() - t0) * 1000
        v = rep.get("validate", {})
        check(v.get("pass") is True, "验收 4 项全部通过", json.dumps(v.get("checks", []), ensure_ascii=False))
        check(len(v.get("checks", [])) >= 4, "报告含 >=4 项检查")
        check(rep.get("output_size") == [160, 240], "报告输出尺寸 160x240", str(rep.get("output_size")))
        check(dt < 3000, f"报告命中缓存（{dt:.0f} ms）", f"{dt:.0f} ms")

        # 7) 导出
        with post_json("/api/export", {"id": iid, "params": params, "name": "_api_test"}) as r:
            ex = json.loads(r.read().decode("utf-8"))
        png_p, meta_p = Path(ex["png"]), Path(ex["meta"])
        check(png_p.exists() and meta_p.exists(), "导出 PNG + JSON 元数据", str(ex))
        if png_p.exists():
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            check(m.get("params", {}).get("factor") == 4, "元数据记录了完整参数")
            png_p.unlink()
            meta_p.unlink()

        # 8) 错误分支
        try:
            get("/api/nope")
            bad("未知路径应返回 404")
        except urllib.error.HTTPError as e:
            check(e.code == 404, "未知路径返回 404", str(e.code))
        try:
            post_raw("/api/upload", b"")
            bad("空上传应返回 400")
        except urllib.error.HTTPError as e:
            check(e.code == 400, "空上传返回 400", str(e.code))
        try:
            post_json("/api/render", {"id": "doesnotexist", "params": {}})
            bad("未知 id 应返回 404")
        except urllib.error.HTTPError as e:
            check(e.code == 404, "未知图片 id 返回 404", str(e.code))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

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
