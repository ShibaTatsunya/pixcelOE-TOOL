# -*- coding: utf-8 -*-
"""HTTP API 与静态页面服务。

只用标准库（``http.server`` / ``json`` / ``PIL`` / ``numpy``），不引入 Flask 等依赖，
保证这个工具拷到任何装了 Python + Pillow + numpy 的机器上都能直接跑。

接口
----
============================ ==========================================
``GET  /``                    前端页面
``GET  /web/<file>``          前端静态资源
``GET  /api/meta``            调色板、策略说明等元信息
``POST /api/upload``          上传图片（请求体为图片二进制），返回 ``{id,w,h}``
``GET  /api/original?id=``    取回原图 PNG（前端做对比用）
``POST /api/render``          转换，直接返回 PNG；统计数字放在响应头
``POST /api/report``          同一组参数的完整报告（JSON，含 4 项验收）
``POST /api/export``          把结果与元数据落盘到 ``outputs/``
============================ ==========================================
"""
from __future__ import annotations

import io
import json
import time
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
from PIL import Image

from core.palette import KINDS, gray_hex, load_palette
from core.algorithm import DOWNSAMPLE_HELP, DOWNSAMPLE_MODES
from core.pipeline import MAX_PIXELS, ExpandCache, Params, convert
from core.validate import validate

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
OUT_DIR = ROOT / "outputs"

MAX_UPLOAD_BYTES = 64 * 1024 * 1024       # 单张上传上限
MAX_IMAGES = 8                            # 内存里最多留几张原图
MAX_RENDERS = 4                           # 渲染结果缓存条数

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class App:
    """进程内的状态：原图、渲染缓存、调色板。"""

    def __init__(self) -> None:
        self.palette = load_palette()
        self.images: OrderedDict[str, np.ndarray] = OrderedDict()
        self.renders: OrderedDict[tuple, dict] = OrderedDict()
        self.expand_cache = ExpandCache(maxsize=3)
        self.lock = threading.Lock()

    # ---- 原图 ----
    def put_image(self, arr: np.ndarray) -> str:
        iid = uuid.uuid4().hex[:12]
        with self.lock:
            self.images[iid] = arr
            while len(self.images) > MAX_IMAGES:
                self.images.popitem(last=False)
        return iid

    def get_image(self, iid: str) -> np.ndarray:
        arr = self.images.get(iid)
        if arr is None:
            raise KeyError(f"图片不存在或已被回收：{iid}（请重新上传）")
        return arr

    # ---- 渲染（带缓存，让 /api/render 与 /api/report 共享同一次计算）----
    def render(self, iid: str, params: Params) -> dict:
        key = (iid, json.dumps(params.to_dict(), sort_keys=True, ensure_ascii=False))
        with self.lock:
            if key in self.renders:
                self.renders.move_to_end(key)
                return self.renders[key]
            arr = self.get_image(iid)
            res = convert(arr, params, self.palette, self.expand_cache)
            report = validate(
                res.final,
                params.palette_kind,
                self.palette,
                canvas=params.canvas,
                extra_colors=[],
            )
            entry = {"result": res, "report": report, "params": params, "t": time.time()}
            self.renders[key] = entry
            while len(self.renders) > MAX_RENDERS:
                self.renders.popitem(last=False)
            return entry


APP = App()


def _png_bytes(arr: np.ndarray, preview: int = 0) -> bytes:
    im = Image.fromarray(arr.astype(np.uint8), "RGB")
    if preview > 1:
        im = im.resize((im.width * preview, im.height * preview), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "pixcelOE/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 工具方法 ----
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return b""
        if n > MAX_UPLOAD_BYTES:
            raise ValueError(f"请求体过大（{n / 1048576:.1f} MB），上限 {MAX_UPLOAD_BYTES // 1048576} MB")
        return self.rfile.read(n)

    def _json_body(self) -> dict:
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def log_message(self, fmt, *args):  # 静音默认日志，避免刷屏
        pass

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/web/"):
                return self._static(path[len("/web/"):])
            if path == "/api/meta":
                return self._meta()
            if path == "/api/original":
                qs = parse_qs(urlparse(self.path).query)
                iid = (qs.get("id") or [""])[0]
                arr = APP.get_image(iid)
                return self._send(200, _png_bytes(arr), "image/png")
            return self._err(404, f"未知路径：{path}")
        except KeyError as e:
            return self._err(404, str(e))
        except Exception as e:  # noqa: BLE001
            return self._err(500, f"{type(e).__name__}: {e}")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                return self._upload()
            if path == "/api/render":
                return self._render()
            if path == "/api/report":
                return self._report()
            if path == "/api/export":
                return self._export()
            return self._err(404, f"未知路径：{path}")
        except KeyError as e:
            return self._err(404, str(e))
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:  # noqa: BLE001
            return self._err(500, f"{type(e).__name__}: {e}")

    # ---- 各接口 ----
    def _static(self, rel: str) -> None:
        p = (WEB_DIR / rel).resolve()
        if not str(p).startswith(str(WEB_DIR.resolve())) or not p.is_file():
            return self._err(404, f"找不到资源：{rel}")
        self._send(200, p.read_bytes(), MIME.get(p.suffix.lower(), "application/octet-stream"))

    def _meta(self) -> None:
        pal = APP.palette
        self._json({
            "downsample": [{"value": m, "help": DOWNSAMPLE_HELP.get(m, "")} for m in DOWNSAMPLE_MODES],
            "kinds": list(KINDS),
            "palette": {k: gray_hex(pal, k) for k in KINDS},
            "accent_reference": pal.get("accent", {}).get("area_ratio_reference_range"),
            "limits": {"max_upload_mb": MAX_UPLOAD_BYTES // 1048576, "max_pixels": MAX_PIXELS},
            "expanded_cache": {"hits": APP.expand_cache.hits, "misses": APP.expand_cache.misses},
        })

    def _upload(self) -> None:
        raw = self._body()
        if not raw:
            return self._err(400, "请求体为空")
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
        except Exception as e:  # noqa: BLE001
            return self._err(400, f"无法解码图片：{e}")
        if im.width * im.height > MAX_PIXELS:
            return self._err(400, f"图片过大（{im.width}x{im.height}），上限 {MAX_PIXELS:,} 像素")
        arr = np.asarray(im.convert("RGB"))
        iid = APP.put_image(arr)
        self._json({"id": iid, "width": arr.shape[1], "height": arr.shape[0],
                    "name": Path(getattr(im, "filename", "") or "").name})

    def _params(self, d: dict, iid: str) -> tuple[str, Params]:
        iid = d.get("id") or iid
        if not iid:
            raise ValueError("缺少图片 id（请先上传图片）")
        return iid, Params.from_dict(d.get("params") or {})

    def _render(self) -> None:
        d = self._json_body()
        iid, params = self._params(d, "")
        entry = APP.render(iid, params)
        res = entry["result"]
        preview = int(d.get("preview") or 0)
        body = _png_bytes(res.final, preview)
        rep = entry["report"]
        self._send(200, body, "image/png", {
            "X-Render-Ms": f"{res.timings['total']:.1f}",
            "X-Expand-Cached": "1" if res.cached_expand else "0",
            "X-Out-Size": f"{res.final.shape[1]}x{res.final.shape[0]}",
            "X-Unique-Colors": rep["details"]["unique_colors"],
            "X-Check-Pass": "1" if rep["pass"] else "0",
            "Access-Control-Expose-Headers": "*",
        })

    def _report(self) -> None:
        d = self._json_body()
        iid, params = self._params(d, "")
        entry = APP.render(iid, params)
        res, rep = entry["result"], entry["report"]
        self._json({
            "params": params.to_dict(),
            "input_size": list(res.input_size),
            "output_size": [res.final.shape[1], res.final.shape[0]],
            "timings": res.timings,
            "cached_expand": res.cached_expand,
            "warned": res.warned,
            "validate": rep,
        })

    def _export(self) -> None:
        d = self._json_body()
        iid, params = self._params(d, "")
        entry = APP.render(iid, params)
        res, rep = entry["result"], entry["report"]
        stem = str(d.get("name") or "").strip() or f"pixel_{int(time.time())}"
        stem = "".join(c for c in stem if c not in '\\/:*?"<>|').strip() or "pixel"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        png = OUT_DIR / f"{stem}.png"
        meta = OUT_DIR / f"{stem}.json"
        scale = max(1, min(8, int(d.get("scale") or 1)))
        png.write_bytes(_png_bytes(res.final, scale))
        meta.write_text(json.dumps({
            "tool": "pixcelOE 1.0",
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source_image": iid,
            "scale": scale,
            "params": params.to_dict(),
            "output_size": [res.final.shape[1], res.final.shape[0]],
            "timings_ms": res.timings,
            "validate": rep,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        self._json({"png": str(png), "meta": str(meta), "pass": rep["pass"]})


def run(host: str = "127.0.0.1", port: int = 8760, quiet: bool = False) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    if not quiet:
        print("=" * 66)
        print("  pixcelOE —— 图片转像素图工具")
        print(f"  已启动：http://{host}:{port}")
        print("  关闭：在本窗口按 Ctrl+C")
        print("=" * 66)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
