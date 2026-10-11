# -*- coding: utf-8 -*-
"""回归校验：走 auto_value.py 真实代码路径复验三个已知点位（吊钟水库/四方井/花桥）。

对比基线：..\\baseline_verify_v2.txt（2026-10 各向异性距离修正前的旧算法输出；
内插值差异应在 ±2mm(Pa)/±0.02(Cv) 口径内，距离/方位角数值按新换算略变属预期）。
用法: python tools/verify_v2.py
"""
import json, os, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..', 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from auto_value import query_point

POINTS = [('吊钟水库', 115.510481961, 28.989354397),
          ('四方井',   114.25104525, 27.68249619),
          ('花桥',     117.409335637, 27.944499731)]

if __name__ == '__main__':
    for name, lon, lat in POINTS:
        r = query_point(name, lon, lat)
        print('=' * 62)
        print('点位：%s (%.4f, %.4f)  分区：%s%s' % (
            name, lon, lat, r.get('zone'),
            '  [warning: %s]' % r['zone_warning'] if r.get('zone_warning') else ''))
        for key, ent in r['values'].items():
            near, opp = ent['nearest'], ent.get('opposite')
            if opp:
                print('  %-7s %s=%g(%.1fkm,%d°) ↔ %s=%g(%.1fkm,%d°) → %.2f%s' % (
                    key, near['id'], near['value'], near['km'], near['azimuth'],
                    opp['id'], opp['value'], opp['km'], opp['azimuth'],
                    ent['interpolated'], '  ⚠' if ent.get('warning') else ''))
            else:
                print('  %-7s %s=%g(%.1fkm,%d°)（无对侧线）' % (
                    key, near['id'], near['value'], near['km'], near['azimuth']))
        for key, ent in r['values'].items():
            if ent.get('warning'):
                print('  [%s] %s' % (key, ent['warning']))
