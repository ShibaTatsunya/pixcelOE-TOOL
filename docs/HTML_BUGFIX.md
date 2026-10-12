# 独立 HTML 版修复（2026-10-13）

用户反馈：导入后很卡，结果与 Python 版不同，调整参数没有反应。

## 修复

- 预览与导出使用的 Canvas ImageData 是 RGBA，原先直接填入 RGB 数据，导致通道错位、透明像素和残缺画面。现逐像素补 alpha=255。
- 把算法放到单文件内创建的 Web Worker；合并等待中的参数更新，丢弃过时结果。缓存轮廓扩展，改 factor、降采样策略或量化参数时复用。局部中值改为 Quickselect，减少数组分配和完整排序。
- 彩色模式切换会触发重算。第五步在彩色模式下也遵守开关；抖动控件放到执行它的第五步中。
- Bayer 归一化由矩阵边长改为矩阵元素数。恢复 float32 运算顺序、截断 uint8 与 NumPy 的偶数舍入语义。
- 彩色降采样使用 RGB 均值亮度，与 Python 一致；相同亮度中值取样使用稳定顺序。Python 的两处 argsort 同步改为 stable，旧版本对并列像素的选择可能因此变化。
- 保存预设、网格开关补齐实际实现。批量列表不再被上传函数覆盖，批量导出只询问一次倍数，导出 PNG 和 JSON；取消导出不再下载文件。
- 导入处理非法文件、大小限制和资源释放；验收按真实输出计算，不再固定显示全部通过。彩色输出会在灰阶检查中显示未通过。
- Python 网页管线同步修复“不强制套调色板”把 uint8 再乘 255 导致几乎全白、第五步开关被跳过预处理参数覆盖、单档分层除零。原始产线兼容函数 `pixelize_oe()` 保留旧数值行为，原有逐像素对照测试继续通过。

## 验证

- `python tests/test_standalone.py`：42 组 Python/JavaScript 对比；41 组逐像素完全相同。真实彩色图有 1 个通道相差 1，来自 LAB 数学库浮点舍入；该用例明确以 1 为容差，不承诺彩色在所有平台逐像素相同。
- `node tests/test_standalone_browser.mjs`：真实 Edge 打开 `file://`，验证后台计算、参数重算、快速连续更新、实际预览 RGB/alpha、非法导入、网格、预设、批量导出、JSON、整数缩放与取消下载。
- 640×960 合成图在 Edge 首次处理约 0.4 秒，复用轮廓改 factor 约 0.2 秒；后台处理期间主线程定时器持续运行。耗时随图片、参数和机器变化，4000 万像素上限不代表大图能实时处理。
- 原有静态资源、CLI 一致性、HTTP API 和浏览器冒烟测试也执行回归。浏览器需要正常 Windows 进程通信权限，受限沙箱内 Edge 会因访问被拒绝启动失败。

最终检查：独立算法 42 组、离线浏览器 20 项、静态资源 6 项、产线一致性 9 项、HTTP API 23 项、服务页面浏览器冒烟 20 项，全部通过。彩色浮点容差如上说明。

执行命令：

```text
python tests/test_standalone.py
node tests/test_standalone_browser.mjs
python tests/test_web_assets.py
python tests/test_consistency.py
python tests/test_api.py
python tests/test_browser.py
git diff --check
```

修改/新增文件：`pixcelOE.html`、`core/algorithm.py`、`core/pipeline.py`、`tests/test_standalone.py`、`tests/test_standalone_browser.mjs`、`README.md`、`docs/HTML_BUGFIX.md`。浏览器验证截图保存在 `outputs/_standalone_qa.png`；诊断临时文件已清理。

此次修改仅在本工具目录内；未修改游戏项目，未使用生成模型/GPU，未提交或上传 Git/GitHub。

## 同日后续：色彩层数保持原图色块的色相

用户要求调节层数时，整片色块中不能冒出其他色相的像素噪点。

原先固定 LAB A/B 改 L 后转回 RGB，会因越出色域而截断通道，改变色相；层数又会影响代表像素选择。改为 HSL 明度分层，在 RGB 色域内重建颜色；最后把原图对应位置的色相/饱和度作为引导，不让分层后的代表像素改变输出色相。原图引导在 HTML 中缓存，独立于色彩层数。抖动只改变明度。黑白流程保持原样。

彩色模式的外观会与旧 LAB 分层不同，这是按此次要求进行的行为调整。纯黑和纯白本身没有色相；8 位输出会有舍入误差。不会对原图自带的不同色相进行区域分割或统一涂色。

新增 `tests/test_color_hue.py`：166 组区域测试，覆盖色彩层数 2–12、五种降采样和三种抖动设置。最大色相误差约 1.54°，并检查整片内部无随机色点、灰色不染色。可视化保存为 `outputs/_color_hue_qa.png`。

独立 Python/JavaScript 对比扩为 54 组，包含原图色相引导和色块分层，真实彩色图也改为零容差。前面的 42 组 LAB 容差记录仅对应第一次修复时的版本。

本次涉及 `core/algorithm.py`、`core/pipeline.py`、`pixcelOE.html`、`web/app.js`、`tests/test_color_hue.py`、`tests/test_standalone.py`、`tests/test_standalone_browser.mjs`、`README.md` 与本记录。新增验证命令：`python tests/test_color_hue.py`，并重新执行算法一致性、API、静态资源和真实浏览器检查。

此次结果：色块测试 166 组、零容差 Python/HTML 对照 54 组、离线浏览器 31 项、原始产线一致性 9 项、HTTP API 23 项、静态资源 6 项全部通过。31 项浏览器检查包含实际滑块逐档操作 2–12 层，对比原图对应位置色相（最大约 1.54°）。无生成模型/GPU 使用，无游戏项目修改或 Git/GitHub 提交、上传。

## 同日后续：边缘杂色清理与可控抽色

用户选择“更干净，允许牺牲极小色点”，因此彩色模式默认 `color_cleanup=2`（标准）。在输出像素尺度的 5×5 邻域统计色相支持，孤立/稀有色相跟随附近主色或灰色区域；最终仍沿用处理结果的明度。轻度 `1` 保留更小色块，关闭 `0` 不做清理。此步骤只在彩色模式第五步开启时执行。`tests/test_color_cleanup.py` 的 9 项检查覆盖孤立异色点、小装饰、连通徽章和明度保持。

用户选择“按原图颜色筛选＋手动框选区域”。新增 `selective_mode` 和 `accent_rules`：主体走原有灰阶管线；从原图按块内中值代表像素提取 HSV 色相，在色相容差、最低饱和度、矩形范围和黑线保护条件相交后，去除过小的四连通块，最后填指定 RGB 纯色。颜色筛选独立于灰阶层数。每条规则一个可选矩形，最多 12 条规则，后面的规则覆盖前面的重叠区域。矩形以原图 0–1 比例坐标保存。开启抽色会归一化关闭完整彩色模式与跳过黑白预处理。

Python 实现位于 `core/selective.py`；离线算法源位于 `web/selective-algorithm.js`，原样嵌入 HTML worker。`web/selective-controls.js` 用于服务页面，并原样嵌入单文件。界面包含取色、框选、规则启停/删除、输出纯色、容差、饱和度、黑线保护与最小色块；Escape 取消取色/框选。修复原图标签拦截矩形起点鼠标事件，标签设置 `pointer-events:none`。近灰色取色会提示重新选择彩色位置。

导出 JSON 保存规则及实际用色/强调色面积；验收只接纳当前规则明确指定的强调色。关闭调色板量化、使用灰阶之外的灰色目标等仍可能验收失败，不会伪造通过状态。功能不包含物体识别或任意形状笔刷；同框同色的不同部位需缩小框选或另建规则。框选不自动适配不同构图的批量图片。

当前验证：

- `python tests/test_standalone.py`：66 组 Python/离线算法零容差对照全部通过，含 9 组抽色、3 组清理和真实彩色输入。
- `python tests/test_selective.py`：框外同色保持灰阶、指定纯色、黑线保护、孤立点、色相跨零、重叠优先、禁用/空规则、灰色取色与四种缩小倍数均通过。
- `node tests/test_standalone_browser.mjs`：38 项通过；实际鼠标点击取色、拖动框选，验证 120 像素整块为目标红色、框外同色灰阶、孤立点过滤和导出元数据；灰色取色提示与 Escape 取消也通过。640×960 合成图约 0.4 秒，复用轮廓约 0.2 秒（仅本机样例）。
- `python tests/test_api.py`：26 项通过，新增服务版抽色渲染、验收面积和导出规则检查。
- `python tests/test_web_assets.py`：7 项通过；`python tests/test_browser.py`：服务页面 20 项通过。
- 色相 166 组与边缘清理 9 项继续通过；`python tests/test_consistency.py` 的原始产线 9 项逐像素一致，`git diff --check` 无差异格式错误。

QA 图片：`outputs/_selective_qa.png`（合成色块）、`outputs/_standalone_qa.png`（实际界面）、`outputs/_selective_photo_example.png` 与同名 JSON（本机彩色插画→灰阶→下方包袋局部抽色，仅算法示例）。`outputs/_color_cleanup_example.png` 基于用户的放大结果截图估算像素网格，不能代替用原始输入重新渲染。参考 PNG 均只读；未覆盖原图。

本轮修改/新增 `core/selective.py`、`core/pipeline.py`、`core/algorithm.py`、`core/validate.py`、`server/api.py`、`pixcelOE.html`、`web/app.js`、`web/index.html`、`web/style.css`、两份抽色 JS、对应测试、README 和本记录。所有写入均在本工具目录内，无模型或 GPU 推理、游戏项目写入、Git 提交或远端操作。


## 后续调整：抽色保留灰阶明度、取色后回成品、移除 Gamma

按用户最新要求，抽色不再整块覆盖固定 RGB。以输出颜色的 HSL 色相/饱和度作为引导，以着色前灰阶成品的 HSL 明度作为目标，在 RGB 色域内重建。对应灰阶档位保留，8 位舍入允许最多 0.5 个明度单位误差；黑线保护和小色块过滤沿用原规则。后面的规则仍覆盖前面的色相，但始终使用原始灰阶底图明度，避免叠加着色改动明暗。此行为取代此前“同一色值平涂”的要求。

验收允许色值改为“当前规则颜色 × 固定灰阶调色板”推导出的离散色值集合，仍记录实际输出颜色与强调色面积；未量化的灰阶明度不会因抽色功能而自动获得验收通过。有效取色后立即自动切回成品，点击接近灰色的区域仍提示重新取色。

两种网页均移除 Gamma 控件和默认参数；Python Params 移除 gamma 字段，网页旧预设中的 gamma 会被删除，旧 API 参数被忽略。转换管线不再执行 Gamma，保留亮度和对比度。底层历史算法函数仍兼容旧 Python CLI 对照调用，不参与网页 Gamma 调节。

验证命令：`python tests/test_selective.py`、`python tests/test_standalone.py`、`node tests/test_standalone_browser.mjs`、`python tests/test_api.py`、`python tests/test_web_assets.py`、`python tests/test_browser.py`、`git diff --check`。明度测试覆盖 0–255 全部灰阶及四种缩小倍数；两端 66 组逐像素一致，离线浏览器 39 项通过（包含取色后自动切回成品和 Gamma 控件消失），HTTP API 26 项、静态资源 7 项、服务页面浏览器 20 项通过；`git diff --check` 无差异格式错误。旧 Gamma 参数在管线中无效并且不再进入 Params 导出。

涉及文件：`core/selective.py`、`core/pipeline.py`、`server/api.py`、`pixcelOE.html`、`web/selective-algorithm.js`、`web/selective-controls.js`、`web/app.js`、相关测试、README 与本记录。未修改外部参考图或游戏项目，未运行模型或 GPU 推理，未进行 Git 提交或远端操作。

## 后续反馈：暗化白底、轮廓杂色、最小色块与画笔遮罩

用户补充要求遇到问题查找已有方案，且应评估适用性。参考 [OpenCV 双边滤波文档](https://docs.opencv.org/3.4.19/d4/d86/group__imgproc__filter.html) 与 [scikit-image 连通区域过滤文档](https://scikit-image.org/docs/0.23.x/api/skimage.morphology.html)。双边滤波适用于保边平滑，但本次不使用整图滤波：实测根因是接近白色的像素只有极小通道差，HSL 明度恢复却按高饱和度重建，调暗后放大成彩色噪点。修复 `restore_color_hue` 与 JS 对应代码，通道差 <=8 的原图引导保持中性，明度仍沿用处理结果。这个阈值与现有灰阶/彩色分类一致。直接修复颜色恢复，不模糊轮廓。

本机 640×960 彩色样例在亮度 -50 时，以原始近灰色引导重建会误染 17955 个输出像素，修正后为 0；亮度 -100 为 17883→0。`outputs/_neutral_noise_fix.png` 是本机真实样例修复前后的软件 QA 对比，上排亮度 0、下排 -50，左旧算法、右修复。与用户截图同类的彩色轮廓也随近灰色恢复修正消失；不据此声称能移除原图所有真实异色细节。

最小色块存在两处限制：旧 API/滑块将阈值夹到 64，较大的对象调节无感；原先先连通筛选掩码再着色，不可见白色像素可能连起本应分开的色点。现在先计算最终可见彩色像素（通道差 >8），再按四邻域连通面积过滤。滑块 1–4096，数字框可到 4000 万（与图像上限一致）。阈值为最小保留面积，不是按单个灰阶色值拆块；相连的不同明度属于同一块。实测 120 像素色块在阈值 121 时消失，阈值 2 时保留。

每条规则新增 `paint_mask`，为 `null` 时不限制画笔范围；`{strokes:[]}` 为启用但空的遮罩，允许区域为空。每笔保存原图比例坐标 points、相对原图短边的圆形 radius 与 erase 标志，按笔画顺序在原图坐标中取输出像素中心，生成无半透明的二值许可区域。涂抹加入许可，橡皮擦去除许可；与原图色相筛选及矩形范围取交集，遮罩外保持灰阶。笔画/圆头线段仅处理包围框，避免每个像素扫描整张笔画。界面显示紫色覆盖层，支持半径、撤销一笔、清除、完成与 Escape。笔画序列保存在预设/API/导出 JSON 中，缩小倍数改变后仍按原图位置取样。预览覆盖层的显示抗锯齿不会进入最终二值遮罩或导出图像。

服务版同步修复连续参数更新的时序：请求参数深复制，改变参数或上传图片会使旧请求失效，旧预览和旧报告不能覆盖最新结果，图像与验收使用同一参数快照。`node tests/test_web_render.mjs` 人为颠倒 HTTP 完成顺序，验证旧图/旧报告被丢弃。

验证命令（本轮 Python 使用 Codex 内置运行时，当前系统 `python` 指向 WindowsApps 别名，无法运行；未安装新依赖）：

```text
<bundled-python> tests/test_color_regressions.py
<bundled-python> tests/test_selective.py
<bundled-python> tests/test_standalone.py
node tests/test_standalone_browser.mjs
node tests/test_web_render.mjs
<bundled-python> tests/test_api.py
<bundled-python> tests/test_color_hue.py
<bundled-python> tests/test_color_cleanup.py
<bundled-python> tests/test_web_assets.py
<bundled-python> tests/test_browser.py
git diff --check
```

实际 Python：`C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`。验证包含 8 组亮度/缩小倍数组合、近白彩边、有效连通面积、画笔/擦除/空遮罩、75 组 Python/离线算法逐像素零容差对照、46 项真实离线浏览器检查、30 项 HTTP API、服务请求乱序测试、色相 166 组、清理 9 项、静态资源 7 项和服务浏览器 20 项。均通过。

遮罩预览沿用浏览器 Canvas 的 [合成操作](https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/globalCompositeOperation) 与 [圆形线帽](https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/lineCap)：画笔累加、destination-out 擦除。最终二值遮罩按同一圆头线段几何在 Python/JS 中计算，避免 Canvas 抗锯齿或浏览器像素差影响最终允许区域。无需额外遮罩插件或整图降噪库。

本轮涉及 `core/algorithm.py`、`core/selective.py`、`pixcelOE.html`、两份抽色 JS、`web/app.js`、新增回归与请求时序测试、扩展 API/离线测试、README 和本记录。参考文件只读，全部写入本工具目录；无生成模型/GPU 推理、游戏项目修改、Git 提交或远端操作。
