# -*- coding: utf-8 -*-
"""一键查值：经纬度/KML → 8 个暴雨参数 + 产流分区（几何缓存 + 人工确认线值库，秒级）。

用法:
  python auto_value.py --lon 115.51 --lat 28.99 [--name 某水库] [--out values.json]
  python auto_value.py --kml C:\\points.kml [--out values.json]        # 多点位
输出 JSON:
  单点位: {name, lon, lat, zone, zone_warning?, values: {1h-Pa: {...}}, has_warning}
  多点位: {points: {点名: 同上}, has_warning}
  每幅 values 项: nearest/opposite 的线号·值·实测距离km·地理方位角 + 距离加权内插值，
  带 warning 字段的项须按 SKILL.md「读图纪律」人工复核。
依赖:
  cache/geometry/<图幅>.npz                 线几何缓存（tools/build_geometry.py 生成，含图集 MD5 指纹自校验）
  cache/manual_labels_v2/<图幅>_lines.json  人工确认线值（349 条）
  cache/manual_labels/<图幅>_extra_lines.json 人工补描线（可选）
  cache/zone_region_map.npz + region_zone_map.json  分区自动判定
说明:
  内插=最近两条不同值等值线按距离加权，夹持对须分列点位两侧（方位差>90°）；
  距离/方位角按纬度余弦各向异性换算（1°纬距111km、1°经距111·cosφ km），
  修正了旧版东西向距离高估 11~13% 的系统偏差。
"""
import argparse, hashlib, json, math, os, sys, io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from registry import SKILL_ROOT, STAT_KEYS, STAT_FILE, resolve_atlas, stat_xy, km_scales, out_of_bounds
from zone_lookup import zone_query

CACHE = os.path.join(SKILL_ROOT, 'cache')
GEOM = os.path.join(CACHE, 'geometry')

_geom_cache = {}
_md5_cache = {}


def _md5(path):
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _md5_cache:
        h = hashlib.md5()
        with open(path, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        _md5_cache[key] = h.hexdigest()
    return _md5_cache[key]


def _die(msg):
    print(json.dumps({'error': msg}, ensure_ascii=False))
    sys.exit(2)


def load_geometry(key):
    """加载线几何缓存并核对图集指纹（不一致说明换过图，须重建几何）。"""
    if key in _geom_cache:
        return _geom_cache[key]
    p = os.path.join(GEOM, key + '.npz')
    if not os.path.isfile(p):
        _die('几何缓存缺失: %s —— 请在开发目录运行 tools/build_geometry.py 生成后 '
             '运行 deploy.ps1 同步（旧版每次查询重数字化 8 幅大图需 103 秒，已弃用）' % p)
    z = np.load(p, allow_pickle=False)
    meta = json.loads(str(z['meta'][0]))
    src = os.path.join(resolve_atlas(), meta.get('file', STAT_FILE[key]))
    if os.path.isfile(src) and _md5(src) != meta.get('atlas_md5'):
        _die('图集文件 %s 与几何缓存指纹不一致（图集被更换/重扫过）——'
             '请重跑 tools/build_geometry.py 并 deploy' % src)
    _geom_cache[key] = (meta, list(map(str, z['ids'])), z['offsets'], z['flat'], z['closed'])
    return _geom_cache[key]


def _adiff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def query_sheet(key, lon, lat):
    """单幅查值：几何缓存 + 线值库 → 最近线/对侧线/内插值（含 warning 判定）。"""
    vp = os.path.join(CACHE, 'manual_labels_v2', key + '_lines.json')
    if not os.path.isfile(vp):
        return None
    vals = json.load(open(vp, encoding='utf-8'))
    meta, ids, offsets, flat, closed = load_geometry(key)
    x, y = stat_xy(lon, lat, meta['W'], meta['H'])
    kx, ky = km_scales(lat)

    # 主线集（挂上人工确认值的）+ 人工补描线，统一拼成一份采样点数组
    segs = []                                   # (id, value, closed, i0, i1)
    pts = [flat]
    for i, lid in enumerate(ids):
        v = vals.get(lid)
        if v:
            segs.append((lid, float(v), bool(closed[i]), int(offsets[i]), int(offsets[i + 1])))
    ep = os.path.join(CACHE, 'manual_labels', key + '_extra_lines.json')
    extra_base = len(flat)
    if os.path.isfile(ep):
        for r in json.load(open(ep, encoding='utf-8')):
            arr = np.asarray(r['polyline_px'], dtype=np.int32)
            segs.append((r['id'], float(r['value']), bool(r.get('closed')),
                         extra_base, extra_base + len(arr)))
            extra_base += len(arr)
            pts.append(arr)
    if not segs:
        return None
    allpts = np.concatenate(pts)

    dxk = (allpts[:, 0] - x) * kx               # 东向 km
    dyk = (y - allpts[:, 1]) * ky               # 北向 km（像面向下为南）
    d2 = dxk * dxk + dyk * dyk
    rows = []
    for lid, v, clo, i0, i1 in segs:
        j = i0 + int(np.argmin(d2[i0:i1]))
        rows.append((math.sqrt(d2[j]), v,
                     (math.degrees(math.atan2(dxk[j], dyk[j])) + 360) % 360,   # 地理方位角：正北0°顺时针
                     lid, clo))
    rows.sort()

    v0, az0 = rows[0][1], rows[0][2]
    cands = [r for r in rows[1:] if r[1] != v0]
    # 夹持对必须分列点位两侧：优先取反方向（方位差>90°）的最近不同值线
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
    ent = {'nearest': {'id': rows[0][3], 'value': v0, 'km': round(rows[0][0], 3), 'azimuth': round(az0)}}
    if other:
        d0, d1 = rows[0][0], other[0]
        vi = round(v0 + (other[1] - v0) * (d0 / (d0 + d1)), 2)
        ent['opposite'] = {'id': other[3], 'value': other[1], 'km': round(other[0], 3), 'azimuth': round(other[2])}
        ent['interpolated'] = vi
        if d0 > 30:
            far = '夹持线较远（最近 %.1f km / 对侧 %.1f km），位于等值线稀疏区，内插不确定度大，建议人工复核' % (d0, d1)
            warn = (warn + '；' if warn else '') + far
        elif d1 > 80:
            far = ('对侧夹持线极远（%.1f km，最近线仅 %.1f km），内插值几乎由最近线决定、'
                   '不确定度大，建议以最近线值为准并人工复核' % (d1, d0))
            warn = (warn + '；' if warn else '') + far
    if warn:
        ent['warning'] = warn
    return ent


def query_point(name, lon, lat):
    """单点全量查值：8 幅等值线 + 产流分区。"""
    err = out_of_bounds(lon, lat)
    if err:
        return {'name': name, 'lon': lon, 'lat': lat, 'error': err}
    zq = zone_query(lon, lat)
    values = {}
    for key in STAT_KEYS:
        ent = query_sheet(key, lon, lat)
        if ent is not None:
            values[key] = ent
    ent = {'name': name, 'lon': lon, 'lat': lat, 'zone': zq.get('zone'),
           'values': values}
    for k in ('warning', 'error'):
        if zq.get(k):
            ent['zone_' + k] = zq[k]
    ent['has_warning'] = (any('warning' in v for v in values.values())
                          or bool(zq.get('warning')) or bool(zq.get('error')))
    return ent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lon', type=float)
    ap.add_argument('--lat', type=float)
    ap.add_argument('--name', default='', help='点名（单点模式可选）')
    ap.add_argument('--kml', default='', help='KML 文件（Point/Polygon 型 Placemark，多点位）')
    ap.add_argument('--out', default='', help='结果 JSON 输出文件（可选）')
    a = ap.parse_args()

    if a.kml:
        if not os.path.isfile(a.kml):
            _die('KML 文件不存在: ' + a.kml)
        from lookup import parse_kml
        pts = parse_kml(a.kml)
        if not pts:
            _die('KML 中未找到有效点位（支持 Point 与 Polygon 外环质心）')
    else:
        if a.lon is None or a.lat is None:
            _die('需提供 --lon/--lat 或 --kml')
        pts = [(a.name or '未命名', a.lon, a.lat, 'point')]

    results = [query_point(n, lo, la) for n, lo, la, _src in pts]
    bad = [r for r in results if 'error' in r]
    if len(results) == 1:
        out = results[0]
    else:
        byname, seen = {}, {}
        for r in results:                      # 同名点位去重命名，避免字典键冲突
            base, k = r['name'], seen.get(r['name'], 0) + 1
            seen[r['name']] = k
            byname[base if k == 1 else '%s#%d' % (base, k)] = r
        out = {'points': byname}
    out['has_warning'] = any(r.get('has_warning') for r in results)
    if bad and a.kml:
        out['note'] = '有 %d 个点位未完成查值（见各点 error 字段）' % len(bad)

    if a.out:
        json.dump(out, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(2 if (not a.kml and bad) else 0)


if __name__ == '__main__':
    main()
