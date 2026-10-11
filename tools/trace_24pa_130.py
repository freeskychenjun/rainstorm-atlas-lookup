# -*- coding: utf-8 -*-
"""从 24h-Pa 图幅描出被漏检的 130 短线（花桥流域重心南侧），存入手工线库"""
import json, math, os, sys, io
from collections import deque
import numpy as np
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
base = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
im = Image.open(os.path.join(base, '5--24h-Pa.jpg')).convert('RGB')
a = np.asarray(im).astype(np.int16)
R, G, B = a[..., 0], a[..., 1], a[..., 2]
mask = (R > 145) & ((R - G) > 80) & ((R - B) > 80)
H, W = mask.shape

# 种子：两标签之间的线上点（放大视场中 displayed(700,430) → 原图）
seed = (4431, 2811)
# 找种子附近最近的红色像素
best, bd = None, 1e18
for dy in range(-40, 41):
    for dx in range(-40, 41):
        yy, xx = seed[1] + dy, seed[0] + dx
        if 0 <= yy < H and 0 <= xx < W and mask[yy, xx]:
            d2 = dx * dx + dy * dy
            if d2 < bd:
                bd, best = d2, (xx, yy)
print('种子吸附到红色像素:', best, '距离%.0fpx' % math.sqrt(bd))

# 连通分量追踪（8连通），限制在局部盒内防止并入其他线
X0, Y0, X1, Y1 = 4150, 2700, 4820, 2950
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
    print('⚠ 像素太少，可能描到碎段，中止')
    sys.exit(2)

# 按 x 排序得到走向（该线大体西东向），每 ~40px 取一点
pts = sorted(comp, key=lambda p: p[0])
step = max(len(pts) // 14, 1)
poly = [pts[i] for i in range(0, len(pts), step)]
if pts[-1] != poly[-1]:
    poly.append(pts[-1])

# 与花桥点位的距离
qx, qy = 4398, 2739
dmin = min(math.hypot(px - qx, py - qy) for px, py in comp) * 111.0 / 1162.0
print('该线距花桥点位最近 %.1f km' % dmin)

rec = {'id': 'M1', 'value': '130', 'closed': False,
       'source': '人工补描（digitize.py 面积过滤漏检），2026-10-09',
       'polyline_px': [[int(px), int(py)] for px, py in poly]}
out = os.path.join(r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache\manual_labels',
                   '24h-Pa_extra_lines.json')
lst = []
if os.path.isfile(out):
    lst = json.load(open(out, encoding='utf-8'))
lst = [r for r in lst if r['id'] != 'M1']
lst.append(rec)
json.dump(lst, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('折线 %d 点已写入 %s' % (len(poly), out))
print('折线:', rec['polyline_px'])
