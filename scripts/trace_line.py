# -*- coding: utf-8 -*-
"""
沿线追踪：从点位附近的等值线出发，沿线条（含小间断）走到它的标签处，回答"这条线是多少"。
用法:
  python trace_line.py --sheet 1h-Cv --lon 115.5105 --lat 28.9894 [--radius 2000] [--out-dir DIR]
输出:
  JSON：每条追踪到的线条 → 距离点位、追踪像素数、沿途遇到的标签（含标签坐标与距离）
  <out>/trace_<sheet>.jpg：追踪结果可视化（线条着色 + 标签框）
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup import stat_xy, DEFAULT_ATLAS
from parse_atlas import DEFAULT_CACHE
from query_atlas import load_mask, load_labels

KM = 111.0 / 1162.0


def dilate(mask, size=7):
    im = Image.fromarray((mask * 255).astype(np.uint8))
    im = im.filter(ImageFilter.MaxFilter(size))
    return np.asarray(im) > 0


def bfs_component(start, walk, limit=4_000_000):
    """在 walk 掩膜上从 start 做 BFS，返回访问到的像素列表"""
    H, W = walk.shape
    from collections import deque
    seen = np.zeros_like(walk, dtype=bool)
    q = deque([start])
    seen[start[1], start[0]] = True
    pts = []
    while q:
        x, y = q.popleft()
        pts.append((x, y))
        if len(pts) > limit:
            break
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and walk[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((nx, ny))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', required=True, help='缓存键，如 1h-Cv / 24h-Pa / zone-产流')
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--radius', type=float, default=2500, help='从点位多远处开始找线条（px）')
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', default='.')
    ap.add_argument('--max-pixels', type=int, default=400000, help='单条线追踪上限（防跑遍全图）')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    mask = load_mask(a.cache, a.sheet)
    labels = load_labels(a.cache, a.sheet)
    # 点位像素
    src = None
    for fn, key in [(f, f.split('--')[1].replace('.jpg', '')) for f in os.listdir(a.atlas) if f.endswith('.jpg')]:
        if key == a.sheet:
            src = fn
            break
    if src is None:
        print(json.dumps({'error': '找不到图幅 %s' % a.sheet}, ensure_ascii=False)); sys.exit(2)
    im = Image.open(os.path.join(a.atlas, src))
    x, y = stat_xy(a.lon, a.lat, *im.size)
    x, y = int(x), int(y)

    walk = dilate(mask, 7)
    H, W = walk.shape
    # 收集半径内所有线条像素作为种子
    y0, y1 = max(y - int(a.radius), 0), min(y + int(a.radius), H)
    x0, x1 = max(x - int(a.radius), 0), min(x + int(a.radius), W)
    sub = mask[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub)
    seeds = list(zip(xs + x0, ys + y0))

    covered = np.zeros_like(mask, dtype=bool)
    lines_out = []
    for s in seeds[::17]:                     # 稀疏采样，避免重复追踪同一条线
        if covered[s[1], s[0]]:
            continue
        pts = bfs_component(s, walk, limit=a.max_pixels)
        for (px, py) in pts:
            covered[py, px] = True
        # 该线条上的标签
        ptset = np.array(pts)
        found = []
        for i, c in enumerate(labels):
            if (c['x0'] - 8 <= ptset[:, 0]).any() and (ptset[:, 0] <= c['x1'] + 8).any() and \
               (c['y0'] - 8 <= ptset[:, 1]).any() and (ptset[:, 1] <= c['y1'] + 8).any():
                # 精确判断：标签框附近是否有轨迹点
                m = ((ptset[:, 0] >= c['x0'] - 10) & (ptset[:, 0] <= c['x1'] + 10) &
                     (ptset[:, 1] >= c['y0'] - 10) & (ptset[:, 1] <= c['y1'] + 10))
                if m.any():
                    dmin = math.hypot(c['cx'] - x, c['cy'] - y) * KM
                    found.append({'label_index': int(i), 'xy': [int(c['cx']), int(c['cy'])], 'dist_km': round(dmin, 1)})
        dseed = math.hypot(s[0] - x, s[1] - y) * KM
        if len(pts) > 60 or found:
            lines_out.append({'seed': [int(s[0]), int(s[1])], 'seed_dist_km': round(dseed, 1),
                              'pixels': len(pts),
                              'reach_km': round(len(pts) * KM / 3, 1),
                              'labels': found})
    lines_out.sort(key=lambda L: L['seed_dist_km'])

    # 可视化
    vis = np.full(mask.shape + (3,), 255, np.uint8)
    vis[mask] = [210, 40, 40]
    ov = Image.fromarray(vis)
    d = ImageDraw.Draw(ov)
    for c in labels:
        d.rectangle((c['x0'] - 4, c['y0'] - 4, c['x1'] + 4, c['y1'] + 4), outline=(0, 0, 220), width=6)
    d.line((x - 70, y, x + 70, y), fill=(0, 170, 0), width=12)
    d.line((x, y - 70, x, y + 70), fill=(0, 170, 0), width=12)
    R = 1700
    box = (max(x - R, 0), max(y - R, 0), min(x + R, W), min(y + R, H))
    ov.crop(box).resize(((box[2] - box[0]) // 2, (box[3] - box[1]) // 2)).save(
        os.path.join(a.out_dir, 'trace_%s.jpg' % a.sheet), quality=88)

    result = {'sheet': a.sheet, 'point_px': [x, y],
              'lines': lines_out[:14],
              'vis': os.path.join(a.out_dir, 'trace_%s.jpg' % a.sheet)}
    with open(os.path.join(a.out_dir, 'trace_%s.json' % a.sheet), 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
