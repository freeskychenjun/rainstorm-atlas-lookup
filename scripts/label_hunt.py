# -*- coding: utf-8 -*-
"""
沿线找标签：沿点位最近的等值线行走，凡遇到线条断口（>=40px，通常就是标注处）就把断口处裁图，
拼成一页供人工辨认——解决"标签沿线条斜排、被误并入线条而漏检"的问题。
用法: python label_hunt.py --sheet 6h-Cv --lon 115.5105 --lat 28.9894 --out-dir DIR
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup import stat_xy, DEFAULT_ATLAS
from parse_atlas import DEFAULT_CACHE
from query_atlas import load_mask
from follow_line import dilate, initial_dirs, nearest_line_pixel

KM = 111.0 / 1162.0


def walk_with_gaps(mask, walk, x, y, deg, max_steps=4000):
    """返回 (path, gaps)；gaps = [(中点点位, 跳跃距离)]"""
    H, W = walk.shape
    d = math.radians(deg)
    px, py = float(x), float(y)
    path = [(px, py)]
    gaps = []
    for _ in range(max_steps):
        best = None
        for ddeg in (0, 4, -4, 8, -8, 14, -14, 22, -22, 32, -32, 44, -44):
            a = d + math.radians(ddeg)
            for r in (7, 10, 14, 19, 26, 36, 50, 70, 95):
                nx, ny = px + r * math.cos(a), py + r * math.sin(a)
                ix, iy = int(round(nx)), int(round(ny))
                if 0 <= ix < W and 0 <= iy < H and walk[iy, ix]:
                    score = abs(ddeg) + r * 0.35
                    if best is None or score < best[0]:
                        best = (score, nx, ny, a, r)
                    break
        if best is None:
            break
        _, nx, ny, a, r = best
        if r >= 25:
            gaps.append(((px + nx) / 2, (py + ny) / 2, r))
        d = math.atan2(0.65 * math.sin(d) + 0.35 * math.sin(a), 0.65 * math.cos(d) + 0.35 * math.cos(a))
        px, py = nx, ny
        path.append((px, py))
        if len(path) > 60 and math.hypot(px - x, py - y) < 6:
            break
    return path, gaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', default='.')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    mask = load_mask(a.cache, a.sheet)
    src = [f for f in os.listdir(a.atlas)
           if f.endswith('.jpg') and f.split('--')[1].replace('.jpg', '') == a.sheet][0]
    im = Image.open(os.path.join(a.atlas, src)).convert('RGB')
    x, y = stat_xy(a.lon, a.lat, *im.size)
    x, y = int(x), int(y)
    walk = dilate(mask, 5)
    sx, sy, sd = nearest_line_pixel(mask, x, y)
    gaps_all = []
    for deg in initial_dirs(walk, sx, sy)[:2]:
        path, gaps = walk_with_gaps(mask, walk, sx, sy, deg)
        for gx, gy, r in gaps:
            d = math.hypot(gx - x, gy - y) * KM
            gaps_all.append((round(d, 1), int(gx), int(gy), int(r)))
    gaps_all.sort()
    # 去掉彼此靠近的重复断口
    uniq = []
    for g in gaps_all:
        if all(math.hypot(g[1] - u[1], g[2] - u[2]) > 60 for u in uniq):
            uniq.append(g)
    print('断口数(去重后):', len(uniq), ' 其中 <=160km:', sum(1 for g in uniq if g[0] <= 160))
    sel = [g for g in uniq if g[0] <= 160][:28]
    tile = (250, 165); cols = 5
    rows = max((len(sel) + cols - 1) // cols, 1)
    cv = Image.new('RGB', (cols * tile[0], rows * (tile[1] + 18)), (255, 255, 255))
    dr = ImageDraw.Draw(cv)
    for i, (d, gx, gy, r) in enumerate(sel):
        box = (max(gx - 125, 0), max(gy - 80, 0), min(gx + 125, im.size[0]), min(gy + 80, im.size[1]))
        crop = im.crop(box).resize((tile[0] - 8, tile[1] - 8))
        rr, cc = divmod(i, cols)
        cv.paste(crop, (cc * tile[0] + 4, rr * (tile[1] + 18) + 16))
        dr.text((cc * tile[0] + 4, rr * (tile[1] + 18) + 2), '%.0fkm r=%d' % (d, r), fill=(0, 0, 200))
    out = os.path.join(a.out_dir, 'gaps_%s.jpg' % a.sheet)
    cv.save(out, quality=92)
    json.dump({'sheet': a.sheet, 'seed_dist_km': round(sd, 1),
               'gaps': uniq[:60], 'montage': out},
              open(os.path.join(a.out_dir, 'gaps_%s.json' % a.sheet), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(json.dumps({'montage': out, 'n': len(sel)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

