# -*- coding: utf-8 -*-
"""产流分区快速查询：基于数字化边界生成的区域标签图。
用法: python zone_lookup.py --lon 115.51 --lat 28.99
输出: JSON（含分区号）
"""
import json, os, sys, io
import numpy as np
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ZJ_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache')
if not os.path.isfile(os.path.join(ZJ_DIR, 'zone_region_map.npz')):
    ZJ_DIR = r'D:\DSH工作区\自动查找图集参数\数字化_产流分区'
LAB = os.path.join(ZJ_DIR, 'zone_region_map.npz')
MP = os.path.join(ZJ_DIR, 'region_zone_map.json')
CX, CY, S9 = 3160.0, 3390.0, 1170.0
A_LON, A_LAT = 115.88, 28.68

ap = argparse.ArgumentParser()
ap.add_argument('--lon', type=float, required=True)
ap.add_argument('--lat', type=float, required=True)
a = ap.parse_args()

z = np.load(LAB)
lab = z['labels']
H, W = lab.shape
x = int(CX + (a.lon - 115.88) * S9)
y = int(CY + (28.68 - a.lat) * S9)
x = min(max(x, 0), W - 1); y = min(max(y, 0), H - 1)
rid = int(lab[y, x])
m = json.load(open(MP, encoding='utf-8'))['ref2zone']
zone = None
for zn, info in m.items():
    if info['region_id'] == rid:
        zone = zn
        break
print(json.dumps({'lon': a.lon, 'lat': a.lat, 'region_id': rid,
                  'zone': zone if zone else '（未识别）'}, ensure_ascii=False))
