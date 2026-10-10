# -*- coding: utf-8 -*-
"""用 merge_px=60 新线集 + 继承值 复验三个已知点位"""
import json, math, os, sys, io
sys.path.insert(0, r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\scripts')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from digitize import build_lines
from lookup import stat_xy

cache = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache'
atlas = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
V2 = os.path.join(cache, 'manual_labels_v2')
mvall = json.load(open(os.path.join(cache, 'marks_values.json'), encoding='utf-8'))
KM = 111.0 / 1162.0

POINTS = [('吊钟水库', 115.510481961, 28.989354397),
          ('四方井',   114.25104525, 27.68249619),
          ('花桥',     117.409335637, 27.944499731)]
SHEETS = ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv']

# 逐幅建立新线集（只建一次）
lineset = {}
for key in SHEETS:
    mv = mvall[key]
    _, W, H, lines = build_lines(os.path.join(atlas, mv['sheet']), merge_px=60)
    vals = json.load(open(os.path.join(V2, key + '_lines.json'), encoding='utf-8'))
    for c in lines:
        c['value'] = vals.get(c['id'])
    lineset[key] = (W, H, [c for c in lines if c['value']])

for name, lon, lat in POINTS:
    print('=' * 62)
    print('点位：%s (%.4f, %.4f)' % (name, lon, lat))
    for key in SHEETS:
        W, H, lines = lineset[key]
        x, y = stat_xy(lon, lat, W, H)
        rows = []
        for c in lines:
            d, bx, by = min(((math.hypot(sx - x, sy - y), sx, sy) for sx, sy in c['samples']),
                            key=lambda t: t[0])
            ang = (math.degrees(math.atan2(bx - x, y - by)) + 360) % 360   # 地理方位角：正北 0°，顺时针
            rows.append((d * KM, float(c['value']), ang, c['id']))
        rows.sort()
        v0 = rows[0][1]
        other = next((r for r in rows[1:] if r[1] != v0), None)
        if other:
            d0, d1 = rows[0][0], other[0]
            vi = round(v0 + (other[1] - v0) * (d0 / (d0 + d1)), 2)
            print('  %-7s %s=%.2f(%.1fkm) ↔ %s=%.2f(%.1fkm) → %.2f'
                  % (key, rows[0][3], v0, d0, other[3], other[1], d1, vi))
        else:
            print('  %-7s %s=%.2f(%.1fkm)（无对侧线）' % (key, rows[0][3], v0, rows[0][0]))
