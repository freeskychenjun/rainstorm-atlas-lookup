# -*- coding: utf-8 -*-
"""生成产流分区的区域编号图（洪水填充），建立 9 个参考点 → 分区号 → 区域ID 对照"""
import json, math, os, sys, io
from collections import deque
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ZJ = os.path.join(r'D:\DSH工作区\自动查找图集参数\数字化_产流分区', 'zones_产流.json')
OUT_MASK = os.path.join(os.path.dirname(ZJ), 'zone_region_map.npz')
OUT_MAP = os.path.join(os.path.dirname(ZJ), 'region_zone_map.json')

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
barrier = np.zeros((H, W), dtype=bool)
for s in d['segments']:
    for (px, py) in s['polyline_px']:
        xi, yi = int(round(px)), int(round(py))
        barrier[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2] = True
barrier[:3, :] = True; barrier[-3:, :] = True
barrier[:, :3] = True; barrier[:, -3:] = True

region = np.zeros((H, W), dtype=np.int32)
nid = 0
for sy in range(6, H, 20):
    for sx in range(6, W, 20):
        if barrier[sy, sx] or region[sy, sx]:
            continue
        nid += 1
        q = deque([(sx, sy)])
        region[sy, sx] = nid
        while q:
            x, y = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and not barrier[ny, nx] and not region[ny, nx]:
                    region[ny, nx] = nid
                    q.append((nx, ny))
np.savez_compressed(OUT_MASK, region=region)

# 参考点 → 区域ID
ref2zone = {}
for zone, (name, lo, la) in REF.items():
    x = int(435.0 * W / 5495 + (lo - 114) * 1162)
    y = int(345.0 * H / 7076 + (30 - la) * 1162)
    x = min(max(x, 0), W - 1); y = min(max(y, 0), H - 1)
    rid = int(region[y, x])
    ref2zone[zone] = {'name': name, 'x': x, 'y': y, 'region_id': rid}
    print('分区 %s (%s): 区域ID=%d' % (zone, name, rid))

ids = [r['region_id'] for r in ref2zone.values()]
if len(set(ids)) != len(ids):
    print('⚠ 有多个分区落在同一个区域，需检查边界提取')
json.dump({'ref2zone': ref2zone, 'n_regions_found': nid},
          open(OUT_MAP, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('OK, 区域图与对照表已保存')
