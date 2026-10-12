# pixcelOE

[简体中文](README.md) | **English**

**Convert photos and illustrations into pixel-style images with tonal layering, outline preservation, and selective color.**

Current version: **1.5.0-alpha.1** · Alpha

pixcelOE runs either as a standalone HTML file or as a local Python service. Adjust pixel size, grayscale levels, color lightness levels, and palettes through visual controls. You can also keep most of an image in grayscale while preserving or assigning hues to details such as ties, headphones, and badges.

[Examples](#examples) · [Quick start](#quick-start) · [Selective color](#selective-color) · [Development and testing](#development-and-testing) · [Changelog](CHANGELOG.md)

The application interface is currently in Simplified Chinese. Instructions below include the corresponding Chinese control labels.

## Features

- **Pixelization**: tonal layering, outline expansion, five block sampling modes, and palette quantization.
- **Color and grayscale modes**: color mode preserves hues at corresponding source positions while controlling lightness levels; grayscale mode includes character and scene palettes.
- **Selective color**: combine source color filtering, rectangles, and painted masks to color selected areas while retaining grayscale lightness.
- **Color noise cleanup**: adjustable edge cleanup, near-neutral color protection, minimum connected color area filtering, and dark line protection.
- **Interactive previews**: result, original, and side-by-side views; zoom, pan, pixel grid, and parameter undo/redo.
- **Presets and exports**: custom presets, batch processing, integer-scale PNG exports, and matching JSON metadata.
- **Local processing**: the HTML edition processes images in the browser; the Python service listens on the local machine by default. Image processing requires no cloud service.

## Examples

These examples were processed with `1.5.0-alpha.1`, with parameters adjusted for each image and dithering disabled. Originals are resized for display; results are enlarged 2× using nearest-neighbor scaling. Python and standalone HTML outputs were verified to match pixel for pixel.

### Color pixelization

Preserve the original hues at corresponding positions, using **8 lightness levels** to define hair, clothing, and skin. Input: `640×960`; output: `160×240`. Brightness: −5; contrast: 10; edge color cleanup: standard. [Full parameters](docs/examples/color-params.json)

![Original on the left, color pixelization on the right: source hues with 8 lightness levels](docs/images/color-comparison.png)

### Grayscale pixelization

Use **4 grayscale levels** to simplify shading while retaining glasses, outlines, and clothing folds. Input: `640×960`; output: `160×240`. Brightness: 0; contrast: 25. [Full parameters](docs/examples/gray-params.json)

![Original on the left, grayscale pixelization on the right: 4 grayscale levels with preserved outlines](docs/images/gray-comparison.png)

### Selective color

Start with a grayscale base, then select the headphones, shoulder strap, and bag by source color and region. A painted mask excludes unwanted selections near the wrist. Coloring retains grayscale lightness, so the cyan headphones and red bag still show light and shadow. Input: `832×1216`; output: `208×304`. Grayscale levels: 4; brightness: 25; contrast: 0. [Full parameters and mask](docs/examples/selective-params.json)

![Left to right: original, grayscale base, and selective color with cyan headphones and a red strap and bag](docs/images/selective-comparison.png)

## Quick start

### Standalone HTML edition

1. Download [pixcelOE.html](pixcelOE.html) from this repository.
2. Open the file in desktop Edge or Chrome.
3. Drag in an image or click “Choose image” (选择图片), adjust parameters, and click “Export PNG” (导出 PNG).

No Python installation, server, or build step is required. A Web Worker processes images in the background. PNG and JSON files are saved through your browser's download system. Batch exports may require permission to download multiple files.

### Local Python service

Requires Python 3.9+, NumPy, and Pillow. Download and extract the full repository, then run these commands from the project directory:

```bash
python -m pip install numpy pillow
python app.py
```

Your browser opens `http://127.0.0.1:8760` automatically. On Windows, you can also double-click [启动.bat](启动.bat); the script checks for dependencies and installs any that are missing.

```bash
python app.py --port 9000   # Starting port; tries higher ports if occupied
python app.py --no-browser  # Start the service without opening a browser
python app.py --version    # Show the version
```

The service exports to the project's `outputs/` directory. `web/index.html` is the service edition's page; access it through the running service.

| Item | Standalone HTML | Local Python service |
|---|---|---|
| Entry point | `pixcelOE.html` | `python app.py` / `启动.bat` |
| Image processing | Browser Web Worker | NumPy + Pillow |
| Requirements | Desktop browser | Python and two dependencies |
| Export location | Browser download directory | Project `outputs/` directory |
| Network needed for image processing | No | No; initial dependency installation requires a connection or offline packages |

## Basic workflow

1. Import a PNG, JPEG, WebP, or another supported image. The service limits each image to 64 MB and 40 million pixels. HTML format support depends on the browser; its pixel limit is also 40 million.
2. Choose the character or scene preset, then adjust brightness, contrast, tonal levels, and outlines.
3. Set the downsampling factor (缩小倍数) to control pixel block size. For example, a `640×960` image at factor 4 produces `160×240` pixels.
4. Check corresponding positions in the original or side-by-side view, and inspect details with the pixel grid.
5. Export PNG and JSON files. JSON records the version, processing parameters, export scale, and validation results.

Dimensions do not have to be divisible by the downsampling factor. Edge replication pads the last block, and output dimensions round up. Exports support integer enlargement factors from 1 to 8.

Custom presets are saved in the current browser's local storage. Clearing browser data, switching browsers, or moving the HTML file may make existing presets unavailable. Keep important settings in exported JSON files.

### Parameter reference

| Parameter | Purpose |
|---|---|
| Brightness / contrast (亮度 / 对比度) | Adjust overall brightness and tonal separation |
| Grayscale levels (灰阶层数) | Control grayscale lightness levels |
| Keep color / color levels (保留彩色 / 色彩层数) | Preserve source hues and adjust color lightness levels |
| Detail sensitivity / line thickness (细节敏感度 / 线条粗细) | Adjust the local outline statistics window and morphological processing strength |
| Keep thin lines (保留细线) | Help retain small details such as eyelashes and clothing seams |
| Downsampling factor (缩小倍数) | Control output resolution and pixel block size |
| Block sampling mode (像素块取值方式) | `bridge`: connect broken lines; `skew`: skew-based sampling; `dark`: protect dark lines; `edge`: protect edges near light backgrounds; `median`: median sampling |
| Dark line preservation (暗线保留强度) | Set the threshold for detecting dark lines within a block |
| Palette / color count (调色板 / 颜色数) | Control grayscale colors; 0 uses the full palette |
| Dithering (抖动) | Optional Bayer 4×4 / 8×8 lightness dithering; disabled by default |
| Edge color cleanup (边缘杂色清理) | Off, light, or standard; standard may remove tiny points of a distinct hue |
| Target canvas (目标画布) | Validate output dimensions; leave empty to skip this check |

Gamma has been removed from the current interface and processing pipeline. Gamma fields in older presets are ignored.

## Selective color

Selective color adds color to chosen areas of the grayscale result. **The output uses the selected color's hue and saturation, while HSL lightness comes from the corresponding grayscale result pixel.** This preserves highlights, shadows, and tonal layers. The color picker's lightness does not override grayscale lightness.

1. Enable “Selective color” (⑥ 抽色艺术) and add a rule.
2. Click “Pick from original” (从原图取色) and select a source color. A successful pick automatically returns to the result view.
3. Set the output hue (输出色相), hue tolerance, and minimum saturation.
4. Optionally select a rectangle or use “Paint mask” (画笔绘制遮罩) to mark eligible areas. Source color filtering, the rectangle, and the painted mask intersect.
5. Refine the mask with the eraser, undo last stroke, or clear mask controls. Click “Finish mask” (完成遮罩) to see the result.
6. Adjust dark line protection and minimum connected color area (最小连通色块) to reduce unwanted color on dark lines and isolated dots.

Minimum connected color area measures the four-connected area of **visible colored output pixels**. Components smaller than the threshold are removed. Adjacent colored pixels with different lightness values belong to the same component. The slider reaches 4096; larger values can be entered directly. Use 1 to retain very small accents.

Up to 12 rules are supported. Later rules take precedence where they overlap. Rectangles and brush strokes use normalized source coordinates, so they continue to target the same region when the downsampling factor changes. Rules are saved in presets and exported JSON. Check region positions again when batch-processing images with different compositions.

Areas outside the painted mask stay grayscale. “Clear mask” (清除遮罩) removes the brush restriction, leaving color filtering and the rectangle in effect. Press Escape to exit color picking, rectangle selection, or mask editing.

## Validation and known limitations

Export reports include checks for target dimensions, semitransparent pixels, palette colors, and unexpected colors, along with actual color values and selective color coverage. Checks follow the built-in grayscale palettes and selective color rules. Full-color mode or disabled quantization may fail palette-related checks; export remains available.

- This is an Alpha release. Parameters, the interface, and export formats may change.
- Processing currently produces opaque RGB output. Automatic background removal and input transparency preservation are not supported.
- Selective color uses source colors and spatial regions rather than object recognition. Objects of the same color within a permitted region may be selected together. White, gray, and black have no useful hue to filter.
- Near-neutral pixels remain neutral to reduce saturated noise when darkening near-white backgrounds. Standard cleanup may remove pupils or decorations only 1–2 pixels in size.
- Large images, complex outlines, and many brush strokes increase processing time. Performance depends on the device and parameters.
- Automated checks identify size and color issues; outlines, composition, and artistic quality still require visual review.

## Development and testing

The service uses Python's standard-library `http.server`; NumPy and Pillow handle image processing. The frontend uses plain HTML, CSS, and JavaScript, with no frontend build step.

```text
pixcelOE-TOOL/
├── VERSION                     Current version
├── pixcelOE.html                Standalone HTML entry point
├── app.py                      Python service entry point
├── core/                       Image algorithms, pipeline, selective color, validation
├── server/api.py               HTTP API and static file service
├── web/                        Service interface and shared selective color scripts
├── data/palette.json           Built-in palettes
├── tests/                      Algorithm, API, and browser tests
├── docs/                       Examples, fix records, and historical roadmap
└── 启动.bat                    Windows launcher
```

The following algorithm and static asset checks use synthetic fixtures defined in the repository. Python/HTML consistency checks also require Node.js:

```bash
python tests/test_color_hue.py
python tests/test_color_cleanup.py
python tests/test_color_regressions.py
python tests/test_selective.py
python tests/test_web_assets.py
python tests/test_standalone.py
node tests/test_web_render.mjs
```

`node tests/test_standalone_browser.mjs` uses a real Edge or Chrome browser to verify offline import, parameter controls, brush masks, and export. Browser discovery currently uses Windows paths and requires a locally installed browser.

`tests/test_consistency.py` and `tests/test_api.py` rely on pipeline scripts or sample images from the author's local `../mengshi-art-workflow/` directory, which is not included in this repository. Prepare those files or update the paths before running these tests. Missing fixtures do not count as completed end-to-end verification. Service browser tests are in `tests/test_browser.py`.

Python/HTML comparisons cover grayscale, full color, selective color, dithering, step toggles, painted masks, and boundary parameters. Shared scripts `web/selective-algorithm.js` and `web/selective-controls.js` are also embedded in the standalone HTML file. Keep the embedded copies synchronized when editing; consistency checks verify them.

Detailed verification records are available in [HTML port fixes](docs/HTML_BUGFIX.md) (Chinese). See the [changelog](CHANGELOG.md) and [historical roadmap](docs/ROADMAP.md) for iteration history (Chinese).

## Reporting issues

When opening an issue, include the version, edition, operating system, browser, reproduction steps, parameters, and actual versus expected results. You may attach a shareable source image, output, and exported JSON. Check that any attached material is suitable for public sharing.

## License

This repository does not currently declare an open-source license. Public source availability does not grant redistribution or commercial-use rights. Contact the project maintainer for usage permissions.
