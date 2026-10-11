# -*- coding: utf-8 -*-
"""产流分区快速查询：基于数字化边界生成的区域标签图判区号（可被 auto_value import）。

用法:
  python zone_lookup.py --lon 115.51 --lat 28.99
输出: JSON（分区号 + 边界邻近提示）

判定规则:
  - 坐标超出图集覆盖范围直接报错（旧版静默钳位到标签图边缘，会给错区号）；
  - 点位标签映射不到 9 区之一 → 警告"未落入分区"（省界外/未覆盖）；
  - 距分区边界 < 2 km → 警告贴边界，区号易判错，须对图复核。
    （标签图里 1~19 是中间区域 id，须先经 region_zone_map.json 映射到最终
     Ⅰ~Ⅸ 区再比较，否则同一分区的内部接缝会被误当成分区边界。）
"""
import argparse, json, os, sys, io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == '__main__' and sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

from registry import zone_xy, out_of_bounds, zone_px_km

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CAND = [os.path.join(SKILL, 'cache'),
         r'D:\DSH工作区\自动查找图集参数\数字化_产流分区']
ZONE_NEAR_KM = 2.0          # 距分区边界小于该值提示人工复核

_loaded = None


def _load():
    """惰性加载标签图与映射表（进程内只加载一次）。"""
    global _loaded
    if _loaded is not None:
        return _loaded
    for d in _CAND:
        npz, mp = os.path.join(d, 'zone_region_map.npz'), os.path.join(d, 'region_zone_map.json')
        if os.path.isfile(npz) and os.path.isfile(mp):
            labels = np.load(npz)['labels']
            ref2zone = json.load(open(mp, encoding='utf-8'))['ref2zone']
            _loaded = (labels, {info['region_id']: zn for zn, info in ref2zone.items()})
            return _loaded
    _loaded = (None, None)
    return _loaded


def zone_query(lon, lat):
    """判产流分区号。返回 dict：zone / region_id / warning / error（有则）。"""
    err = out_of_bounds(lon, lat)
    if err:
        return {'zone': None, 'error': err}
    labels, id2zone = _load()
    if labels is None:
        return {'zone': None,
                'error': '分区标签图缺失（cache/zone_region_map.npz + region_zone_map.json）'}
    H, W = labels.shape
    fx, fy = zone_xy(lon, lat)
    x, y = int(round(fx)), int(round(fy))
    if not (0 <= x < W and 0 <= y < H):
        return {'zone': None,
                'error': '点位换算像素 (%d,%d) 落在分区标签图 (%d×%d) 之外，不钳位估读'
                         % (x, y, W, H)}
    rid = int(labels[y, x])
    zone = id2zone.get(rid)
    out = {'zone': zone, 'region_id': rid}
    if zone is None:
        out['warning'] = '点位标签 %d 未映射到 Ⅰ~Ⅸ 任何分区（可能贴近省界或未覆盖区），须人工对图判区' % rid
        return out

    # ---- 边界邻近检测：窗口内映射到最终区号，出现异区像素即贴边界 ----
    r = 24                                   # px ≈ 2.3 km（S9=1170 px/°）
    y0, y1 = max(y - r, 0), min(y + r + 1, H)
    x0, x1 = max(x - r, 0), min(x + r + 1, W)
    names = sorted(set(id2zone.values()))
    nidx = {n: i for i, n in enumerate(names)}
    lut = np.full(max(id2zone) + 1, -1, dtype=np.int32)
    for rid_, zn in id2zone.items():
        lut[rid_] = nidx[zn]
    win = labels[y0:y1, x0:x1]
    zidx = lut[np.clip(win, 0, lut.shape[0] - 1)]
    other = (zidx >= 0) & (zidx != nidx[zone])
    if other.any():
        wy, wx = np.nonzero(other)
        dpx = float(np.min(np.hypot(wx + x0 - x, wy + y0 - y)))
        dkm = dpx * zone_px_km()
        if dkm < ZONE_NEAR_KM:
            out['warning'] = ('距分区边界约 %.1f km（第%s区与第%s区交界），区号易判错，'
                              '请对图放大复核' % (dkm, zone, names[int(zidx[wy[0], wx[0]])]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--lat', type=float, required=True)
    a = ap.parse_args()
    r = zone_query(a.lon, a.lat)
    print(json.dumps(dict(lon=a.lon, lat=a.lat, **r), ensure_ascii=False))
    sys.exit(2 if r.get('error') else 0)


if __name__ == '__main__':
    main()
