"""Deterministic selective-color masks, preserving grayscale lightness."""
from collections import deque
import re
import numpy as np
from .algorithm import downsample_color, restore_color_hue
from .palette import hex_to_rgb


def normalize_rules(rules):
    result = []
    for rule in (rules if isinstance(rules, list) else [])[:12]:
        if not isinstance(rule, dict):
            continue
        source = str(rule.get('source', '#35A7B4'))
        target = str(rule.get('target', source))
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', source) or not re.fullmatch(r'#[0-9a-fA-F]{6}', target):
            continue
        region = rule.get('region')
        if isinstance(region, list) and len(region) == 4:
            region = [max(0., min(1., float(v))) for v in region]
            if region[2] <= region[0] or region[3] <= region[1]:
                region = None
        else:
            region = None
        result.append(dict(source=source.upper(), target=target.upper(), region=region,
                           tolerance=max(0., min(90., float(rule.get('tolerance', 20)))),
                           saturation=max(0., min(100., float(rule.get('saturation', 20)))),
                           dark_limit=max(0, min(128, int(rule.get('dark_limit', 32)))),
                           min_size=max(1, min(40_000_000, int(rule.get('min_size', 2)))),
                           paint_mask=normalize_paint_mask(rule.get('paint_mask')),
                           enabled=rule.get('enabled', True) is not False))
    return result


def normalize_paint_mask(value):
    if not isinstance(value, dict) or not isinstance(value.get('strokes'), list):
        return None
    strokes = []
    for stroke in value['strokes'][:512]:
        if not isinstance(stroke, dict):
            continue
        points = []
        for p in (stroke.get('points') if isinstance(stroke.get('points'), list) else [])[:4096]:
            if isinstance(p, list) and len(p) == 2:
                points.append([max(0., min(1., float(v))) for v in p])
        if points:
            strokes.append(dict(points=points, radius=max(.00001, min(64., float(stroke.get('radius', .03)))),
                                erase=stroke.get('erase') is True))
    return dict(strokes=strokes)


def paint_mask_at(value, xs, ys, sw, sh):
    """Hard binary circles/segments at output pixel centers, in source coordinates."""
    result = np.zeros((len(ys), len(xs)), dtype=bool)
    xcoords, ycoords = xs*sw, ys*sh
    for stroke in value['strokes']:
        points = np.asarray(stroke['points'])*[sw, sh]
        radius = stroke['radius']*min(sw, sh)
        for a, b in zip(points, np.vstack([points[1:], points[-1:]])):
            xl = np.searchsorted(xcoords, min(a[0],b[0])-radius, side='left')
            yr = np.searchsorted(ycoords, max(a[1],b[1])+radius, side='right')
            yl = np.searchsorted(ycoords, min(a[1],b[1])-radius, side='left')
            xr = np.searchsorted(xcoords, max(a[0],b[0])+radius, side='right')
            xx, yy = np.meshgrid(xcoords[xl:xr], ycoords[yl:yr])
            dx, dy = b-a; denom = dx*dx+dy*dy
            t = np.clip(((xx-a[0])*dx+(yy-a[1])*dy)/denom, 0, 1) if denom else 0
            selected = (xx-a[0]-t*dx)**2+(yy-a[1]-t*dy)**2 <= radius*radius
            result[yl:yr,xl:xr][selected] = not stroke['erase']
    return result


def hue_saturation(rgb):
    a = rgb.astype(np.float64)
    hi, lo = a.max(axis=-1), a.min(axis=-1)
    delta = hi - lo
    safe = np.maximum(delta, 1)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hue = np.where(hi == r, (g-b)/safe, np.where(hi == g, 2+(b-r)/safe, 4+(r-g)/safe))
    return (hue*60+360) % 360, np.divide(delta, hi, out=np.zeros_like(delta), where=hi > 0)*100


def remove_small_regions(mask, minimum):
    if minimum <= 1:
        return mask
    h, w = mask.shape
    visited = np.zeros_like(mask)
    result = mask.copy()
    for y, x in zip(*np.nonzero(mask)):
        if visited[y, x]:
            continue
        component = [(y, x)]
        queue = deque(component)
        visited[y, x] = True
        while queue:
            yy, xx = queue.popleft()
            for ny, nx in ((yy-1, xx), (yy+1, xx), (yy, xx-1), (yy, xx+1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((ny, nx))
                    component.append((ny, nx))
        if len(component) < minimum:
            for yy, xx in component:
                result[yy, xx] = False
    return result


def apply_selective_color(gray, source, factor, enabled_downsample, rules):
    guide = downsample_color(source, factor, 'median') if enabled_downsample else source
    hue, saturation = hue_saturation(guide)
    sh, sw = source.shape[:2]
    h, w = gray.shape[:2]
    stride = factor if enabled_downsample else 1
    # Source coordinates are used so selections survive factor changes.
    xs = (np.minimum(np.arange(w)*stride+stride//2, sw-1)+0.5)/sw
    ys = (np.minimum(np.arange(h)*stride+stride//2, sh-1)+0.5)/sh
    out = gray.copy()
    for rule in normalize_rules(rules):
        if not rule['enabled']:
            continue
        ref_rgb = np.array(hex_to_rgb(rule['source']))
        if ref_rgb.max()-ref_rgb.min() <= 8:
            continue  # Neutral colors have no useful hue to select.
        ref_hue, _ = hue_saturation(ref_rgb)
        d = np.abs(hue-ref_hue)
        mask = ((np.minimum(d, 360-d) <= rule['tolerance']) & (saturation >= rule['saturation'])
                & (guide.max(axis=2)-guide.min(axis=2) > 8)
                & (gray.mean(axis=2) > rule['dark_limit']))
        if rule['region']:
            l, t, r, b = rule['region']
            mask &= (xs[None, :] >= l) & (xs[None, :] < r) & (ys[:, None] >= t) & (ys[:, None] < b)
        if rule['paint_mask'] is not None:
            mask &= paint_mask_at(rule['paint_mask'], xs, ys, sw, sh)
        target = np.empty_like(gray)
        target[:] = hex_to_rgb(rule['target'])
        tinted = restore_color_hue(gray, target)
        # Invisible white/near-gray pixels must not join otherwise separate accents.
        mask &= np.ptp(tinted.astype(int), axis=2) > 8
        mask = remove_small_regions(mask, rule['min_size'])
        out[mask] = tinted[mask]
    return out


def accent_palette(rules, gray_values):
    """Only accept shades derived from the configured gray palette and target H/S."""
    gray = np.array([[c for c in gray_values]], dtype=np.uint8)
    colors = set()
    for rule in normalize_rules(rules):
        if not rule['enabled']:
            continue
        target = np.empty_like(gray); target[:] = hex_to_rgb(rule['target'])
        colors.update(tuple(map(int, c)) for c in restore_color_hue(gray, target)[0])
    return list(colors)
