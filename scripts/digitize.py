# -*- coding: utf-8 -*-
"""
等值线数字化（正式版）：
 1) 提取图幅上的等值线，合并被断开的碎段（含闭合圈），逐条编号 L1、L2…
 2) 读取人工圈注值（cache/marks_values.json + marks7/<sheet>/marks.json），
    按"标注到线条的实际最近距离"把值挂到对应线（闭合圈优先按圈内包含判定）
 3) 输出每幅图 3 页（上/中/下）编号图：绿字=已有值，红字=待补值
用法: python digitize.py [--sheet 1h-Cv] [--out-dir DIR]
"""
import argparse, json, math, os, sys
from collections import deque
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_atlas import runs_per_row, group_runs, DEFAULT_ATLAS, DEFAULT_CACHE

KM = 111.0 / 1162.0
MARKED_DIR = r'D:\DSH工作区\自动查找图集参数\查图_吊钟水库\marks7'


def contour_mask(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 145) & ((R - G) > 80) & ((R - B) > 80)


def font(size):
    for p in (r'C:\Windows\Fonts\msyhbd.ttc', r'C:\Windows\Fonts\msyh.ttc'):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def endpoints(g):
    g2 = sorted(g, key=lambda r: r[0])
    return ((g2[0][1] + g2[0][2]) // 2, g2[0][0]), ((g2[-1][1] + g2[-1][2]) // 2, g2[-1][0])


def inside_region(mask, cx, cy, box, limit=300000):
    x0, y0, x1, y1 = box
    if not (x0 < cx < x1 and y0 < cy < y1):
        return False
    seen = {(cx, cy)}
    q = deque([(cx, cy)])
    n = 0
    while q:
        x, y = q.popleft()
        n += 1
        if n > limit:
            return True
        if x <= x0 or x >= x1 or y <= y0 or y >= y1:
            return False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or mask[ny, nx]:
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
    return True


def build_lines(path, min_px=1200, merge_px=60):
    im = Image.open(path).convert('RGB')
    W, H = im.size
    mask = contour_mask(path)
    groups = group_runs(runs_per_row(mask))
    comps = []
    for g in groups:
        npix = sum(r[2] - r[1] for r in g)
        if npix < min_px:
            continue
        x0 = min(r[1] for r in g); x1 = max(r[2] for r in g)
        y0 = min(r[0] for r in g); y1 = max(r[0] for r in g)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        w, h = x1 - x0, y1 - y0
        if (cx > 0.78 * W and cy > 0.72 * H) or cy > 0.955 * H:
            continue
        if w < 160 and h < 160:
            continue
        if w < 260 and h < 260 and npix / max(w * h, 1) > 0.12:
            continue
        step = max(len(g) // 4, 1)
        anchors = [((r[1] + r[2]) // 2, r[0]) for r in g[::step]]
        samples = [((r[1] + r[2]) // 2, r[0]) for r in g[::max(len(g) // 400, 1)]]
        comps.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, npix=npix,
                          anchors=anchors, samples=samples, ends=list(endpoints(g)), runs=g))
    parent = list(range(len(comps)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            A, B = comps[i], comps[j]
            if A['x1'] < B['x0'] - 60 or B['x1'] < A['x0'] - 60 or A['y1'] < B['y0'] - 60 or B['y1'] < A['y0'] - 60:
                continue
            d = min(math.hypot(pa[0] - pb[0], pa[1] - pb[1]) for pa in A['ends'] for pb in B['ends'])
            if d <= merge_px:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[rb] = ra
    fused = {}
    for i, c in enumerate(comps):
        fused.setdefault(find(i), []).append(c)
    lines = []
    for _, v in fused.items():
        x0 = min(c['x0'] for c in v); x1 = max(c['x1'] for c in v)
        y0 = min(c['y0'] for c in v); y1 = max(c['y1'] for c in v)
        anchors = [p for c in v for p in c['anchors']]
        samples = [p for c in v for p in c['samples']]
        anchors.sort(key=lambda p: p[1])
        lines.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, anchors=anchors, samples=samples,
                          npix=sum(c['npix'] for c in v), runs=[r for c in v for r in c['runs']]))
    # 闭合判定（该线自身能否围住中心）
    for c in lines:
        lx0, ly0 = c['x0'] - 4, c['y0'] - 4
        lx1, ly1 = c['x1'] + 5, c['y1'] + 5
        sub = np.zeros((max(ly1 - ly0, 1), max(lx1 - lx0, 1)), dtype=bool)
        for (y, s0, e0) in c['runs']:
            yy = y - ly0
            if 0 <= yy < sub.shape[0]:
                sub[yy, max(s0 - lx0, 0):max(e0 - lx0, 1)] = True
        c['closed'] = inside_region(sub, (c['x0'] + c['x1']) // 2 - lx0,
                                    (c['y0'] + c['y1']) // 2 - ly0,
                                    (0, 0, sub.shape[1] - 1, sub.shape[0] - 1))
    lines.sort(key=lambda c: (c['y0'] // 500, c['x0']))
    for i, c in enumerate(lines, 1):
        c['id'] = 'L%d' % i
    return im, W, H, lines


def attach_values(lines, marks, vals):
    """把人工圈注值挂到线上：先按圈内包含（闭合圈），再按到线条的实际最近距离"""
    for c in lines:
        c['value'] = None
        c['from_mark'] = None
    for idx, m in marks.items():
        v = vals.get(str(idx))
        if not v:
            continue
        mx, my = m['cx'], m['cy']
        best, bd = None, 1e18
        for c in lines:
            if c['closed'] and c['x0'] <= mx <= c['x1'] and c['y0'] <= my <= c['y1']:
                d = min(math.hypot(mx - sx, my - sy) for sx, sy in c['samples'])
                if d > 25:      # 在圈内且离线圈本身较远 → 判为该闭合圈的值
                    best, bd = c, 0.0
                    break
            d = min(math.hypot(mx - sx, my - sy) for sx, sy in c['samples'])
            if d < bd:
                bd, best = d, c
        if best is not None and bd <= 70:
            if best['value'] is None:
                best['value'] = v
                best['from_mark'] = idx
    return lines


def render(im, W, H, lines, out_prefix, npages=3, scale=0.30):
    pages = []
    step = H // npages
    for pi in range(npages):
        ya, yb = pi * step, (pi + 1) * step if pi < npages - 1 else H
        crop = im.crop((0, ya, W, yb))
        d = ImageDraw.Draw(crop)
        for c in lines:
            col = (0, 140, 0) if c['value'] else (200, 0, 0)
            txt = c['id'] + ('=' + str(c['value']) if c['value'] else '') + ('·闭' if c['closed'] else '')
            placed = 0
            for (ax, ay) in c['anchors']:
                if not (ya + 10 <= ay < yb - 10):
                    continue
                if placed >= 3:
                    break
                px, py = ax, ay - ya
                d.text((px + 12, py - 44), txt, fill=(255, 255, 255), font=font(54))
                d.text((px + 10, py - 46), txt, fill=col, font=font(54))
                placed += 1
        out = '%s_p%d.jpg' % (out_prefix, pi + 1)
        crop.resize((int(W * scale), int((yb - ya) * scale))).save(out, quality=88)
        pages.append(out)
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default='')
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    mv = json.load(open(os.path.join(a.cache, 'marks_values.json'), encoding='utf-8'))
    sheets = [a.sheet] if a.sheet else [k for k in mv if not k.startswith('_')]
    for key in sheets:
        src = mv[key]['sheet']
        vals = mv[key]['values']
        m2 = os.path.join(MARKED_DIR, key, 'marks2.json')
        mpath = m2 if os.path.isfile(m2) else os.path.join(MARKED_DIR, key, 'marks.json')
        marks = {i: m for i, m in enumerate(json.load(open(mpath, encoding='utf-8')))} if os.path.isfile(mpath) else {}
        im, W, H, lines = build_lines(os.path.join(a.atlas, src))
        lines = attach_values(lines, marks, vals)
        lp2 = os.path.join(a.cache, 'manual_labels_v2', key + '_lines.json')
        lp = lp2 if os.path.isfile(lp2) else os.path.join(a.cache, 'manual_labels', key + '_lines.json')
        if os.path.isfile(lp):
            for c in lines:
                v = json.load(open(lp, encoding='utf-8')).get(c['id'])
                if v:
                    c['value'] = v
        pages = render(im, W, H, lines, os.path.join(a.out_dir, 'digit_%s' % key))
        nk = sum(1 for c in lines if c['value'])
        ncl = sum(1 for c in lines if c['closed'])
        json.dump({'sheet': src, 'n_lines': len(lines), 'n_closed': ncl, 'n_valued': nk,
                   'pages': pages,
                   'lines': [{'id': c['id'], 'closed': c['closed'], 'value': c['value'],
                              'from_mark': c['from_mark'], 'npix': c['npix'],
                              'bbox': [c['x0'], c['y0'], c['x1'], c['y1']]} for c in lines]},
                  open(os.path.join(a.out_dir, 'digit_%s.json' % key), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('%-8s 线 %2d 条（闭合 %d）  已挂值 %2d 条  待补 %2d 条'
              % (key, len(lines), ncl, nk, len(lines) - nk))


if __name__ == '__main__':
    main()
