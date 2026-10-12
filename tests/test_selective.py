"""Selective masks: ROI, gray lightness, line protection and speckles."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.selective import apply_selective_color, normalize_rules
from core.pipeline import convert, Params

def fixture():
    src = np.full((24, 32, 3), 190, dtype=np.uint8)
    src[4:16, 2:12] = [180, 35, 40]
    src[4:16, 20:30] = [180, 35, 40]
    src[16:22, 12:20] = [20, 160, 180]
    src[2, 2] = [180, 35, 40]
    return src

def rules():
    return [dict(source='#B42328', target='#A92F35', tolerance=20, saturation=20,
                 dark_limit=32, min_size=2, region=[0, 0, .5, 1], enabled=True)]

def main():
    src = fixture(); gray = np.full_like(src, 120); rule = rules()
    out = apply_selective_color(gray, src, 1, False, rule)
    assert np.all(out[4:16, 2:12] == [188, 52, 59])
    assert np.array_equal(out[4:16, 20:30], gray[4:16, 20:30])
    assert np.array_equal(out[2, 2], gray[2, 2])
    assert np.array_equal(out[16:22, 12:20], gray[16:22, 12:20])
    black = gray.copy(); black[8:10, 4:6] = 15
    protected = apply_selective_color(black, src, 1, False, rule)
    assert np.all(protected[8:10, 4:6] == 15)
    disabled = [{**rule[0], 'enabled': False}]
    assert np.array_equal(apply_selective_color(gray, src, 1, False, disabled), gray)
    assert np.array_equal(apply_selective_color(gray, src, 1, False, []), gray)
    assert np.array_equal(apply_selective_color(gray, src, 1, False, [{**rule[0], 'source': '#888888'}]), gray)
    two = rule + [{**rule[0], 'target': '#35A7B4'}]
    assert np.all(apply_selective_color(gray, src, 1, False, two)[5:8, 3:7] == [55, 172, 185])
    wrap = np.array([[[180, 20, 25], [180, 25, 20]]], dtype=np.uint8)
    wrap_gray = np.full_like(wrap, 120)
    assert np.all(apply_selective_color(wrap_gray, wrap, 1, False,
        [dict(source='#FF0000', target='#35A7B4', tolerance=5, min_size=1)]) == [55, 172, 185])
    for factor in (1, 2, 3, 4):
        p = Params(selective_mode=True, color_mode=True, posterize_skip=True,
                   accent_rules=rule, factor=factor, enable_outline=False)
        output = convert(src, p).final
        assert p.color_mode is False and p.posterize_skip is False
        colored = output.max(axis=2)-output.min(axis=2)>8
        assert colored.any() and not colored[:, output.shape[1]//2:].any()
        base = convert(src, Params(factor=factor, enable_outline=False)).final
        light = (output.max(axis=2).astype(float)+output.min(axis=2))/2
        assert np.max(np.abs(light-base[:,:,0])) <= .5
    # All 256 gray intensities retain lightness, including black and white.
    ramp = np.repeat(np.arange(256,dtype=np.uint8)[None,:,None],3,axis=2)
    reds = np.empty_like(ramp); reds[:] = [180,35,40]
    shades = apply_selective_color(ramp, reds, 1, False,
        [{**rule[0], 'region': None, 'dark_limit': 0, 'min_size': 1}])
    light = (shades.max(axis=2).astype(float)+shades.min(axis=2))/2
    assert np.max(np.abs(light-ramp[:,:,0])) <= .5
    assert len(np.unique(shades.reshape(-1,3),axis=0)) == 256
    assert np.array_equal(convert(src, Params.from_dict({'gamma': .2})).final,convert(src, Params()).final)
    assert 'gamma' not in Params.from_dict({'gamma': .2}).to_dict()
    assert len(normalize_rules(rule * 20)) == 12
    # Visual comparison is an algorithm QA artifact, not a generated character.
    final = convert(src, Params(selective_mode=True, accent_rules=rule, factor=1, enable_outline=False)).final
    comparison = np.concatenate([src, final], axis=1)
    ROOT.joinpath('outputs').mkdir(exist_ok=True)
    Image.fromarray(comparison).resize((640, 240), Image.Resampling.NEAREST).save(ROOT/'outputs/_selective_qa.png')
    print('PASS selective color: ROI, 256 gray intensities, protected lines, cleanup, overlap, 4 factors; legacy Gamma ignored')

if __name__ == '__main__':
    main()
