# -*- coding: utf-8 -*-
"""拆分 3d-Pa 的过度合并线 L3：按 60px 端点阈值把 L3 拆成真实分段，
近段（花桥西侧，站值135.6压线）=150，北段（标签180）=180；
写入 3d-Pa_extra_lines.json（M1/M2），并在 3d-Pa_lines.json 标记排除原 L3。"""
import json, math, os, sys, io
from collections import deque
import numpy as np

sys.path.insert(0, r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\scripts')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from digitize import build_lines

cache = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache'
atlas = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
mv = json.load(open(os.path.join(cache, 'marks_values.json'), encoding='utf-8'))['3d-Pa']
im, W, H, lines = build_lines(os.path.join(atlas, mv['sheet']))
L3 = next(c for c in lines if c['id'] == 'L3')
print('L3 原始：像素%d 采样%d bbox=%s' % (L3['npix'], len(L3['samples']), (L3['x0'], L3['y0'], L3['x1'], L3['y1'])))

# 用 L3 的 runs 重建子连通分量（60px 端点阈值）
runs = L3['runs']
def endpoints(g):
    g2 = sorted(g, key=lambda r: r[0])
    return ((g2[0][1] + g2[0][2]) // 2, g2[0][0]), ((g2[-1][1] + g2[-1][2]) // 2, g2[-1][0])

# 先把 runs 按行连续段分组（runs 之间行连续且列重叠 => 同一笔段）
segs = []
for r in sorted(runs, key=lambda r: (r[0], r[1])):
    y, x0, x1 = r
    placed = False
    for s in segs:
        if abs(s['y1'] - y) <= 1 and not (x1 < s['x0'] - 2 or x0 > s['x1'] + 2):
            s['runs'].append(r); s['y1'] = y
            s['x0'] = min(s['x0'], x0); s['x1'] = max(s['x1'], x1)
            placed = True
            break
    if not placed:
        segs.append({'runs': [r], 'y0': y, 'y1': y, 'x0': x0, 'x1': x1})
print('L3 内部笔画段数：', len(segs))

# 并查集按 60px 端点距离合并
par = list(range(len(segs)))
def find(x):
    while par[x] != x:
        par[x] = par[par[x]]; x = par[x]
    return x
for i in range(len(segs)):
    for j in range(i + 1, len(segs)):
        A, B = segs[i], segs[j]
        if A['x1'] < B['x0'] - 70 or B['x1'] < A['x0'] - 70 or A['y1'] < B['y0'] - 70 or B['y1'] < A['y0'] - 70:
            continue
        ea = endpoints(A['runs']); eb = endpoints(B['runs'])
        d = min(math.hypot(pa[0] - pb[0], pa[1] - pb[1]) for pa in ea for pb in eb)
        if d <= 60:
            ra, rb = find(i), find(j)
            if ra != rb:
                par[rb] = ra
groups = {}
for i in range(len(segs)):
    groups.setdefault(find(i), []).append(segs[i])
print('按60px阈值拆出子段数：', len(groups))

qx, qy = 4398, 2738          # 花桥点位
nx, ny = 4502, 2640          # 北段种子
pieces = []
for _, gs in groups.items():
    pts = [(r[1] + r[2]) // 2 for s in gs for r in s['runs']]
    ys = [r[0] for s in gs for r in s['runs']]
    npix = sum(r[2] - r[1] for s in gs for r in s['runs'])
    if npix < 300:
        continue
    d_q = min(math.hypot(px - qx, py - qy) for px, py in zip(pts, ys))
    d_n = min(math.hypot(px - nx, py - ny) for px, py in zip(pts, ys))
    pieces.append({'npix': npix, 'd_point': d_q * 111 / 1162, 'd_north': d_n * 111 / 1162,
                   'bbox': (min(pts), min(ys), max(pts), max(ys))})
pieces.sort(key=lambda p: p['d_point'])
print('拆分后各子段（按距点位排序）：')
for i, p in enumerate(pieces):
    print('  #%d 像素%5d 距点位%6.1fkm 距北种子%6.1fkm bbox=%s' % (i, p['npix'], p['d_point'], p['d_north'], p['bbox']))

# ---- 落盘：M1=近段(150)、M2=北段(#1+#2 合并,180)；保留原 L3（不破坏其他点位的远段） ----
def poly_of(gs, step=14):
    pts = sorted([(r[0], (r[1] + r[2]) // 2) for s in gs for r in s['runs']], key=lambda t: (t[0], t[1]))
    if len(pts) > 400:
        k = len(pts) // 400
        pts = pts[::k]
    k2 = max(len(pts) // step, 1)
    out = [[int(x), int(y)] for y, x in pts[::k2]]
    if not out or out[-1] != [int(pts[-1][1]), int(pts[-1][0])]:
        out.append([int(pts[-1][1]), int(pts[-1][0])])
    return out

# 近段 = 距点位最近且像素≥1000 的子段
near = next(p for p in pieces if p['npix'] >= 1000 and p['d_point'] < 20)
# 北段 = 距北种子最近的两个子段（#2 与其东北的 #1）
north_cands = sorted([p for p in pieces if p is not near], key=lambda p: p['d_north'])[:2]
print('近段: 像素%d 距点位%.1fkm' % (near['npix'], near['d_point']))
print('北段: ' + ', '.join('像素%d 距北种子%.1fkm' % (p['npix'], p['d_north']) for p in north_cands))

# 取各 piece 对应的 gs
def gs_of(piece):
    return [s for _, g in groups.items() for s in g
            if sum(r[2] - r[1] for r in s['runs']) and
            abs(min(r[1] + r[2] for r in s['runs']) // 2 - piece['bbox'][0]) < 1e9 and
            (min(r[0] for r in s['runs']), min(r[1] for r in s['runs'])) >= (0, 0) and
            piece['bbox'][0] <= min(r[1] + r[2] for r in s['runs']) // 2 <= piece['bbox'][2] and
            piece['bbox'][1] <= min(r[0] for r in s['runs']) <= piece['bbox'][3]]

# 稳定做法：直接按 bbox 归属重建 groups 映射
key2gs = {}
for k, gs in groups.items():
    pts = [(r[1] + r[2]) // 2 for s in gs for r in s['runs']]
    ys = [r[0] for s in gs for r in s['runs']]
    key2gs[(min(pts), min(ys), max(pts), max(ys))] = gs
near_gs = key2gs[near['bbox']]
north_gs = [s for p in north_cands for s in key2gs[p['bbox']]]

recs = [
    {'id': 'M1', 'value': '150', 'closed': False,
     'source': 'L3拆分-近段（花桥西2.6km，站值135.6/44压线），2026-10-09',
     'polyline_px': poly_of(near_gs)},
    {'id': 'M2', 'value': '180', 'closed': False,
     'source': 'L3拆分-北段（人工辨认标签180），2026-10-09',
     'polyline_px': poly_of(north_gs)},
]
ep = os.path.join(cache, 'manual_labels', '3d-Pa_extra_lines.json')
json.dump(recs, open(ep, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('已写入 %s' % ep)
for r in recs:
    print('  %s=%s 折线%d点 %s' % (r['id'], r['value'], len(r['polyline_px']), r['polyline_px'][:3]))

