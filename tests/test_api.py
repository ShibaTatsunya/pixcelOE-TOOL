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

import numpy as np

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

        # 5c) 抖动：bayer4 开启后输出仍在调色板内、且与关闭时不同
        import io
        from PIL import Image
        with post_json("/api/render", {"id": iid, "params": {"dither": "bayer4", "dither_strength": 24,
                "factor": 4, "posterize_skip": True, "palette_kind": "character", "quantize_levels": 4}}) as r:
            png_d = r.read()
        with post_json("/api/render", {"id": iid, "params": {"dither": "none",
                "factor": 4, "posterize_skip": True, "palette_kind": "character", "quantize_levels": 4}}) as r:
            png_n = r.read()
        a_d = np.asarray(Image.open(io.BytesIO(png_d)).convert("RGB"))
        a_n = np.asarray(Image.open(io.BytesIO(png_n)).convert("RGB"))
        diff = int((np.abs(a_d.astype(int) - a_n.astype(int)).max(axis=2) > 0).sum())
        check(diff > 0, f"抖动 bayer4 改变了输出（{diff} 像素不同）", str(diff))

        # 5d) 大步骤开关：关闭「轮廓与线条」后输出变化（证明开关生效）
        with post_json("/api/render", {"id": iid, "params": {"enable_outline": False,
                "factor": 4, "posterize_skip": True, "palette_kind": "character", "quantize_levels": 4}}) as r:
            png_off = r.read()
        a_off = np.asarray(Image.open(io.BytesIO(png_off)).convert("RGB"))
        diff_off = int((np.abs(a_off.astype(int) - a_n.astype(int)).max(axis=2) > 0).sum())
        check(diff_off > 0, f"关闭「轮廓与线条」后输出变化（{diff_off} 像素不同）", str(diff_off))

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

        # 7) 导出（含放大倍数）
        with post_json("/api/export", {"id": iid, "params": params, "name": "_api_test", "scale": 4}) as r:
            ex = json.loads(r.read().decode("utf-8"))
        png_p, meta_p = Path(ex["png"]), Path(ex["meta"])
        check(png_p.exists() and meta_p.exists(), "导出 PNG + JSON 元数据", str(ex))
        if png_p.exists():
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            check(m.get("params", {}).get("factor") == 4, "元数据记录了完整参数")
            check(m.get("scale") == 4, "元数据记录了放大倍数", str(m.get("scale")))
            from PIL import Image
            with Image.open(png_p) as im:
                check(im.size == (640, 960), f"scale=4 导出图 640x960（原 160x240）", str(im.size))
            png_p.unlink()
            meta_p.unlink()

        # Selective artwork uses original color masks, source ROI and exact fills.
        from test_selective import fixture, rules
        buf = io.BytesIO(); Image.fromarray(fixture()).save(buf, format='PNG')
        with post_raw('/api/upload', buf.getvalue()) as r:
            selective_id = json.loads(r.read())['id']
        selective_params = dict(selective_mode=True, factor=1, enable_outline=False, accent_rules=rules())
        with post_json('/api/render', {'id': selective_id, 'params': selective_params}) as r:
            art = np.asarray(Image.open(io.BytesIO(r.read())).convert('RGB'))
        mask = art.max(axis=2)-art.min(axis=2)>8
        check(int(mask.sum()) == 120 and np.all(art[mask] == [91,25,28]), '抽色输出保持灰阶明度、框外同色保持灰阶')
        with post_json('/api/report', {'id': selective_id, 'params': selective_params}) as r:
            selective_report = json.loads(r.read())
        check(selective_report['validate']['pass'] and selective_report['validate']['details']['accent_pixels'] == 120,
              '抽色验收记录实际强调色面积')
        with post_json('/api/export', {'id': selective_id, 'params': selective_params, 'name': '_api_selective_test', 'scale': 2}) as r:
            selective_export = json.loads(r.read())
        metadata = Path(selective_export['meta']); selective_meta = json.loads(metadata.read_text(encoding='utf-8'))
        check(selective_meta['params']['accent_rules'][0]['region'] == [0,0,.5,1] and selective_meta['validate']['pass'],
              '抽色导出保存选色、框选与验收结果')
        Path(selective_export['png']).unlink(); metadata.unlink()

        from test_color_regressions import painted_rules
        paint_params = {**selective_params, 'accent_rules': painted_rules(True)}
        with post_json('/api/render', {'id': selective_id, 'params': paint_params}) as r:
            painted_art = np.asarray(Image.open(io.BytesIO(r.read())).convert('RGB'))
        paint_count = int((np.ptp(painted_art.astype(int), axis=2)>8).sum())
        check(0 < paint_count < 120, '服务版画笔和擦除遮罩共同限制抽色区域')
        with post_json('/api/export', {'id': selective_id, 'params': paint_params, 'name': '_api_paint_test'}) as r:
            painted_export = json.loads(r.read())
        painted_meta_path = Path(painted_export['meta'])
        painted_meta = json.loads(painted_meta_path.read_text(encoding='utf-8'))
        strokes = painted_meta['params']['accent_rules'][0]['paint_mask']['strokes']
        check(len(strokes) == 2 and strokes[1]['erase'] and painted_meta['validate']['pass'], '服务版导出记录完整笔画和擦除操作')
        Path(painted_export['png']).unlink(); painted_meta_path.unlink()
        with post_json('/api/render', {'id': selective_id, 'params': {**selective_params,
                'accent_rules': [{**rules()[0], 'min_size':121}]}}) as r:
            filtered = np.asarray(Image.open(io.BytesIO(r.read())).convert('RGB'))
        check(not np.any(np.ptp(filtered.astype(int), axis=2)>8), '服务版大于64的连通区域阈值生效')
        whitebuf=io.BytesIO(); Image.fromarray(np.full((16,16,3), [251,253,255], dtype=np.uint8)).save(whitebuf,format='PNG')
        with post_raw('/api/upload',whitebuf.getvalue()) as r:
            white_id=json.loads(r.read())['id']
        with post_json('/api/render',{'id':white_id,'params':{'color_mode':True,'brightness':-70,'color_levels':4}}) as r:
            darkwhite=np.asarray(Image.open(io.BytesIO(r.read())).convert('RGB'))
        check(not np.any(np.ptp(darkwhite.astype(int),axis=2)), '服务版近白背景降低亮度后不染色')

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
