"""Near-white chroma, visible component area and painted source-space masks."""
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core.pipeline import Params,convert
from core.selective import apply_selective_color,normalize_rules
from test_selective import fixture,rules

def painted_rules(erase=False):
    strokes=[dict(radius=.15,points=[[.2,.3],[.2,.5]],erase=False)]
    if erase:
        strokes.append(dict(radius=.06,points=[[.2,.4]],erase=True))
    return [{**rules()[0], 'paint_mask':dict(strokes=strokes)}]

def main():
    src=np.full((48,48,3),255,dtype=np.uint8)
    for y in range(48):
        for x in range(48):src[y,x]=[247+(x+y)%9,250+(x+y)%6,255]
    src[12:36,12:36]=[150,70,25]
    src[11:37,11]=[251,254,255]  # faint cool anti-aliased fringe
    count=0
    for brightness in (0,-30,-60,-100):
        for factor in (1,4):
            out=convert(src,Params(color_mode=True,brightness=brightness,color_levels=4,
                                   factor=factor,enable_outline=False)).final
            assert np.all(out[:2,:,0]==out[:2,:,1]) and np.all(out[:2,:,1]==out[:2,:,2])
            if factor==1:assert np.all(np.ptp(out[11:37,11].astype(int),axis=1)==0)
            if brightness>=-30:assert np.any(np.ptp(out.astype(int),axis=2)>8),'true color must remain'
            count+=1
    src=fixture();gray=np.full_like(src,120)
    assert np.any(np.ptp(apply_selective_color(gray,src,1,False,rules()).astype(int),axis=2)>8)
    assert np.array_equal(apply_selective_color(gray,src,1,False,[{**rules()[0],'min_size':121}]),gray)
    red=np.empty((1,8,3),dtype=np.uint8);red[:]=[180,35,40]
    bridge=np.full_like(red,255);bridge[:,:2]=120;bridge[:,-2:]=120
    assert np.array_equal(apply_selective_color(bridge,red,1,False,
        [{**rules()[0],'region':None,'min_size':3}]),bridge),'invisible whites must not connect tiny accents'
    paint=apply_selective_color(gray,src,1,False,painted_rules())
    erased=apply_selective_color(gray,src,1,False,painted_rules(True))
    n=lambda a:int((np.ptp(a.astype(int),axis=2)>8).sum())
    assert 0<n(erased)<n(paint)<120
    assert np.array_equal(apply_selective_color(gray,src,1,False,
        [{**rules()[0],'paint_mask':{'strokes':[]}}]),gray)
    assert normalize_rules(painted_rules(True))[0]['paint_mask']['strokes'][1]['erase']
    print(f'PASS {count} brightness/factor cases; neutral background/fringe, visible area threshold, paint/erase/empty masks')

if __name__=='__main__':main()
