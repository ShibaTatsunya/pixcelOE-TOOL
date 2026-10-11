'use strict';

/* =========================================================================
 * pixcelOE 前端 —— 原生 JS，无框架
 * =======================================================================*/

// 用函数声明而非 const 箭头函数：顶层函数声明会成为 window 属性，
// 这样浏览器控制台里也能直接用 $('...') 调试，且不存在任何作用域盲区。
function $(s) { return document.querySelector(s); }
function $$(s) { return Array.from(document.querySelectorAll(s)); }

/* ---------------- 预设 ---------------- */
const PRESETS = {
  character: {
    posterize_skip: false, desat: 'hsl', gamma: 1, brightness: 0, contrast: 0,
    posterize_levels: 4, color_levels: 12, posterize_mode: 'ps',
    patch: 2, thickness: 1, keep_thin: false,
    factor: 4, downsample: 'bridge', dark_tol: 0.06,
    palette_kind: 'character', quantize_levels: 4, no_quantize: false, dither: 'none', dither_strength: 24,
  },
  scene: {
    posterize_skip: false, desat: 'hsl', gamma: 1, brightness: 0, contrast: 0,
    posterize_levels: 4, color_levels: 12, posterize_mode: 'ps',
    patch: 2, thickness: 1, keep_thin: false,
    factor: 2, downsample: 'bridge', dark_tol: 0.06,
    palette_kind: 'scene', quantize_levels: 0, no_quantize: false, dither: 'none', dither_strength: 24,
  },
};

/* ---------------- 控件定义 ---------------- */
const GROUPS = [
  {
    title: '① 输入与明暗',
    enableKey: 'enable_input',
    items: [
      { k: 'color_mode', t: 'bool', label: '保留彩色（不黑白化）', help: '勾选后跳过黑白化与灰阶分层，保留原图彩色，输出彩色像素图（强调色不再被抽走）。' },
      { k: 'desat', t: 'select', label: '黑白化算法', opts: [['hsl', 'HSL —— 和 PS 一致（推荐）'], ['rec709', 'Rec.709 —— 旧做法，脸会更暗']], help: '决定彩色图怎么变黑白。「HSL」跟 Photoshop 把饱和度拉到底的结果一致。' },
      { k: 'gamma', t: 'range', label: '明暗曲线（Gamma）', min: 0.2, max: 3, step: 0.05, help: '调大 → 整体变暗；调小 → 整体变亮。' },
      { k: 'brightness', t: 'range', label: '整体亮度', min: -150, max: 150, step: 1, help: '正数更亮、负数更暗，等价于 Photoshop 的「亮度」。' },
      { k: 'contrast', t: 'range', label: '整体对比度', min: -50, max: 100, step: 1, help: '调大 → 黑白更分明、细节更锐；调小 → 更柔和。默认 0（中性，不额外调整）。' },
    ],
  },
  {
    title: '② 分层',
    enableKey: 'enable_posterize',
    items: [],
  },
  {
    title: '③ 轮廓与线条',
    enableKey: 'enable_outline',
    items: [
      { k: 'patch', t: 'range', label: '细节敏感度', min: 1, max: 4, step: 1, help: '调大 → 线条更平滑、忽略细小噪点；调小 → 保留更多细节，但可能带出噪点。' },
      { k: 'thickness', t: 'range', label: '线条粗细', min: 0, max: 4, step: 1, help: '调大 → 轮廓更粗更实；0 = 不做轮廓处理。' },
      { k: 'keep_thin', t: 'bool', label: '保留发丝等细线', help: '勾选后睫毛、发丝、衣褶这类 1 像素细线不会在缩小中消失。' },
    ],
  },
  {
    title: '④ 像素块大小',
    enableKey: 'enable_downsample',
    items: [
      { k: 'factor', t: 'range', label: '缩小倍数（像素块粗细）', min: 1, max: 16, step: 1, help: '越大像素块越粗、成品越小。640×960 用 4 就得到 160×240。任意值都能用，无需尺寸整除。' },
      { k: 'downsample', t: 'select', label: '像素块取值方式', opts: '#downsample' },
      { k: 'dark_tol', t: 'range', label: '暗线保留强度', min: 0, max: 0.5, step: 0.01, help: '调大 → 更容易把暗线连起来，但也可能让线变粗。' },
    ],
  },
  {
    title: '⑤ 颜色',
    enableKey: 'enable_quantize',
    items: [
      { k: 'quantize_levels', t: 'range', label: '颜色数（量化档数）', min: 0, max: 8, step: 1, help: '0 = 用整套灰阶；改成 4 表示只在调色板里取 4 档，颜色更少、更统一。' },
      { k: 'no_quantize', t: 'bool', label: '不强制套调色板', help: '保留缩小后的原始颜色（一般不需要勾，勾了颜色会乱）。' },
      { k: 'dither', t: 'select', label: '抖动（dither）', opts: [['none', '不抖动（默认）'], ['bayer4', '4×4 Bayer 有序抖动'], ['bayer8', '8×8 Bayer 有序抖动']], help: '在灰阶过渡处叠加规律纹理，模拟中间调。默认关闭（与产线逐像素一致）。' },
      { k: 'dither_strength', t: 'range', label: '抖动强度', min: 0, max: 100, step: 1, help: '抖动偏移幅度，越大纹理越明显。' },
    ],
  },
];

/* ---------------- 状态 ---------------- */
const state = {
  id: null, srcW: 0, srcH: 0, outW: 0, outH: 0,
  params: { ...PRESETS.character },
  view: 'result', zoom: 'fit', grid: false,
  meta: null, busyCount: 0, timer: null,
  history: [], hIndex: -1,
  files: [],
};

/* ---------------- 小工具 ---------------- */
let toastTimer = null;
function toast(msg, ok = false) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = ok ? 'ok' : '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 4200);
}

function setBusy(on) {
  state.busyCount = Math.max(0, state.busyCount + (on ? 1 : -1));
  $('#busy').classList.toggle('hidden', state.busyCount === 0);
}

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (j && j.error) throw new Error(j.error);
  return j;
}

/* ---------------- 参数面板 ---------------- */
function buildControls() {
  const host = $('#controls');
  host.innerHTML = '';
  for (const g of GROUPS) {
    const sec = document.createElement('div');
    sec.className = 'group';
    const on = state.params[g.enableKey] !== false;
    const label = document.createElement('label');
    label.className = 'step-toggle';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = on;
    cb.addEventListener('change', () => {
      setParam(g.enableKey, cb.checked);
      sec.classList.toggle('off', !cb.checked);
    });
    label.appendChild(cb);
    const span = document.createElement('span');
    span.textContent = g.title;
    label.appendChild(span);
    sec.appendChild(label);
    sec.classList.toggle('off', !on);
    const items = (g.enableKey === 'enable_posterize')
      ? (state.params.color_mode
          ? [{ k: 'color_levels', t: 'range', label: '色彩层数（明度档数）', min: 2, max: 12, step: 1, help: '色相不变，只把彩色像素的明度减少到 N 档，档数越少色阶越简练。' }]
          : [
              { k: 'posterize_levels', t: 'range', label: '灰阶层数', min: 0, max: 8, step: 1, help: '黑白灰像素的明度档数（原版语义）。0 = 不分层；4 层最常用。' },
              { k: 'posterize_mode', t: 'select', label: '分层方式', opts: [['ps', '和 Photoshop 一致（推荐）'], ['palette', '旧做法（按调色板范围）']], help: '「和 PS 一致」按 Photoshop 色调分离的原样分层，是验收通过的默认。' },
            ])
      : g.items;
    for (const it of items) sec.appendChild(buildField(it));
    host.appendChild(sec);
  }
}

function buildField(it) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  wrap.dataset.k = it.k;   // 供测试/调试按参数名定位控件
  const v = state.params[it.k];

  if (it.t === 'bool') {
    const lab = document.createElement('label');
    lab.className = 'chk';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!v;
    cb.addEventListener('change', () => setParam(it.k, cb.checked));
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(' ' + it.label));
    wrap.appendChild(lab);
    if (it.help) wrap.appendChild(helpEl(it.help));
    return wrap;
  }

  const top = document.createElement('div');
  top.className = 'field-top';
  const lab = document.createElement('label');
  lab.textContent = it.label;
  top.appendChild(lab);

  if (it.t === 'range') {
    const val = document.createElement('span');
    val.className = 'val';
    val.textContent = fmt(v);
    top.appendChild(val);
    wrap.appendChild(top);

    const inp = document.createElement('input');
    inp.type = 'range';
    inp.min = it.min; inp.max = it.max; inp.step = it.step; inp.value = v;
    inp.addEventListener('input', () => {
      val.textContent = fmt(parseFloat(inp.value));
      setParam(it.k, parseFloat(inp.value));
    });
    wrap.appendChild(inp);
  } else if (it.t === 'select') {
    wrap.appendChild(top);
    const sel = document.createElement('select');
    let opts = it.opts;
    if (opts === '#downsample') {
      opts = (state.meta ? state.meta.downsample : []).map((d) => [d.value, d.value + ' —— ' + d.help]);
    }
    for (const [value, text] of opts) {
      const o = document.createElement('option');
      o.value = value;
      o.textContent = text;
      if (value === v) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener('change', () => setParam(it.k, sel.value));
    wrap.appendChild(sel);
  } else {
    wrap.appendChild(top);
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = v == null ? '' : v;
    inp.addEventListener('change', () => setParam(it.k, inp.value.trim() || null));
    wrap.appendChild(inp);
  }

  if (it.help) wrap.appendChild(helpEl(it.help));
  return wrap;
}

function helpEl(text) {
  const d = document.createElement('div');
  d.className = 'help';
  d.textContent = text;
  return d;
}

function fmt(v) {
  if (typeof v !== 'number') return String(v);
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function pushHistory() {
  const cur = JSON.stringify(state.params);
  const top = state.hIndex >= 0 ? JSON.stringify(state.history[state.hIndex]) : null;
  if (cur === top) return;
  state.history = state.history.slice(0, state.hIndex + 1);
  state.history.push({ ...state.params });
  state.hIndex++;
  if (state.history.length > 50) { state.history.shift(); state.hIndex--; }
  refreshHistButtons();
}

function setParam(k, value) {
  state.params[k] = value;
  $('#preset').value = 'custom';
  pushHistory();
  scheduleRender();
}

function undo() {
  if (state.hIndex <= 0) return;
  state.hIndex--;
  state.params = { ...state.history[state.hIndex] };
  buildControls();
  scheduleRender();
  refreshHistButtons();
}

function redo() {
  if (state.hIndex >= state.history.length - 1) return;
  state.hIndex++;
  state.params = { ...state.history[state.hIndex] };
  buildControls();
  scheduleRender();
  refreshHistButtons();
}

function refreshHistButtons() {
  const u = $('#btn-undo');
  const r = $('#btn-redo');
  if (u) u.disabled = state.hIndex <= 0;
  if (r) r.disabled = state.hIndex >= state.history.length - 1;
}

function scheduleRender() {
  clearTimeout(state.timer);
  state.timer = setTimeout(renderNow, 260);
}

/* ---------------- 上传 ---------------- */
async function upload(file) {
  if (!file) return;
  setBusy(true);
  try {
    const r = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    state.id = j.id;
    state.srcW = j.width;
    state.srcH = j.height;
    $('#img-original').src = '/api/original?id=' + j.id;
    $('#drop-hint').classList.add('hidden');
    $('#views').classList.remove('hidden');
    setExportEnabled(true);
    toast(`已载入 ${j.width}×${j.height}`, true);
  } catch (e) {
    toast('上传失败：' + e.message);
  } finally {
    setBusy(false);
  }
  if (state.id) await renderNow();
}

/* ---------------- 渲染 ---------------- */
async function renderNow() {
  if (!state.id) return;
  setBusy(true);
  try {
    const body = { id: state.id, params: state.params };
    const r = await fetch('/api/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
      throw new Error(j.error || 'HTTP ' + r.status);
    }
    const blob = await r.blob();
    const img = $('#img-result');
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    const url = URL.createObjectURL(blob);
    img.dataset.url = url;
    img.src = url;

    const size = r.headers.get('X-Out-Size') || '';
    if (size) [state.outW, state.outH] = size.split('x').map(Number);
    $('#st-size').textContent = `${state.srcW}×${state.srcH} → ${size}`;
    $('#st-time').textContent = `耗时 ${r.headers.get('X-Render-Ms')} ms`;
    $('#st-cache').textContent = r.headers.get('X-Expand-Cached') === '1' ? '轮廓扩展：缓存命中' : '轮廓扩展：已重算';
    $('#st-warn').textContent = '';

    applyView();
    await refreshReport();
  } catch (e) {
    $('#st-warn').textContent = e.message;
    toast(e.message);
  } finally {
    setBusy(false);
  }
}

async function refreshReport() {
  try {
    const j = await api('/api/report', { id: state.id, params: state.params });
    renderReport(j);
    if (j.warned && j.warned.length) $('#st-warn').textContent = j.warned.join('；');
  } catch (e) {
    /* 报告失败不阻塞主流程 */
  }
}

function renderReport(j) {
  const v = j.validate;
  const el = $('#st-check');
  if (!el) return;
  const passN = v.checks.filter((c) => c.pass).length;
  const totalN = v.checks.length;
  el.textContent = v.pass ? `验收 ✓ ${passN}/${totalN}` : `验收 ✗ ${passN}/${totalN}`;
  el.className = v.pass ? 'ok' : 'bad';
}

/* ---------------- 视图 / 缩放 / 网格 ---------------- */
function applyView() {
  const views = $('#views');
  views.className = 'views ' + state.view;
  $$('#view-mode button').forEach((b) => b.classList.toggle('on', b.dataset.v === state.view));
  applyZoom();
}

function applyZoom() {
  const oImg = $('#img-original');
  const rImg = $('#img-result');
  if (!rImg.naturalWidth && !state.outW) return;

  const wrap = $('#canvas-wrap');
  const availH = wrap.clientHeight - 60;
  const availW = wrap.clientWidth - 60;
  const gap = 16;

  // 成品缩放 zR、原图缩放 zO（各自独立；并排时按「等高」对齐）
  let zR, zO;
  if (state.zoom === 'fit') {
    if (state.view === 'split') {
      // 并排：两张等高、整体适应窗口
      const h = Math.min(availH, (availW - gap) / (state.outW / state.outH + state.srcW / state.srcH));
      zR = h / state.outH;
      zO = h / state.srcH;
    } else if (state.view === 'original') {
      zO = Math.min(availH / state.srcH, availW / state.srcW);
      zR = zO;
    } else {
      zR = Math.min(availH / state.outH, availW / state.outW);
      zO = zR;
    }
  } else {
    const zi = Number(state.zoom);   // 手动按钮 / 滚轮：整数倍
    if (state.view === 'split') {
      zR = zi;
      zO = zi * (state.outH / state.srcH);   // 原图缩到与成品等高
    } else {
      zR = zi;
      zO = zi;
    }
  }

  // 滚轮依据：当前视图主图的缩放
  state.effZ = (state.view === 'original') ? zO : zR;

  rImg.style.width = state.outW * zR + 'px';
  rImg.style.height = state.outH * zR + 'px';
  oImg.style.width = state.srcW * zO + 'px';
  oImg.style.height = state.srcH * zO + 'px';

  const showZ = (state.view === 'original') ? zO : zR;
  const zLabel = Number.isInteger(showZ) ? `${showZ}×` : `${showZ.toFixed(2)}× 适应`;
  tag(rImg, `${state.outW}×${state.outH} · ${zLabel}`);
  tag(oImg, `${state.srcW}×${state.srcH}`);

  // 网格叠加：只在成品整数倍时对齐显示
  let g = $('#view-result .grid-overlay');
  if (!g) {
    g = document.createElement('div');
    g.className = 'grid-overlay';
    g.style.backgroundImage =
      'linear-gradient(to right, rgba(124,108,255,.30) 1px, transparent 1px),' +
      'linear-gradient(to bottom, rgba(124,108,255,.30) 1px, transparent 1px)';
    $('#view-result').appendChild(g);
  }
  g.style.backgroundSize = `${Math.max(1, Math.round(zR))}px ${Math.max(1, Math.round(zR))}px`;
  g.style.display = (state.grid && Number.isInteger(zR)) ? 'block' : 'none';
}

function tag(view, text) {
  let t = view.querySelector('.tag');
  if (!t) {
    t = document.createElement('span');
    t.className = 'tag';
    view.appendChild(t);
  }
  t.textContent = text;
}

/* ---------------- 导出 ---------------- */
function setExportEnabled(on) {
  $('#btn-export').disabled = !on;
}

async function doExport() {
  if (!state.id) return;
  try {
    const name = prompt('导出文件名（不含扩展名）：', `pixel_${Date.now()}`);
    if (name == null) return;   // 用户取消
    const scaleRaw = prompt('放大倍数（1/2/4/8，默认 4）：', '4');
    const scale = Math.max(1, Math.min(8, parseInt(scaleRaw, 10) || 4));
    const j = await api('/api/export', {
      id: state.id,
      params: state.params,
      name,
      scale,
    });
    toast(j.pass ? '已保存（验收通过）：' + j.png : '已保存（验收未通过）：' + j.png, j.pass);
  } catch (e) {
    toast('导出失败：' + e.message);
  }
}

async function batchExport() {
  if (!state.files || state.files.length === 0) {
    toast('请先选择多张图片');
    return;
  }
  const prefix = prompt('批量导出文件名前缀：', 'batch');
  if (!prefix || !prefix.trim()) return;
  const scaleRaw = prompt('放大倍数（1/2/4/8，默认 4）：', '4');
  const scale = Math.max(1, Math.min(8, parseInt(scaleRaw, 10) || 4));
  const total = state.files.length;
  let done = 0, failed = 0;
  setBusy(true);
  try {
    for (let i = 0; i < total; i++) {
      const up = await (await fetch('/api/upload', {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: state.files[i],
      })).json();
      if (up.error) { failed++; continue; }
      await api('/api/export', { id: up.id, params: state.params, name: `${prefix.trim()}_${i + 1}`, scale });
      done++;
      toast(`批量导出 ${done}/${total}`, true);
    }
    toast(`批量导出完成：成功 ${done}，失败 ${failed}`, done === total);
  } catch (e) {
    toast('批量导出失败：' + e.message);
  } finally {
    setBusy(false);
  }
}

/* ---------------- 事件绑定 ---------------- */
function bind() {
  $('#btn-pick').addEventListener('click', () => $('#file').click());
  $('#file').addEventListener('change', (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    state.files = files;
    upload(files[0]);
    if (files.length > 1) toast(`已载入 ${files.length} 张图，可点「批量导出」`, true);
  });

  const hint = $('#drop-hint');
  hint.addEventListener('click', (e) => {
    if (e.target.id !== 'btn-pick') $('#file').click();
  });
  ['dragenter', 'dragover'].forEach((ev) =>
    window.addEventListener(ev, (e) => {
      e.preventDefault();
      hint.classList.add('over');
    })
  );
  ['dragleave', 'drop'].forEach((ev) =>
    window.addEventListener(ev, (e) => {
      e.preventDefault();
      if (ev === 'drop' || e.target === document || !e.relatedTarget) hint.classList.remove('over');
    })
  );
  window.addEventListener('drop', (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) {
      state.files = Array.from(files);
      upload(files[0]);
      if (files.length > 1) toast(`已载入 ${files.length} 张图，可点「批量导出」`, true);
    }
  });

  $('#preset').addEventListener('change', (e) => {
    applyPreset(e.target.value);
  });

  $('#btn-save-preset').addEventListener('click', saveCurrentPreset);

  $('#btn-reset').addEventListener('click', () => {
    $('#preset').value = 'character';
    state.params = { ...PRESETS.character };
    buildControls();
    scheduleRender();
  });

  $('#view-mode').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    state.view = b.dataset.v;
    state.zoom = 'fit';   // 切换视图时回到适应，当前视图立即以最优尺寸显示
    $$('#zoom button').forEach((x) => x.classList.toggle('on', x.dataset.z === 'fit'));
    applyView();
  });

  $('#zoom').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    state.zoom = b.dataset.z === 'fit' ? 'fit' : Number(b.dataset.z);
    $$('#zoom button').forEach((x) => x.classList.toggle('on', x === b));
    applyZoom();
  });

  $('#chk-grid').addEventListener('change', (e) => {
    state.grid = e.target.checked;
    applyZoom();
  });

  $('#btn-export').addEventListener('click', doExport);
  $('#btn-batch').addEventListener('click', batchExport);
  // 在画布上滚动滚轮 = 缩放（向上滚放大、向下滚缩小，在 1x~16x 整数倍间切换）
  $('#canvas-wrap').addEventListener('wheel', (e) => {
    if (!state.outW) return;
    e.preventDefault();
    const levels = [1, 2, 4, 8, 16];
    const cur = state.effZ || 1;
    const up = e.deltaY < 0;
    let next;
    if (up) {
      next = levels.find((x) => x > cur + 0.01);                       // 向上：比当前大的最小整数倍
    } else {
      next = [...levels].reverse().find((x) => x < cur - 0.01);        // 向下：比当前小的最大整数倍
    }
    if (next == null) return;
    state.zoom = next;
    $$('#zoom button').forEach((b) => b.classList.toggle('on', b.dataset.z === String(next)));
    applyZoom();
  }, { passive: false });

  // 左键拖动平移（图片放大超出容器时按住左键拖动查看）
  const cwrap = $('#canvas-wrap');
  let drag = null;
  cwrap.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('button, input, select, .seg, a')) return;
    drag = { x: e.clientX, y: e.clientY, sl: cwrap.scrollLeft, st: cwrap.scrollTop };
    cwrap.style.cursor = 'grabbing';
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!drag) return;
    cwrap.scrollLeft = drag.sl - (e.clientX - drag.x);
    cwrap.scrollTop = drag.st - (e.clientY - drag.y);
  });
  window.addEventListener('mouseup', () => { drag = null; cwrap.style.cursor = ''; });

  window.addEventListener('resize', () => applyZoom());

  $('#btn-undo').addEventListener('click', undo);
  $('#btn-redo').addEventListener('click', redo);

  document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    const k = e.key.toLowerCase();
    if (k === 's') { e.preventDefault(); doExport(); }
    else if (k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); redo(); }
  });
}

/* ---------------- 启动 ---------------- */
async function init() {
  bind();
  try {
    state.meta = await (await fetch('/api/meta')).json();
  } catch (e) {
    state.meta = null;
  }
  // 调色板里的画布建议值
  refreshPresetSelect();
  buildControls();
  state.history = [{ ...state.params }];   // 初始参数作为历史起点
  state.hIndex = 0;
  refreshHistButtons();
}

init();

/* ---------------- 自定义预设（localStorage，纯前端） ---------------- */
const CUSTOM_PRESETS_KEY = 'pixceloe_presets_v1';

function loadCustomPresets() {
  try { return JSON.parse(localStorage.getItem(CUSTOM_PRESETS_KEY) || '{}'); }
  catch { return {}; }
}

function refreshPresetSelect(selected) {
  const sel = $('#preset');
  if (!sel) return;
  const custom = loadCustomPresets();
  sel.innerHTML = '';
  const add = (value, text) => {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = text;
    sel.appendChild(o);
  };
  add('character', '角色预设');
  add('scene', '场景预设');
  for (const name of Object.keys(custom)) add('custom:' + name, '★ ' + name);
  if (selected) sel.value = selected;
}

function applyPreset(key) {
  if (key === 'character' || key === 'scene') {
    state.params = { ...PRESETS[key] };
  } else if (key && key.startsWith('custom:')) {
    const p = loadCustomPresets()[key.slice(7)];
    if (!p) return;
    state.params = { ...p };
  } else {
    return;
  }
  pushHistory();
  buildControls();
  scheduleRender();
}

function saveCurrentPreset() {
  const name = prompt('预设名称：', '');
  if (!name || !name.trim()) return;
  const custom = loadCustomPresets();
  custom[name.trim()] = { ...state.params };
  localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(custom));
  refreshPresetSelect('custom:' + name.trim());
  toast(`已保存预设「${name.trim()}」`, true);
}
