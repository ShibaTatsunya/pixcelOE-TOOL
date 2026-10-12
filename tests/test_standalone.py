"""Compare the offline HTML algorithm against the Python implementation.

Run: python tests/test_standalone.py (requires Node.js).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.pipeline import Params, convert
from test_color_hue import source_blocks
from test_color_cleanup import fixture as cleanup_fixture
from test_selective import fixture as selective_fixture, rules as selective_rules
from test_color_regressions import painted_rules


def main():
    html = (ROOT / 'pixcelOE.html').read_text(encoding='utf-8')
    for shared in ('selective-algorithm.js', 'selective-controls.js'):
        assert (ROOT / 'web' / shared).read_text(encoding='utf-8') in html, f'offline copy of {shared} is stale'
    rng = np.random.default_rng(42)
    rgb = rng.integers(0, 256, (19, 23, 3), dtype=np.uint8)
    gray = np.repeat(np.arange(256, dtype=np.uint8).reshape(16, 16, 1), 3, axis=2)
    cases = []
    def add(name, src=rgb, tolerance=0, **kw):
        p = Params(**kw)
        expected = convert(src, p).final
        cases.append(dict(name=name, rgb=src.ravel().tolist(), h=src.shape[0], w=src.shape[1],
                          params=p.to_dict(), expected=expected.ravel().tolist(),
                          outW=expected.shape[1], outH=expected.shape[0], tolerance=tolerance))

    for mode in ('bridge', 'skew', 'dark', 'edge', 'median'):
        add('gray/' + mode, downsample=mode)
        add('color/' + mode, color_mode=True, downsample=mode)
    for pattern in ('bayer4', 'bayer8'):
        add('gray/' + pattern, src=gray, dither=pattern, enable_outline=False, factor=1)
        add('color/' + pattern, color_mode=True, dither=pattern)
    for key in ('enable_input', 'enable_posterize', 'enable_outline', 'enable_downsample', 'enable_quantize'):
        add('off/' + key, **{key: False})
        add('color/off/' + key, color_mode=True, **{key: False})
    for levels in (0, 1, 2, 3, 4, 5, 6, 7, 8):
        add('levels/' + str(levels), src=gray, posterize_levels=levels, quantize_levels=levels)
    add('adjust/rec709', desat='rec709', brightness=13, contrast=42)
    add('skip', posterize_skip=True)
    add('keep-thin', keep_thin=True, patch=3, thickness=2)
    add('scene', palette_kind='scene', factor=3)
    add('no-quantize', no_quantize=True)
    add('skip/off-quantize', posterize_skip=True, enable_quantize=False)
    # Same luminance, distinct hues: tie order must be deterministic.
    tied = np.array([[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [85, 85, 85]]], dtype=np.uint8)
    add('color/ties', src=tied, color_mode=True, factor=2, downsample='median',
        enable_input=False, enable_posterize=False, enable_outline=False, enable_quantize=False)
    blocks = source_blocks()
    for factor in (1, 2, 3, 4):
        add(f'selective/{factor}', src=selective_fixture(), selective_mode=True,
            accent_rules=selective_rules(), factor=factor)
    add('selective/conflicting-modes', src=selective_fixture(), selective_mode=True,
        color_mode=True, posterize_skip=True, accent_rules=selective_rules())
    add('selective/no-downsample', src=selective_fixture(), selective_mode=True,
        enable_downsample=False, accent_rules=selective_rules())
    add('selective/overlap', src=selective_fixture(), selective_mode=True,
        accent_rules=selective_rules()+[{**selective_rules()[0], 'region': None, 'target': '#35A7B4'}])
    add('selective/disabled', src=selective_fixture(), selective_mode=True,
        accent_rules=[{**selective_rules()[0], 'enabled': False}])
    add('selective/neutral-source', src=selective_fixture(), selective_mode=True,
        accent_rules=[{**selective_rules()[0], 'source': '#888888'}])
    add('selective/neutral-target',src=selective_fixture(),selective_mode=True,
        accent_rules=[{**selective_rules()[0],'target':'#FBFDFF'}])
    add('selective/large-minimum',src=selective_fixture(),selective_mode=True,
        factor=1,accent_rules=[{**selective_rules()[0],'min_size':121}])
    for factor in (1,3):
        for erase in (False,True):
            add(f'paint/{factor}/{erase}',src=selective_fixture(),selective_mode=True,
                factor=factor,accent_rules=painted_rules(erase))
    add('paint/empty',src=selective_fixture(),selective_mode=True,
        accent_rules=[{**selective_rules()[0],'paint_mask':{'strokes':[]}}])
    add('paint/large-radius',src=selective_fixture(),selective_mode=True,factor=1,
        accent_rules=[{**selective_rules()[0],'paint_mask':{'strokes':[{'points':[[.1,.1]],'radius':1.5,'erase':False}]}}])
    nearwhite=np.full((24,32,3),[251,253,255],dtype=np.uint8)
    add('near-white/darken',src=nearwhite,color_mode=True,brightness=-70,color_levels=4)
    for strength in (0, 1, 2):
        add(f'cleanup/{strength}', src=cleanup_fixture(), color_mode=True,
            color_cleanup=strength, factor=1, enable_input=False, enable_outline=False)
    for levels in (2, 4, 8, 12):
        for pattern in ('none', 'bayer4', 'bayer8'):
            add(f'hue-blocks/{levels}/{pattern}', src=blocks, color_mode=True,
                factor=3, color_levels=levels, dither=pattern)
    sample = ROOT.parent / 'mengshi-art-workflow/experiments/E048-front-light/outputs/canon_ps/bag_a/01_crop.png'
    if sample.exists():
        with Image.open(sample) as im:
            add('real-image/default', src=np.asarray(im.convert('RGB')))
            add('real-image/color', src=np.asarray(im.convert('RGB').resize((160, 240))), color_mode=True)
    identity = convert(rgb, Params(enable_input=False, posterize_skip=True, enable_outline=False,
                                   enable_downsample=False, no_quantize=True)).final
    assert np.array_equal(identity, rgb), 'no_quantize must preserve RGB rather than clip to white'
    tie_result = convert(tied, Params(color_mode=True, factor=2, downsample='median',
                                     enable_input=False, enable_posterize=False,
                                     enable_outline=False, enable_quantize=False)).final
    assert tie_result[0, 0].tolist() == [0, 0, 255], 'equal luminance must retain source order'
    runner = r"""
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('pixcelOE.html','utf8');
const script=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n').replace(/\binit\(\);\s*$/, '');
const ctx=vm.createContext({console,setTimeout,clearTimeout});vm.runInContext(script,ctx);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));let failed=0;
for(const c of cases){ctx.c=c;const r=vm.runInContext('convert(new Uint8ClampedArray(c.rgb),c.h,c.w,c.params)',ctx);
const diff=c.expected.filter((v,i)=>v!==r.final[i]).length;
const max=Math.max(...c.expected.map((v,i)=>Math.abs(v-r.final[i])));
const good=r.outW===c.outW&&r.outH===c.outH&&r.final.length===c.expected.length&&max<=c.tolerance;
console.log(`${good?'PASS':'FAIL'} ${c.name}: ${diff} channels differ, max=${max}${c.tolerance?' (LAB tolerance='+c.tolerance+')':''}`);if(!good)failed++;}
process.exitCode=failed?1:0;
"""
    result = subprocess.run(['node', '-e', runner], cwd=ROOT, input=json.dumps(cases),
                            text=True, encoding='utf-8', capture_output=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
