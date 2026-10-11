# -*- coding: utf-8 -*-
"""pixcelOE 启动入口：起一个本地网页服务，并自动打开浏览器。

用法::

    python app.py                  # 默认 127.0.0.1:8760，自动开浏览器
    python app.py --port 9000
    python app.py --no-browser     # 只起服务，不自动开浏览器

依赖：Python 3.9+、numpy、Pillow（无其它第三方依赖）。
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.api import run  # noqa: E402


def pick_port(preferred: int) -> int:
    """优先用 ``preferred``；被占用则顺延，最多试 20 个端口。"""
    for p in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return preferred


def main() -> int:
    ap = argparse.ArgumentParser(description="pixcelOE —— 图片转像素图工具")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认只监听本机）")
    ap.add_argument("--port", type=int, default=8760, help="端口（默认 8760）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    port = pick_port(args.port)
    if port != args.port:
        print(f"提示：端口 {args.port} 被占用，改用 {port}")
    url = f"http://{args.host}:{port}"
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    run(args.host, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
