// 真实浏览器**交互**测试：通过 CDP（Chrome DevTools Protocol）驱动无头浏览器，
// 模拟真实点击、滚轮、文件注入，验证交互逻辑。
//
// 设计上把**所有交互合并进一次 Runtime.evaluate**：一次连接、一次执行完所有步骤、
// 一次性返回全部结果 —— 避免多次 evaluate 之间页面重载导致
// "Execution context was destroyed"。
//
// 运行（需要服务已在 8760 运行）：
//   node tests/interact.mjs http://127.0.0.1:8760 <图片路径>
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const HOST = process.argv[2] || 'http://127.0.0.1:8760';
const IMG = process.argv[3];
const EDGE = process.argv[4] || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

let pass = 0;
let fail = 0;
const ok = (m) => { console.log('  [PASS] ' + m); pass++; };
const bad = (m) => { console.log('  [FAIL] ' + m); fail++; };
const check = (c, m, x = '') => (c ? ok(m) : bad(m + (x ? ' —— ' + x : '')));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function evalInPage(wsUrl, expression) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let seq = 0;
    const timer = setTimeout(() => { try { ws.close(); } catch {} reject(new Error('evaluate 超时')); }, 120000);
    ws.addEventListener('open', () => {
      seq++;
      ws.send(JSON.stringify({
        id: seq, method: 'Runtime.evaluate',
        params: { expression, awaitPromise: true, returnByValue: true },
      }));
    });
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === seq) {
        clearTimeout(timer);
        ws.close();
        if (m.error) reject(new Error('CDP error: ' + JSON.stringify(m.error)));
        else if (m.result && m.result.exceptionDetails) {
          reject(new Error((m.result.exceptionDetails.exception?.description || m.result.exceptionDetails.text)));
        } else resolve(m.result?.result?.value);
      }
    });
    ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('WebSocket 错误')); });
  });
}

async function getPageWs(port) {
  const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = list.find((t) => t.type === 'page' && t.url.includes('127.0.0.1'));
  return page ? page.webSocketDebuggerUrl : null;
}

// evaluate 带重试：页面导航中执行上下文会被销毁（Execution context was destroyed），
// 此时重新拿最新 target、重连、重试。
async function evalRetry(port, expr, tries = 6) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    const url = await getPageWs(port);
    if (!url) { await sleep(1500); continue; }
    try {
      return await evalInPage(url, expr);
    } catch (e) {
      lastErr = e;
      if (/destroyed|context/i.test(e.message)) { await sleep(2500); continue; }
      throw e;
    }
  }
  throw lastErr || new Error('多次重试后仍无法连接页面');
}

async function main() {
  if (!fs.existsSync(EDGE)) { console.log('[SKIP] 本机没有 Edge'); return 0; }
  if (!IMG || !fs.existsSync(IMG)) { console.log('[SKIP] 缺少样例图片'); return 0; }

  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'px_cdp_'));
  const edge = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    `--user-data-dir=${prof}`, '--remote-debugging-port=0', HOST + '/',
  ], { stdio: 'ignore' });

  let wsUrl = null;
  let port = null;
  for (let i = 0; i < 100 && !wsUrl; i++) {
    await sleep(400);
    try {
      const pf = path.join(prof, 'DevToolsActivePort');
      if (fs.existsSync(pf)) port = fs.readFileSync(pf, 'utf8').split(/\r?\n/)[0].trim();
      if (port) {
        const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page = list.find((t) => t.type === 'page' && t.url.includes('127.0.0.1'));
        if (page) wsUrl = page.webSocketDebuggerUrl;
      }
    } catch { /* 还没就绪 */ }
  }
  if (!wsUrl) { console.log('[FAIL] 无法连接 CDP'); edge.kill(); return 1; }
  ok('CDP 连接成功');
  await sleep(3000);   // 等页面加载稳定

  const b64 = fs.readFileSync(IMG).toString('base64');

  try {
    const r = await evalRetry(port, `(async () => {
      await new Promise(rr => { const chk = () => document.getElementById('file') ? rr() : setTimeout(chk, 200); chk(); });
      const bin = Uint8Array.from(atob('${b64}'), c => c.charCodeAt(0));
      const file = new File([bin], 't.png', { type: 'image/png' });
      const dt = new DataTransfer();
      dt.items.add(file);
      const input = document.getElementById('file');
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      await new Promise(rr => setTimeout(rr, 6000));

      const R = {};
      R.loaded = document.getElementById('img-result').src.startsWith('blob:');
      R.size = document.getElementById('st-size').textContent;
      R.check = document.getElementById('st-check').textContent;
      R.warn = document.getElementById('st-warn').textContent;

      document.querySelector('#view-mode button[data-v="original"]').click();
      R.cls1 = document.getElementById('views').className;
      R.act1 = document.querySelector('#view-mode button.on')?.dataset.v;
      R.fitActive1 = document.querySelector('#zoom button.on')?.dataset.z;

      document.querySelector('#view-mode button[data-v="split"]').click();
      R.splitResH = document.getElementById('img-result').offsetHeight;
      R.splitOrigH = document.getElementById('img-original').offsetHeight;

      document.querySelector('#view-mode button[data-v="result"]').click();
      R.act2 = document.querySelector('#view-mode button.on')?.dataset.v;

      const img = document.getElementById('img-result');
      R.naturalW = img.naturalWidth;
      document.querySelector('#zoom button[data-z="4"]').click();
      R.w4 = img.style.width;
      document.querySelector('#zoom button[data-z="1"]').click();
      R.w1 = img.style.width;
      R.zoomAct = document.querySelector('#zoom button.on')?.dataset.z;

      const wrap = document.getElementById('canvas-wrap');
      wrap.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, bubbles: true, cancelable: true }));
      R.wheelUp = img.style.width;
      wrap.dispatchEvent(new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true }));
      wrap.dispatchEvent(new WheelEvent('wheel', { deltaY: 120, bubbles: true, cancelable: true }));
      R.wheelDown = img.style.width;

      // 放大到 8x 后左键拖动平移
      document.querySelector('#zoom button[data-z="8"]').click();
      const st0 = wrap.scrollTop;
      R.scrollH = wrap.scrollHeight;
      R.clientH = wrap.clientHeight;
      wrap.dispatchEvent(new MouseEvent('mousedown', { button: 0, clientX: 300, clientY: 400, bubbles: true, cancelable: true }));
      R.cursorDown = wrap.style.cursor;
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 300, clientY: 200, bubbles: true }));
      window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      R.dragDy = wrap.scrollTop - st0;
      R.cursorUp = wrap.style.cursor;

      const ps = document.getElementById('preset');
      const f = () => document.querySelector('.field[data-k="factor"] input')?.value;
      ps.value = 'scene'; ps.dispatchEvent(new Event('change', { bubbles: true }));
      R.scene = f();
      ps.value = 'character'; ps.dispatchEvent(new Event('change', { bubbles: true }));
      R.char = f();

      return R;
    })()`);

    check(r.loaded === true, '注入图片后成品已渲染（blob 源）');
    check(/160x240/.test(r.size), `尺寸指示正确：${r.size}`, r.size);
    check(/验收 ✓/.test(r.check), `验收状态显示通过：${r.check}`, r.check);
    check(r.warn === '', '无报错提示', r.warn);

    check(/original/.test(r.cls1), '点「原图」后视图切换', r.cls1);
    check(r.act1 === 'original' && r.act2 === 'result', '视图按钮高亮跟随', `act1=${r.act1} act2=${r.act2}`);
    check(r.fitActive1 === 'fit', '点「原图」后自动回到适应', String(r.fitActive1));
    check(Math.abs(r.splitResH - r.splitOrigH) <= 2, `并排时原图与成品等高（${r.splitResH} vs ${r.splitOrigH}）`, `${r.splitResH} vs ${r.splitOrigH}`);

    check(r.w4 === (r.naturalW * 4) + 'px', `4x 缩放生效（${r.w4}）`, r.w4);
    check(r.w1 === String(r.naturalW) + 'px', `1x 缩放生效（${r.w1}）`, r.w1);
    check(r.zoomAct === '1', '缩放按钮高亮跟随', String(r.zoomAct));

    check(r.wheelUp !== r.w1, `滚轮向上滚 → 放大（${r.w1} → ${r.wheelUp}）`, `${r.w1} → ${r.wheelUp}`);
    check(r.wheelDown !== r.wheelUp, `滚轮向下滚 → 缩小（${r.wheelUp} → ${r.wheelDown}）`, `${r.wheelUp} → ${r.wheelDown}`);
    check(r.dragDy > 0, `左键拖动平移生效（scrollTop 变化 ${r.dragDy}px）`, `scrollH=${r.scrollH} clientH=${r.clientH} cursorDown=${r.cursorDown} cursorUp=${r.cursorUp}`);

    check(r.scene === '2', '场景预设把缩小倍数设为 2', String(r.scene));
    check(r.char === '4', '角色预设把缩小倍数设为 4', String(r.char));
  } catch (e) {
    bad('交互测试异常：' + e.message);
  } finally {
    edge.kill();
    await sleep(1500);
    try { fs.rmSync(prof, { recursive: true, force: true }); } catch { /* EPERM 忽略 */ }
  }

  console.log(`\n通过 ${pass} / 失败 ${fail}`);
  return fail ? 1 : 0;
}

main().then((code) => process.exit(code));
