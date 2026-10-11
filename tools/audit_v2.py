# -*- coding: utf-8 -*-
"""v2 线值自动复核：用人工圈注（277 个圈）作为局部真值，
对每条 v2 新线投票校正，输出 修正/已证实/冲突/无证据 四类清单。"""
import json, math, os, sys, io
from collections import defaultdict
sys.path.insert(0, r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\scripts')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from digitize import build_lines
from lookup import stat_xy   # noqa

cache = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache'
atlas = r'D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集'
V2 = os.path.join(cache, 'manual_labels_v2')
msroot = r'D:\DSH工作区\自动查找图集参数\查图_吊钟水库\marks7'
mvall = json.load(open(os.path.join(cache, 'marks_values.json'), encoding='utf-8'))
CELL = 24
R_VOTE = 60.0     # 圈中心到线采样点的投票半径（px）
SHEETS = ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv']

report = {}
for key in SHEETS:
    mv = mvall[key]
    _, W, H, lines = build_lines(os.path.join(atlas, mv['sheet']), merge_px=60)
    vp = os.path.join(V2, key + '_lines.json')
    vals = json.load(open(vp, encoding='utf-8'))
    # 圈注（位置+值）
    msrc = os.path.join(msroot, key)
    mk = os.path.join(msrc, 'marks2.json')
    mk = mk if os.path.isfile(mk) else os.path.join(msrc, 'marks.json')
    marks = json.load(open(mk, encoding='utf-8'))
    mvals = {int(k): v for k, v in mv['values'].items()}
    votes = defaultdict(list)      # 线 id -> [(mark值, 距离px)]
    used_marks = 0
    for i, m in enumerate(marks):
        v = mvals.get(i)
        if not v:
            continue
        mx, my = m['cx'], m['cy']
        cand = []
        for c in lines:
            d, bx, by = min(((math.hypot(sx - mx, sy - my), sx, sy) for sx, sy in c['samples']),
                            key=lambda t: t[0])
            if d <= R_VOTE:
                cand.append((d, c['id']))
        if not cand:
            continue
        cand.sort()
        # 只投给最近的线（标签只属于一根线）
        d0, lid0 = cand[0]
        # 若第二近的距离与第一接近且值不同 → 标签归属歧义
        amb = any(abs(d - d0) < 20 and c2 != lid0 for d, c2 in cand[1:4])
        votes[lid0].append((float(v), d0, i, amb))
        used_marks += 1
    # 逐线复核
    corrected, verified, conflicts, noevid = [], [], [], []
    newvals = dict(vals)
    for c in lines:
        lid = c['id']
        cur = vals.get(lid)
        vs = votes.get(lid, [])
        if not vs:
            if cur:
                noevid.append(lid)
            continue
        # 冲突检测：不同值且都有近距离支持
        byval = defaultdict(list)
        for v, d, i, amb in vs:
            byval[v].append((d, i, amb))
        if len(byval) > 1:
            # 取最近圈（标签大概率属于最近的线段）
            byval_sorted = sorted(byval.items(), key=lambda kv: min(x[0] for x in kv[1]))
            win = byval_sorted[0][0]
            conflicts.append((lid, cur, dict((k, len(x)) for k, x in byval.items()), win))
        else:
            win = list(byval.keys())[0]
        amb_any = any(v[3] for v in vs)
        if cur is None or float(cur) != float(win):
            corrected.append((lid, cur, win, amb_any))
            newvals[lid] = win
        else:
            verified.append((lid, win, amb_any))
    if os.environ.get('AUDIT_DRY') == '0':
        json.dump(newvals, open(os.path.join(V2, key + '_lines.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    report[key] = dict(marks_used=used_marks, corrected=corrected, verified_n=len(verified),
                       verified_ids=[v[0] for v in verified],
                       conflicts=conflicts, noevid=noevid)
    print('== %-7s 圈注投票 %d 个' % (key, used_marks))
    for lid, old, new, amb in corrected:
        print('   修正 %-4s: %s → %s%s' % (lid, old, new, '（归属有歧义，建议复核）' if amb else ''))
    for lid, old, cnt, win in conflicts:
        print('   冲突 %-4s: 当前%s, 圈注%s → 按最近圈取 %s（需人工复核）' % (lid, old, cnt, win))
    print('   已证实 %d 条 | 无局部标注 %d 条' % (len(verified), len(noevid)))

json.dump(report, open(os.path.join(V2, '_audit_report.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('审计报告已保存: _audit_report.json')
