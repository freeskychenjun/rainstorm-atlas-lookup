# -*- coding: utf-8 -*-
"""
沿线定向行走：从点位最近的一条等值线出发，沿线条双向行走，走到它的标签处，回答"这条线是多少"。
比 BFS 连通域更可靠：按切线方向逐段前进，遇交叉不串线。
用法:
  python follow_line.py --sheet 1h-Cv --lon 115.5105 --lat 28.9894 [--out-dir DIR] [--max-steps 2500]
输出:
  JSON（stdout + <out>/follow_<sheet>.json）：每条线路的行走方向、长度、途经标签（含标签到点位的距离）
  <out>/follow_<sheet>.jpg：行走轨迹可视化（轨迹着色 + 标签框）
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup import stat_xy, DEFAULT_ATLAS
from parse_atlas import DEFAULT_CACHE
from query_atlas import load_mask, load_labels

KM = 111.0 / 1162.0


def dilate(mask, size=5):
    im = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(size))
    return np.asarray(im) > 0


def nearest_line_pixel(mask, x, y, rmax=600):
    H, W = mask.shape
    best, bd = None, 1e18
    for r in range(10, rmax, 3):
        found = []
        for deg in range(0, 360, 4):
            a = math.radians(deg)
            xx, yy = int(x + r * math.cos(a)), int(y + r * math.sin(a))
            if 0 <= xx < W and 0 <= yy < H and mask[yy, xx]:
                d = math.hypot(xx - x, yy - y)
                found.append((d, xx, yy))
        if found:
            found.sort()
            return found[0][1], found[0][2], found[0][0] * KM
    return None, None, None


def initial_dirs(walk, x, y):
    """在种子周围找线条的两个走向"""
    dirs = []
    for deg in range(0, 360, 3):
        a = math.radians(deg)
        if walk[int(y + 9 * math.sin(a)), int(x + 9 * math.cos(a))]:
            dirs.append(deg)
    if not dirs:
        return [0, 180]
    # 按角度聚类成不超过两组，取组中心
    groups = []
    for d in dirs:
        for g in groups:
            if min(abs(d - g[-1]), 360 - abs(d - g[-1])) <= 12:
                g.append(d); break
        else:
            groups.append([d])
    cents = [sum(g) / len(g) for g in groups]
    if len(cents) >= 2:
        return [cents[0], cents[1]]
    return [cents[0], (cents[0] + 180) % 360]


def walk_line(walk, mask, x, y, deg, labels, max_steps=2500):
    H, W = walk.shape
    d = math.radians(deg)
    px, py = float(x), float(y)
    path = [(px, py)]
    hits = []
    seen_labels = set()
    for step in range(max_steps):
        best = None
        for ddeg in (0, 4, -4, 8, -8, 14, -14, 22, -22, 32, -32, 44, -44):
            a = d + math.radians(ddeg)
            for r in (7, 10, 14, 19, 26, 36, 50, 70, 95):   # 含断口桥接（跨河流/道路/注记）
                nx, ny = px + r * math.cos(a), py + r * math.sin(a)
                ix, iy = int(round(nx)), int(round(ny))
                if 0 <= ix < W and 0 <= iy < H and walk[iy, ix]:
                    score = abs(ddeg) + r * 0.35
                    if best is None or score < best[0]:
                        best = (score, nx, ny, a)
                    break
        if best is None:
            break
        _, nx, ny, a = best
        d = math.atan2(0.65 * math.sin(d) + 0.35 * math.sin(a), 0.65 * math.cos(d) + 0.35 * math.cos(a))
        px, py = nx, ny
        path.append((px, py))
        # 记录途经标签
        for i, c in enumerate(labels):
            if i in seen_labels:
                continue
            if abs(c['cx'] - px) <= 45 + c['w'] / 2 and abs(c['cy'] - py) <= 30 + c['h'] / 2:
                dist = math.hypot(c['cx'] - x, c['cy'] - y) * KM
                hits.append({'label_index': i, 'xy': [int(c['cx']), int(c['cy'])],
                             'dist_km': round(dist, 1), 'walk_steps': step})
                seen_labels.add(i)
        if step > 40 and math.hypot(px - x, py - y) < 6 and len(path) > 60:
            break   # 回到起点（闭合圈）
    return path, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', default='.')
    ap.add_argument('--max-steps', type=int, default=2500)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    mask = load_mask(a.cache, a.sheet)
    labels = load_labels(a.cache, a.sheet)
    src = None
    for f in os.listdir(a.atlas):
        if f.endswith('.jpg') and f.split('--')[1].replace('.jpg', '') == a.sheet:
            src = f
            break
    if src is None:
        print(json.dumps({'error': 'no sheet'}, ensure_ascii=False)); sys.exit(2)
    im = Image.open(os.path.join(a.atlas, src))
    x, y = stat_xy(a.lon, a.lat, *im.size)
    x, y = int(x), int(y)
    walk = dilate(mask, 5)

    sx, sy, sdist = nearest_line_pixel(mask, x, y)
    out = {'sheet': a.sheet, 'point_px': [x, y], 'seed': [sx, sy],
           'seed_dist_km': round(sdist, 1) if sdist else None, 'lines': []}
    vis = np.full(mask.shape + (3,), 255, np.uint8)
    vis[mask] = [225, 190, 190]
    ov = Image.fromarray(vis)
    dr = ImageDraw.Draw(ov)
    for c in labels:
        dr.rectangle((c['x0'] - 4, c['y0'] - 4, c['x1'] + 4, c['y1'] + 4), outline=(0, 0, 230), width=6)
    dr.line((x - 80, y, x + 80, y), fill=(0, 170, 0), width=12)
    dr.line((x, y - 80, x, y + 80), fill=(0, 170, 0), width=12)

    if sx is not None:
        dirs = initial_dirs(walk, sx, sy)
        for di, deg in enumerate(dirs[:2]):
            path, hits = walk_line(walk, mask, sx, sy, deg, labels, a.max_steps)
            pts = [(int(px), int(py)) for px, py in path]
            col = (200, 30, 30) if di == 0 else (30, 90, 200)
            if len(pts) > 1:
                dr.line(pts, fill=col, width=7)
            plen_km = 0.0
            for i in range(1, len(path)):
                plen_km += math.hypot(path[i][0] - path[i-1][0], path[i][1] - path[i-1][1]) * KM
            out['lines'].append({'dir_deg': round(deg, 1), 'steps': len(path),
                                 'length_km': round(plen_km, 1), 'labels': hits})
    R = 2400
    box = (max(x - R, 0), max(y - R, 0), min(x + R, im.size[0]), min(y + R, im.size[1]))
    vis_path = os.path.join(a.out_dir, 'follow_%s.jpg' % a.sheet)
    ov.crop(box).resize(((box[2] - box[0]) // 3, (box[3] - box[1]) // 3)).save(vis_path, quality=88)
    out['vis'] = vis_path
    with open(os.path.join(a.out_dir, 'follow_%s.json' % a.sheet), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
