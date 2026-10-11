# -*- coding: utf-8 -*-
"""真实浏览器冒烟测试（无头 Edge / Chrome）。

不需要任何第三方驱动：直接调用本机浏览器的 headless 模式，用
``--dump-dom`` 拿到 **JS 执行之后** 的 DOM，用 ``--screenshot`` 拿到真实渲染结果。

这一层覆盖的是纯静态检查（test_web_assets.py）碰不到的东西：

  * ``app.js`` 到底有没有成功执行 —— ``#controls`` 在 HTML 里是空 div，
    里面的控件全部由 JS 生成，DOM dump 出来是空的就说明脚本挂了；
  * 控件数量、分组标题、下拉选项是否符合预期；
  * 浏览器控制台是否抛了 JS 异常（``Uncaught`` / ``is not defined`` / ``ReferenceError``）；
  * 页面是否真的画出了东西（截图字节数、尺寸）。

本机没装 Edge / Chrome 时记为 SKIP，不算失败。

运行：
    python tests/test_browser.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

PASS: list[str] = []
FAIL: list[str] = []
SKIP: list[str] = []


def ok(msg: str) -> None:
    PASS.append(msg)


def bad(msg: str) -> None:
    FAIL.append(msg)


def skip(msg: str) -> None:
    SKIP.append(msg)


def check(cond: bool, msg: str, extra: str = "") -> None:
    (ok if cond else bad)(msg + ("" if cond else f" —— {extra}"))


# ---------------------------------------------------------------- 服务

def wait_up(timeout: float = 40.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(BASE + "/api/meta", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


# ---------------------------------------------------------------- 浏览器

def find_browser() -> str | None:
    for p in BROWSERS:
        if Path(p).is_file():
            return p
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_browser(exe: str, args: list[str], timeout: float = 180.0) -> subprocess.CompletedProcess:
    """headless 跑一次浏览器，DOM 走 stdout，日志走 stderr。"""
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run",
           "--disable-extensions", "--disable-sync", "--no-default-browser-check",
           *args]
    return subprocess.run(cmd, capture_output=True, timeout=timeout)  # noqa: S603


# ---------------------------------------------------------------- 主流程

def main() -> int:
    exe = find_browser()
    if not exe:
        skip("本机没有找到 Edge / Chrome，跳过浏览器冒烟测试")
        report()
        return 0
    ok(f"找到浏览器：{Path(exe).name}")

    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(ROOT / "app.py"), "--port", str(PORT), "--no-browser"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    tmp = Path(tempfile.mkdtemp(prefix="pixceloe_browser_"))
    try:
        if not wait_up():
            bad("服务未能在 40 秒内启动")
            report()
            return 1
        ok("测试服务已启动")

        profile = tmp / "profile"
        profile.mkdir()

        # ---- 1. dump-dom：JS 执行后的 DOM ----
        r = run_browser(exe, [
            f"--user-data-dir={profile}",
            "--virtual-time-budget=8000",
            "--window-size=1600,1000",
            "--dump-dom", BASE + "/",
        ])
        dom = r.stdout.decode("utf-8", "replace")
        log = r.stderr.decode("utf-8", "replace")

        check(len(dom) > 2000, f"取回渲染后的 DOM（{len(dom)} 字符）")

        # JS 是否真的跑起来了：#controls 原本是空的
        m = re.search(r'<div id="controls"[^>]*>(.*?)</div>\s*</aside>', dom, re.S)
        inner = m.group(1) if m else ""
        check(len(inner) > 1500, f"#controls 被 JS 填充（{len(inner)} 字符）",
              "为空说明 app.js 没执行")

        # 控件与分组
        n_ctl = len(re.findall(r'class="field"', dom))
        check(n_ctl >= 12, f"参数控件渲染出 {n_ctl} 个（预期 >= 12）")
        titles = ['① 输入与明暗', '② 分层', '③ 轮廓与线条', '④ 像素块大小', '⑤ 颜色']
        missing = [t for t in titles if t not in dom]
        check(not missing, f"参数分组渲染出 {len(titles) - len(missing)}/{len(titles)} 组", '缺失：' + ','.join(missing))

        # 关键元素
        for eid in ("view-mode", "zoom", "preset", "drop-hint", "canvas-wrap",
                    "st-check", "btn-export", "btn-batch"):
            check(f'id="{eid}"' in dom, f"页面元素 #{eid} 存在")

        # 下拉选项（含来自 /api/meta 的降采样策略）
        n_opt = len(re.findall(r"<option", dom))
        check(n_opt >= 5, f"下拉选项渲染出 {n_opt} 个")

        # ---- 2. 控制台错误扫描 ----
        errs = [ln.strip() for ln in log.splitlines()
                if re.search(r"Uncaught|ReferenceError|is not defined|SyntaxError"
                             r"|Unhandled|net::ERR", ln)]
        check(not errs, "浏览器控制台无 JS 异常", " | ".join(errs[:3]))

        # 页面自身抛出的错误（Edge 的噪声日志按前缀排除）
        noisy = ("task_manager", "importer", "gpu", "voice_transcription",
                 "device_event_log", "dxdiag", "GetHandleVerifier")
        real = [e for e in errs if not any(n in e for n in noisy)]
        check(not real, "除浏览器自身噪声外无页面级错误", " | ".join(real[:3]))

        # ---- 3. 截图：真的渲染出像素 ----
        shot = tmp / "page.png"
        r2 = run_browser(exe, [
            f"--user-data-dir={profile}",
            "--virtual-time-budget=8000",
            "--window-size=1600,1000",
            f"--screenshot={shot}", BASE + "/",
        ])
        check(shot.is_file(), "生成了页面截图")
        if shot.is_file():
            size = shot.stat().st_size
            check(size > 20000, f"截图 {size:,} 字节（说明确实渲染出了内容）")
            head = shot.read_bytes()[:8]
            check(head == b"\x89PNG\r\n\x1a\n", "截图是合法 PNG")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    report()
    return 1 if FAIL else 0


def report() -> None:
    print("=" * 78)
    for s in PASS:
        print(f"  [PASS] {s}")
    for s in SKIP:
        print(f"  [SKIP] {s}")
    for s in FAIL:
        print(f"  [FAIL] {s}")
    print("=" * 78)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)} / 跳过 {len(SKIP)}")


if __name__ == "__main__":
    raise SystemExit(main())
