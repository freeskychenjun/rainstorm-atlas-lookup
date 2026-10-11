# -*- coding: utf-8 -*-
"""入库用户确认的 v2 线值指认表：比对→应用→统计"""
import json, re, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
MD = r'D:\DSH工作区\自动查找图集参数\数字化_v2_指认\指认表.md'
V2 = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache\manual_labels_v2'

sec = None
table = {}   # sheet -> {lineid: 确认值}
order = {}
for line in open(MD, encoding='utf-8'):
    m = re.match(r'## (\S+?)（', line)
    if m:
        sec = m.group(1)
        table.setdefault(sec, {})
        order[sec] = []
    m2 = re.match(r'\|\s*(L\d+)\s*\|\s*([\d.]+)\s*\|', line)
    if m2 and sec:
        lid, cur = m2.group(1), m2.group(2)
        parts = [p.strip() for p in line.strip().strip('|').split('|')]
        conf = parts[-1] if len(parts) >= 6 else ''
        table[sec][lid] = conf
        order[sec].append(lid)

total = agree = changed = empty = 0
changes = []
for key, rows in table.items():
    p = os.path.join(V2, key + '_lines.json')
    d = json.load(open(p, encoding='utf-8'))
    for lid, conf in rows.items():
        total += 1
        if not conf:
            empty += 1
            continue
        try:
            cv = '%g' % float(conf)
        except Exception:
            cv = conf
        cur = d.get(lid)
        curs = ('%g' % float(cur)) if cur is not None else None
        if curs == cv:
            agree += 1
        else:
            changed += 1
            d[lid] = conf
            changes.append((key, lid, cur, conf))
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('指认总条数 %d | 一致 %d | 更正 %d | 未填 %d' % (total, agree, changed, empty))
print('更正明细：')
for k, lid, old, new in changes:
    print('   %-7s %-4s %s → %s' % (k, lid, old, new))
# 未填清单
unf = [(k, lid) for k, rows in table.items() for lid in order[k] if not rows.get(lid)]
if unf:
    print('未填：', ', '.join('%s.%s' % (k, lid) for k, lid in unf))
