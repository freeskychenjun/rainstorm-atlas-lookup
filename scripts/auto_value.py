# -*- coding: utf-8 -*-
"""一键查值：经纬度 → 8 个暴雨参数 + 产流分区（基于全量人工确认的数字化等值线线值库）。

用法:
  python auto_value.py --lon 115.51 --lat 28.99 [--out values.json]
依赖:
  cache/manual_labels_v2/<图幅>_lines.json   人工确认线值（349 条）
  cache/manual_labels/<图幅>_extra_lines.json 人工补描线（可选）
  cache/zone_region_map.npz + region_zone_map.json  分区自动判定
  atlas/ 或 DEFAULT_ATLAS                    图集原图（仅用于配准常数）
说明:
  内插=最近两条不同值等值线按距离加权；结果为机器初值，重要工程建议按
  SKILL.md「读图纪律」人工复核夹持方向（同侧双线时程序无法判内外侧）。
"""
import argparse, json, math, os, sys, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from digitize import build_lines
from lookup import stat_xy

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(SKILL, 'cache')
ATLAS = os.path.join(SKILL, 'atlas')
if not os.path.isdir(ATLAS):
    ATLAS = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
SHEETS = ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv']
DUR = {'1h': '1h', '6h': '6h', '24h': '24h', '3d': '3d'}

ap = argparse.ArgumentParser()
ap.add_argument('--lon', type=float, required=True)
ap.add_argument('--lat', type=float, required=True)
ap.add_argument('--out', default='')
a = ap.parse_args()

# ---------- 分区 ----------
zone = None
zm = os.path.join(CACHE, 'zone_region_map.npz')
mj = os.path.join(CACHE, 'region_zone_map.json')
if os.path.isfile(zm) and os.path.isfile(mj):
    import numpy as np
    lab = np.load(zm)['labels']
    H, W = lab.shape
    x = int(3160.0 + (a.lon - 115.88) * 1170)
    y = int(3390.0 + (28.68 - a.lat) * 1170)
    rid = int(lab[min(max(y, 0), H - 1), min(max(x, 0), W - 1)])
    for zn, info in json.load(open(mj, encoding='utf-8'))['ref2zone'].items():
        if info['region_id'] == rid:
            zone = zn
            break

# ---------- 各幅等值线 ----------
out = {'lon': a.lon, 'lat': a.lat, 'zone': zone, 'values': {}}
for key in SHEETS:
    vp = os.path.join(CACHE, 'manual_labels_v2', key + '_lines.json')
    if not os.path.isfile(vp):
        continue
    sheet = json.load(open(os.path.join(os.path.dirname(vp), '..', 'digit_v2_sheet.json'), encoding='utf-8')).get(key) if False else None
    import glob
    from PIL import Image
    # 图幅文件名由 SKILL 约定
    FN = {'1h-Pa': '1--1h-Pa.jpg', '1h-Cv': '2--1h-Cv.jpg', '6h-Pa': '3--6h-Pa.jpg', '6h-Cv': '4--6h-Cv.jpg',
          '24h-Pa': '5--24h-Pa.jpg', '24h-Cv': '6--24h-Cv.jpg', '3d-Pa': '7--3d-Pa.jpg', '3d-Cv': '8--3d-Cv.jpg'}[key]
    im = Image.open(os.path.join(ATLAS, FN))
    W, H = im.size
    vals = json.load(open(vp, encoding='utf-8'))
    lines = []
    for lid, v in vals.items():
        lines.append({'id': lid, 'value': v, 'samples': []})   # 占位，稍后用重数字化太慢
    # 直接重建线采样（merge60 与线值库同源）
    _, _, _, ls = build_lines(os.path.join(ATLAS, FN), merge_px=60)
    byid = {c['id']: c for c in ls}
    usable = []
    for i in vals:
        c = byid.get(i)
        if c is not None:
            c['value'] = vals[i]
            usable.append(c)
    for r in json.load(open(os.path.join(CACHE, 'manual_labels', key + '_extra_lines.json'),
                            encoding='utf-8')) if os.path.isfile(os.path.join(CACHE, 'manual_labels', key + '_extra_lines.json')) else []:
        usable.append({'id': r['id'], 'value': r['value'], 'closed': r.get('closed', False),
                       'samples': [tuple(p) for p in r['polyline_px']]})
    x, y = stat_xy(a.lon, a.lat, W, H)
    KM = 111.0 / 1162.0
    rows = []
    for c in usable:
        if not c.get('value'):
            continue
        d, bx, by = min(((math.hypot(sx - x, sy - y), sx, sy) for sx, sy in c['samples']), key=lambda t: t[0])
        ang = (math.degrees(math.atan2(bx - x, y - by)) + 360) % 360   # 地理方位角：正北 0°，顺时针
        rows.append((d * KM, float(c['value']), ang, c['id'], bool(c.get('closed'))))
    rows.sort()
    if not rows:
        continue
    v0 = rows[0][1]
    az0 = rows[0][2]

    def _adiff(a, b):
        d = abs(a - b) % 360
        return min(d, 360 - d)

    cands = [r for r in rows[1:] if r[1] != v0]      # 按距离排序的候选夹持线
    # 夹持对必须分列点位两侧：优先取反方向（方位差 >90°）的最近不同值线
    other = next((r for r in cands if _adiff(r[2], az0) > 90), None)
    warn = ''
    if other is None:
        other = cands[0] if cands else None
        if other is not None:
            warn = ('无对侧等值线（各线均在方位 %d° 同侧 %.1f km 内），'
                    '夹持区间仅单侧，内插不可靠，必须人工复核' % (round(az0), other[0]))
    elif cands and _adiff(cands[0][2], az0) < 60:
        warn = ('最近两条等值线同侧（方位差 %d°：%s %.1f km / %s %.1f km），'
                '已改取反方向对侧线 %s %.1f km 夹持；请人工复核点位内外侧'
                % (round(_adiff(cands[0][2], az0)), cands[0][3], cands[0][0],
                   rows[0][3], rows[0][0], other[3], other[0]))
    ent = {'nearest': {'id': rows[0][3], 'value': v0, 'km': rows[0][0], 'azimuth': round(az0)}}
    if other:
        d0, d1 = rows[0][0], other[0]
        vi = round(v0 + (other[1] - v0) * (d0 / (d0 + d1)), 2)
        ent['opposite'] = {'id': other[3], 'value': other[1], 'km': other[0], 'azimuth': round(other[2])}
        ent['interpolated'] = vi
        # 夹持线过远：内插不可靠，需提示（线稀疏区）
        if d0 > 30:
            far = '夹持线较远（最近 %.1f km / 对侧 %.1f km），位于等值线稀疏区，内插不确定度大，建议人工复核' % (d0, d1)
            warn = (warn + '；' if warn else '') + far
        elif d1 > 80:
            far = ('对侧夹持线极远（%.1f km，最近线仅 %.1f km），内插值几乎由最近线决定、'
                   '不确定度大，建议以最近线值为准并人工复核' % (d1, d0))
            warn = (warn + '；' if warn else '') + far
    if warn:
        ent['warning'] = warn
    out['values'][key] = ent

if a.out:
    json.dump(out, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
