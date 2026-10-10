# -*- coding: utf-8 -*-
"""8 幅图 merge_px=60 重数字化 + 按几何重叠自动继承现有线值。

判定规则（网格占用法，CELL=24px，双方各膨胀1格）：
  forward  = 新线采样点落在旧线邻域内的比例
  backward = 旧线采样点落在新线邻域内的比例
  forward≥0.7 且 backward≥0.7 → 1:1 对应，直接继承旧值
  forward≥0.7 但 backward<0.7 → 新线只是旧线的一部分（拆分/粘连残留）→ 继承但标记待确认
  forward<0.7                    → 新线无对应旧线 → 无值（新出现/新拆分出的线）
产物：cache/manual_labels_v2/<key>_lines.json （新线号→值） + _meta（继承/标记/无值统计）
"""
import json, math, os, sys, io
sys.path.insert(0, r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\scripts')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from digitize import build_lines, attach_values, MARKED_DIR

cache = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache'
atlas = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
OUT = os.path.join(cache, 'manual_labels_v2')
os.makedirs(OUT, exist_ok=True)
CELL = 24


def cells(samples, dilate=1):
    s = set()
    for x, y in samples:
        cx, cy = int(x) // CELL, int(y) // CELL
        for dx in range(-dilate, dilate + 1):
            for dy in range(-dilate, dilate + 1):
                s.add((cx + dx, cy + dy))
    return s


def overlap(new_s, old_cells):
    if not new_s:
        return 0.0
    hit = sum(1 for x, y in new_s if (int(x) // CELL, int(y) // CELL) in old_cells)
    return hit / len(new_s)


mvall = json.load(open(os.path.join(cache, 'marks_values.json'), encoding='utf-8'))
summary = {}
for key in ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv']:
    mv = mvall[key]
    path = os.path.join(atlas, mv['sheet'])
    # ---- 旧线（merge 150）+ 现有值 ----
    _, W, H, old = build_lines(path, merge_px=150)
    msrc = os.path.join(MARKED_DIR, key)
    mk = os.path.join(msrc, 'marks2.json')
    mk = mk if os.path.isfile(mk) else os.path.join(msrc, 'marks.json')
    if os.path.isfile(mk):
        marks = {i: m for i, m in enumerate(json.load(open(mk, encoding='utf-8')))}
        old = attach_values(old, marks, {str(k): v for k, v in mv['values'].items()})
    lp = os.path.join(cache, 'manual_labels', key + '_lines.json')
    if os.path.isfile(lp):
        ov = json.load(open(lp, encoding='utf-8'))
        for c in old:
            if c['id'] in ov and isinstance(ov[c['id']], str):
                c['value'] = ov[c['id']]
    ep = os.path.join(cache, 'manual_labels', key + '_extra_lines.json')
    if os.path.isfile(ep):
        for r in json.load(open(ep, encoding='utf-8')):
            old.append({'id': r['id'], 'value': r['value'], 'closed': r.get('closed', False),
                        'samples': [tuple(p) for p in r['polyline_px']]})
    old_val = [c for c in old if c.get('value')]
    old_cells = {c['id']: cells(c['samples']) for c in old_val}
    # ---- 新线（merge 60）----
    _, _, _, new = build_lines(path, merge_px=60)
    res, flagged, inherited, none = {}, {}, 0, 0
    for c in new:
        ns = c['samples']
        best, bf, bb = None, 0.0, 0.0
        for o in old_val:
            f = overlap(ns, old_cells[o['id']])
            if f > bf:
                b = overlap(o['samples'], cells(ns))
                best, bf, bb = o, f, b
        if best is not None and bf >= 0.7:
            res[c['id']] = best['value']
            if bb < 0.7:
                flagged[c['id']] = {'value': best['value'], 'from': best['id'],
                                    'forward': round(bf, 2), 'backward': round(bb, 2),
                                    'why': '新线仅为旧线一部分（拆分/残留），值待确认'}
            else:
                inherited += 1
        else:
            none += 1
    json.dump(res, open(os.path.join(OUT, key + '_lines.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    meta = {'sheet': mv['sheet'], 'old_lines': len(old), 'old_valued': len(old_val),
            'new_lines': len(new), 'inherited_1to1': inherited,
            'flagged_partial': flagged, 'new_unvalued': none,
            'value_dict': res}
    json.dump(meta, open(os.path.join(OUT, key + '_meta.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    summary[key] = (len(old), len(old_val), len(new), inherited, len(flagged), none)
    print('%-7s 旧线%2d(有值%2d) → 新线%2d | 1:1继承%2d 部分继承(待确认)%2d 无值%2d'
          % (key, len(old), len(old_val), len(new), inherited, len(flagged), none))
print()
print('拆分待确认明细：')
for key, meta in [(k, json.load(open(os.path.join(OUT, k + '_meta.json'), encoding='utf-8')))
                  for k in ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv']]:
    fl = meta['flagged_partial']
    if fl:
        print('  %s: %s' % (key, ', '.join('%s←%s(%s=%s)' % (nid, v['from'], v['from'], v['value'])
                                           for nid, v in list(fl.items())[:8])))
