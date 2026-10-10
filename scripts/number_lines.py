# -*- coding: utf-8 -*-
"""
全线编号图 v2：正确处理闭合等值线
 - 端点相接的碎段合并为同一条线（闭合圈被标签/河流断开的情况）
 - 闭合圈：其值写在圈内，故优先在圈内区域搜索标签赋值
 - 输出上下两半页，绿字=已知值，红字=待补值
用法: python number_lines.py --sheet 1h-Pa --out-dir DIR
"""
import argparse, json, math, os, sys
from collections import deque
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_atlas import runs_per_row, group_runs, DEFAULT_ATLAS, DEFAULT_CACHE

KM = 111.0 / 1162.0


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
    y0, s0, e0 = g2[0]
    y1, s1, e1 = g2[-1]
    return ((s0 + e0) // 2, y0), ((s1 + e1) // 2, y1)


def inside_region(mask, cx, cy, box, limit=400000):
    """从 (cx,cy) 洪水填充，若无法逃出 box 则说明该点被线条包围（闭合圈内部）"""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', required=True)
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--min-px', type=int, default=1200)
    ap.add_argument('--merge-px', type=int, default=320)
    ap.add_argument('--scale', type=float, default=0.34)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    src = [f for f in os.listdir(a.atlas)
           if f.endswith('.jpg') and f.split('--')[1].replace('.jpg', '') == a.sheet][0]
    path = os.path.join(a.atlas, src)
    im = Image.open(path).convert('RGB')
    W, H = im.size
    mask = contour_mask(path)
    groups = group_runs(runs_per_row(mask))

    comps = []
    for g in groups:
        npix = sum(r[2] - r[1] for r in g)
        if npix < a.min_px:
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
        step = max(len(g) // 3, 1)
        anchors = [((r[1] + r[2]) // 2, r[0]) for r in g[::step]]
        comps.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, cx=cx, cy=cy, npix=int(npix),
                          anchors=anchors, ends=list(endpoints(g)), runs=g))

    # 合并端点相接的碎段
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
            if d <= a.merge_px:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[rb] = ra

    fused = {}
    for i, c in enumerate(comps):
        fused.setdefault(find(i), []).append(c)
    lines = []
    for _, v in fused.items():
        anchors = [p for c in v for p in c['anchors']]
        x0 = min(c['x0'] for c in v); x1 = max(c['x1'] for c in v)
        y0 = min(c['y0'] for c in v); y1 = max(c['y1'] for c in v)
        ends = [p for c in v for p in c['ends']]
        far = max(((p, q) for p in ends for q in ends),
                  key=lambda pq: math.hypot(pq[0][0] - pq[1][0], pq[0][1] - pq[1][1]))
        gap = math.hypot(far[0][0] - far[1][0], far[0][1] - far[1][1])
        diag = math.hypot(x1 - x0, y1 - y0)
        lines.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, npix=sum(c['npix'] for c in v),
                          anchors=anchors, closed=False, gap=gap, diag=diag,
                          runs=[r for c in v for r in c['runs']]))
    lines.sort(key=lambda c: (c['y0'] // 500, c['x0']))
    for i, c in enumerate(lines, 1):
        c['id'] = 'L%d' % i

    # 值：人工标注（闭合圈取圈内标注）
    manual = []
    mpath = os.path.join(a.cache, 'manual_labels', a.sheet + '.json')
    if os.path.isfile(mpath):
        manual += [m for m in json.load(open(mpath, encoding='utf-8'))['labels'] if m.get('val')]
    for c in lines:
        c['value'] = None
        c['interior'] = False
        # 用"该线自身能否围住 bbox 中心"判定闭合圈（闭合圈的值写在圈内）
        lx0, ly0 = c['x0'] - 4, c['y0'] - 4
        lx1, ly1 = c['x1'] + 5, c['y1'] + 5
        sub = np.zeros((max(ly1 - ly0, 1), max(lx1 - lx0, 1)), dtype=bool)
        for (y, s0, e0) in c['runs']:
            yy = y - ly0
            if 0 <= yy < sub.shape[0]:
                sub[yy, max(s0 - lx0, 0):max(e0 - lx0, 1)] = True
        tx = (c['x0'] + c['x1']) // 2 - lx0
        ty = (c['y0'] + c['y1']) // 2 - ly0
        c['closed'] = inside_region(sub, tx, ty, (0, 0, sub.shape[1] - 1, sub.shape[0] - 1))
        if c['closed']:
            c['interior'] = True
            for m in manual:
                if c['x0'] <= m['cx'] <= c['x1'] and c['y0'] <= m['cy'] <= c['y1']:
                    c['value'] = m['val']; break
        if c['value'] is None:
            best, bd = None, 1e18
            for m in manual:
                for (ax, ay) in c['anchors']:
                    d = math.hypot(ax - m['cx'], ay - m['cy'])
                    if d < bd:
                        bd, best = d, m
            if best and bd <= 90:
                c['value'] = best['val']

    pages = []
    for pi, (ya, yb) in enumerate([(0, H // 2), (H // 2, H)]):
        crop = im.crop((0, ya, W, yb))
        d = ImageDraw.Draw(crop)
        for c in lines:
            col = (0, 140, 0) if c['value'] else (200, 0, 0)
            txt = c['id'] + ('=' + c['value'] if c['value'] else '') + ('·闭合' if c['closed'] else '')
            for (ax, ay) in c['anchors']:
                if not (ya <= ay < yb):
                    continue
                px, py = ax, ay - ya
                d.text((px + 12, py - 46), txt, fill=(255, 255, 255), font=font(56))
                d.text((px + 10, py - 48), txt, fill=col, font=font(56))
        out = os.path.join(a.out_dir, 'numbered_%s_p%d.jpg' % (a.sheet, pi + 1))
        crop.resize((int(W * a.scale), int((yb - ya) * a.scale))).save(out, quality=88)
        pages.append(out)

    json.dump({'sheet': src, 'n_lines': len(lines), 'pages': pages,
               'lines': [{'id': c['id'], 'closed': c['closed'], 'closed_inside': c['interior'],
                          'value': c['value'], 'npix': c['npix'],
                          'bbox': [c['x0'], c['y0'], c['x1'], c['y1']]} for c in lines]},
              open(os.path.join(a.out_dir, 'numbered_%s.json' % a.sheet), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('%s: 合并后 %d 条线（闭合圈 %d 条），已知值 %d 条'
          % (a.sheet, len(lines), sum(1 for c in lines if c['closed']),
             sum(1 for c in lines if c['value'])))


if __name__ == '__main__':
    main()
