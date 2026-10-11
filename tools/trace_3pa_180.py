# -*- coding: utf-8 -*-
"""从 3d-Pa 图幅描出被漏检的北侧 180 线（花桥流域重心北面），存入手工线库"""
import json, math, os, sys, io
from collections import deque
import numpy as np
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
base = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
im = Image.open(os.path.join(base, '7--3d-Pa.jpg')).convert('RGB')
a = np.asarray(im).astype(np.int16)
R, G, B = a[..., 0], a[..., 1], a[..., 2]
mask = (R > 145) & ((R - G) > 80) & ((R - B) > 80)
H, W = mask.shape

seed = (4502, 2640)   # 网格扫描定位：北侧曲线实际位置
best, bd = None, 1e18
for dy in range(-40, 41):
    for dx in range(-40, 41):
        yy, xx = seed[1] + dy, seed[0] + dx
        if 0 <= yy < H and 0 <= xx < W and mask[yy, xx]:
            d2 = dx * dx + dy * dy
            if d2 < bd:
                bd, best = d2, (xx, yy)
print('种子吸附到红色像素:', best, '距离%.0fpx' % math.sqrt(bd))

X0, Y0, X1, Y1 = 4150, 2450, 4950, 2695   # 局部盒：北侧曲线范围
comp = set()
q = deque([best])
while q:
    x, y = q.popleft()
    if (x, y) in comp:
        continue
    if not (X0 <= x <= X1 and Y0 <= y <= Y1):
        continue
    if not mask[y, x]:
        continue
    comp.add((x, y))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                q.append((x + dx, y + dy))
print('连通分量像素数:', len(comp))
if len(comp) < 200:
    print('⚠ 像素太少，中止')
    sys.exit(2)

pts = sorted(comp, key=lambda p: p[0])
step = max(len(pts) // 14, 1)
poly = [pts[i] for i in range(0, len(pts), step)]
if pts[-1] != poly[-1]:
    poly.append(pts[-1])

qx, qy = 4398, 2735
dmin = min(math.hypot(px - qx, py - qy) for px, py in comp) * 111.0 / 1162.0
print('该线距花桥点位最近 %.1f km' % dmin)

rec = {'id': 'M2', 'value': '180', 'closed': False,
       'source': '人工补描（北侧漏检线，值按人工辨认180），2026-10-09',
       'polyline_px': [[int(px), int(py)] for px, py in poly]}
out = os.path.join(r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache\manual_labels',
                   '3d-Pa_extra_lines.json')
lst = []
if os.path.isfile(out):
    lst = json.load(open(out, encoding='utf-8'))
lst = [r for r in lst if r['id'] != 'M2']
lst.append(rec)
json.dump(lst, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('折线 %d 点已写入 %s' % (len(poly), out))
print('折线:', rec['polyline_px'])
