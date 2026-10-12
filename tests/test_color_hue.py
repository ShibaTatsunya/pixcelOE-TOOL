"""Regression: lightness layers must not introduce foreign hues into color blocks."""
import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.algorithm import downsample_color, quantize_color
from core.pipeline import Params, convert


def hue_error(actual, reference):
    errors = []
    for a, b in zip(actual.reshape(-1, 3), reference.reshape(-1, 3)):
        # Hue is undefined at black/white and poorly conditioned close to gray.
        if np.ptp(a.astype(int)) < 24 or np.ptp(b.astype(int)) < 24:
            continue
        ha = colorsys.rgb_to_hsv(*(a / 255.0))[0]
        hb = colorsys.rgb_to_hsv(*(b / 255.0))[0]
        d = abs(ha - hb)
        errors.append(min(d, 1 - d) * 360)
    return max(errors, default=0), len(errors)


def source_blocks():
    # Warm/cool regions have texture in lightness, including highlight/shadow
    # values that previously pushed the fixed LAB chroma outside the RGB gamut.
    result = np.empty((48, 144, 3), dtype=np.uint8)
    for region, hue in enumerate((0.02, 0.12, 0.32, 0.53, 0.67, 0.85)):
        for y in range(48):
            light = 0.10 + 0.80 * y / 47
            c = np.round(np.array(colorsys.hls_to_rgb(hue, light, 0.82)) * 255).astype(np.uint8)
            result[y, region * 24:(region + 1) * 24] = c
    return result


def main():
    source = source_blocks()
    passed = 0
    snapshots = []
    max_error = 0
    for levels in range(2, 13):
        for pattern in ('none', 'bayer4', 'bayer8'):
            direct = quantize_color(source, levels, 4, pattern, 24)
            error, count = hue_error(direct, source)
            assert count > 0 and error <= 3, (levels, pattern, 'quantize', error)
            for mode in ('bridge', 'skew', 'dark', 'median', 'edge'):
                p = Params(color_mode=True, color_levels=levels, factor=3,
                           downsample=mode, dither=pattern, contrast=35)
                out = convert(source, p).final
                guide = downsample_color(source, 3, mode)
                error, count = hue_error(out, guide)
                assert count > 0 and error <= 3, (levels, pattern, mode, error)
                max_error = max(max_error, error)
                # Within each source row/region, no scattered foreign colors.
                if pattern == 'none':
                    for region in range(6):
                        # Outline shading may change lightness at region edges.
                        interior = out[:, region*8+2:region*8+6]
                        assert np.array_equal(interior, np.repeat(interior[:, :1], 4, axis=1))
                passed += 1
            if pattern == 'none' and levels in (2, 4, 8, 12):
                snapshots.append((levels, convert(source, Params(color_mode=True, color_levels=levels, factor=3)).final))

    neutral = np.repeat(np.arange(256, dtype=np.uint8).reshape(16, 16, 1), 3, axis=2)
    neutral_out = quantize_color(neutral, 2, 4, 'bayer8', 100)
    assert np.all(neutral_out[:, :, 0] == neutral_out[:, :, 1])
    assert np.all(neutral_out[:, :, 1] == neutral_out[:, :, 2])
    passed += 1
    # A visual artifact for checking region colors at several layer counts.
    panel = Image.new('RGB', (600, 188 * 5), '#14161c')
    draw = ImageDraw.Draw(panel)
    rows = [('Original', source)] + [(f'Color lightness levels: {n}', im) for n, im in snapshots]
    for row, (label, arr) in enumerate(rows):
        draw.text((12, row*188+8), label, fill='white')
        image = Image.fromarray(arr).resize((576, 144), Image.Resampling.NEAREST)
        panel.paste(image, (12, row*188+32))
    panel.save(ROOT / 'outputs/_color_hue_qa.png')
    print(f'PASS {passed} region/level/dither cases; maximum hue error {max_error:.3f} degrees')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
