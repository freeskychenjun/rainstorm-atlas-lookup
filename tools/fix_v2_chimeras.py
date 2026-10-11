# -*- coding: utf-8 -*-
"""v2 定向校正：把补描线（24h-Pa M1=130、3d-Pa M1=150/M2=180）的真值
写回与之重叠的 v2 新线号，修正“粘连线拆分后两片继承同一值”的错误。"""
import json, math, os, sys, io
sys.path.insert(0, r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\scripts')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from digitize import build_lines

cache = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache'
atlas = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
V2 = os.path.join(cache, 'manual_labels_v2')
mvall = json.load(open(os.path.join(cache, 'marks_values.json'), encoding='utf-8'))
CELL = 24

for key in ['24h-Pa', '3d-Pa']:
    ep = os.path.join(cache, 'manual_labels', key + '_extra_lines.json')
    if not os.path.isfile(ep):
        continue
    extras = json.load(open(ep, encoding='utf-8'))
    mv = mvall[key]
    _, W, H, lines = build_lines(os.path.join(atlas, mv['sheet']), merge_px=60)
    vp = os.path.join(V2, key + '_lines.json')
    vals = json.load(open(vp, encoding='utf-8'))
    print('== %s（现有 v2 线 %d 条，值 %d 条）' % (key, len(lines), len(vals)))
    for ex in extras:
        mp = ex['polyline_px']
        mcells = set()
        for x, y in mp:
            cx, cy = int(x) // CELL, int(y) // CELL
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    mcells.add((cx + dx, cy + dy))
        hits = []
        for c in lines:
            s = c['samples']
            if not s:
                continue
            # 反向度量：补描折线的点有多少落在该新线邻域内（折线是稀疏描迹）
            lcells = set()
            for x, y in s:
                lcells.add((int(x) // CELL, int(y) // CELL))
            f = sum(1 for x, y in mp if (int(x) // CELL, int(y) // CELL) in lcells) / len(mp)
            if f >= 0.5:
                hits.append((f, c['id']))
        hits.sort(reverse=True)
        top = hits[0] if hits else None
        print('   补描线 %s=%s（%d点）→ 命中 v2 线: %s'
              % (ex['id'], ex['value'], len(mp),
                 ', '.join('%s(%.0f%%)' % (i, f * 100) for f, i in hits[:4]) or '无'))
        for f, lid in hits:
            if f >= 0.6 and vals.get(lid) != ex['value']:
                print('      修正 %s: %s → %s' % (lid, vals.get(lid), ex['value']))
                vals[lid] = ex['value']
    json.dump(vals, open(vp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('   已保存修正后的 v2 值表')
