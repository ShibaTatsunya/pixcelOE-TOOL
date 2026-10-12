"""Check speckle suppression without blurring outlines or connected accents."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.algorithm import clean_color_speckles, restore_color_hue


def fixture():
    image = np.full((24, 24, 3), [72, 94, 68], dtype=np.uint8)
    image[:, :8] = [60, 60, 60]
    # Isolated colors on a neutral contour and on a coherent green region.
    image[5, 7] = [10, 230, 255]
    image[13, 8] = [255, 10, 230]
    # A connected badge and a two-pixel intentional small accent.
    image[6:9, 15:18] = [230, 135, 40]
    image[18, 18:20] = [220, 30, 30]
    return image


def main():
    source = fixture()
    light = clean_color_speckles(source, 1)
    standard = clean_color_speckles(source, 2)
    assert np.array_equal(clean_color_speckles(source, 0), source)
    assert light[5, 7].tolist() == [60, 60, 60]
    assert light[13, 8].tolist() == [72, 94, 68]
    assert np.array_equal(light[6:9, 15:18], source[6:9, 15:18])
    assert np.array_equal(standard[6:9, 15:18], source[6:9, 15:18])
    assert np.array_equal(light[18, 18:20], source[18, 18:20])
    assert not np.array_equal(standard[18, 18:20], source[18, 18:20])
    output = restore_color_hue(source, light)
    base_l = (source.max(axis=2).astype(int)+source.min(axis=2).astype(int))/2
    out_l = (output.max(axis=2).astype(int)+output.min(axis=2).astype(int))/2
    assert np.max(np.abs(base_l-out_l)) <= 0.5
    mask = np.all(source == light, axis=2)
    assert np.array_equal(output[mask], source[mask]), 'unchanged regions must remain exact'
    print('PASS 9 cleanup checks: isolated hues removed; badge and small accents protected in light mode; lightness preserved')
    panel = Image.new('RGB', (744, 300), '#14161c')
    draw = ImageDraw.Draw(panel)
    for i, (label, rgb) in enumerate([('Off', source), ('Light', restore_color_hue(source, light)), ('Standard', restore_color_hue(source, standard))]):
        draw.text((12+i*244, 10), label, fill='white')
        panel.paste(Image.fromarray(rgb).resize((240, 240), Image.Resampling.NEAREST), (4+i*244, 40))
    panel.save(ROOT/'outputs/_color_cleanup_qa.png')
    if len(sys.argv) > 1:
        # The supplied example is an enlarged result, not the source input.
        # Approximate its fourfold display grid for a post-processing preview.
        with Image.open(sys.argv[1]) as im:
            sample = np.asarray(im.convert('RGB').resize((round(im.width/4), round(im.height/4)), Image.Resampling.NEAREST))
        rows = [sample, restore_color_hue(sample, clean_color_speckles(sample, 1)),
                restore_color_hue(sample, clean_color_speckles(sample, 2))]
        w, h = sample.shape[1]*2, sample.shape[0]*2
        preview = Image.new('RGB', (w*3, h+32), '#14161c')
        draw = ImageDraw.Draw(preview)
        for i, (label, arr) in enumerate(zip(('Screenshot grid / off', 'Light', 'Standard'), rows)):
            draw.text((i*w+10, 8), label, fill='white')
            preview.paste(Image.fromarray(arr).resize((w,h), Image.Resampling.NEAREST), (i*w,32))
        preview.save(ROOT/'outputs/_color_cleanup_example.png')
        print('Example preview uses an estimated screenshot grid; it is not a re-render of the unavailable original input.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
