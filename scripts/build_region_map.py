# -*- coding: utf-8 -*-
"""区域图生成 v3：直接复用 digitize_zones 的封墙逻辑（cv2 14px 折线 + ring 省界环 + 自由端 tip_dir 射线补接 + 膨胀），
生成逐像素区域标签图，再用 9 个县城参考点给区域编号挂分区号。"""
import json, math, os, sys, io
import numpy as np
import cv2

sys.path.insert(0, r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\scripts')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import digitize_zones as dz

ZJ = os.path.join(r'D:\DSH工作区\自动查找图集参数\数字化_产流分区', 'zones_产流.json')
CACHE = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache'
JX = os.path.join(CACHE, 'jiangxi_360000.json')

REF = {'Ⅰ': ('安远县', 115.394, 25.137),
       'Ⅱ': ('崇义县', 114.308, 25.683),
       'Ⅲ': ('永新县', 113.950, 26.945),
       'Ⅳ': ('上高县', 114.917, 28.233),
       'Ⅴ': ('南城县', 116.533, 27.553),
       'Ⅵ': ('横峰县', 117.596, 28.407),
       'Ⅶ': ('婺源县', 117.861, 29.248),
       'Ⅷ': ('修水县', 114.568, 29.026),
       'Ⅸ': ('鄱阳县', 116.675, 28.994)}

d = json.load(open(ZJ, encoding='utf-8'))
W, H = d['image']['w'], d['image']['h']
segs = d['segments']

if not os.path.isfile(JX):
    print(json.dumps({'error': '缺少省界矢量 ' + JX + '；请从外部会话的 cache 复制过来'}, ensure_ascii=False))
    sys.exit(2)

roi, ring, poly = dz.province_roi(JX, W, H)

# 封墙：全部段折线（14px 粗线，闭合段闭合绘制）
wall = np.zeros((H, W), np.uint8)
for s in segs:
    pts = np.array(s['polyline_px'], np.int32).reshape(-1, 1, 2)
    cv2.polylines(wall, [pts], bool(s.get('closed')), 1, thickness=14)
wall[ring] = 1

# 自由端点射线补接（tip_dir 朝外方向，≤400px）
for s in segs:
    if s.get('closed'):
        continue
    ends = s.get('ends') or []
    for side in (0, 1):
        if side >= len(ends) or ends[side] is not None:
            continue
        pts = s['polyline_px']
        p = pts[0] if side == 0 else pts[-1]
        ux, uy = dz.tip_dir(pts, side == 0)
        for t in range(10, 400, 2):
            qx, qy = int(p[0] + ux * t), int(p[1] + uy * t)
            if not (0 <= qx < W and 0 <= qy < H):
                break
            if wall[qy, qx]:
                cv2.line(wall, (int(p[0]), int(p[1])), (qx, qy), 1, thickness=10)
                break

wall = cv2.dilate(wall, dz.ellipse(5))
n, lab, stats, cents = cv2.connectedComponentsWithStats((1 - wall).astype(np.uint8), connectivity=4)
hh, ww = wall.shape
valid = []
for i in range(1, n):
    area = stats[i, cv2.CC_STAT_AREA]
    touches = (stats[i, cv2.CC_STAT_LEFT] == 0 or stats[i, cv2.CC_STAT_TOP] == 0 or
               stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] >= ww or
               stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] >= hh)
    if not touches and area >= 100000:
        valid.append(i)
print('封闭区域数:', len(valid))

np.savez_compressed(os.path.join(os.path.dirname(ZJ), 'zone_region_map.npz'), labels=lab,
                    valid=np.array(valid))

ref2zone = {}
for zone, (name, lo, la) in REF.items():
    x = int(3160.0 + (lo - 115.88) * 1170)
    y = int(3390.0 + (28.68 - la) * 1170)
    x = min(max(x, 0), W - 1); y = min(max(y, 0), H - 1)
    rid = int(lab[y, x])
    ref2zone[zone] = {'name': name, 'xy': [x, y], 'region_id': rid}
    in_valid = rid in valid
    print('%s(%s): region_id=%d %s' % (zone, name, rid, '✓' if in_valid else '⚠ 无效区域'))

used = sorted(set(r['region_id'] for r in ref2zone.values()))
print('参考点覆盖区域数:', len(used))
json.dump({'ref2zone': ref2zone}, open(os.path.join(os.path.dirname(ZJ), 'region_zone_map.json'),
           'w', encoding='utf-8'), ensure_ascii=False, indent=1)
