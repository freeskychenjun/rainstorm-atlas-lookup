# -*- coding: utf-8 -*-
"""部署版 skill 最终校验（改完源码跑 deploy.ps1 之后运行本脚本）。

校验项：
  1. SKILL.md + scripts/*.py  dev/部署逐字节一致（deploy.ps1 已自校验，这里复核）
  2. 部署 scripts/ 与源码集合一致（一次性工具已移 tools/ 不部署，不得残留）
  3. 图集 11 幅 jpg 在位
  4. 8 幅 v2 线值表 dev/部署逐字节一致
  5. 几何缓存 8 幅 npz 在位且与部署图集 MD5 指纹自洽（防换图后旧几何查值）
  6. 历史定位抽查（线值表关键条目，含人工合并线 M1）
"""
import hashlib, json, os, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
dev = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dep = os.path.join(os.path.expanduser('~'), '.agents', 'skills', 'rainstorm-atlas-lookup')
ok = True


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def check(good, msg):
    global ok
    if not good:
        ok = False
    print('%s %s' % ('✓' if good else '✗', msg))


# 1) 源码一致性
import glob
rels = ['SKILL.md'] + [os.path.relpath(p, dev) for p in
                       sorted(glob.glob(os.path.join(dev, 'scripts', '*.py')))]
bad = [r for r in rels
       if not os.path.isfile(os.path.join(dep, r))
       or md5(os.path.join(dev, r)) != md5(os.path.join(dep, r))]
check(not bad, 'SKILL.md + scripts/*.py dev/部署一致（%d 个文件）%s' % (len(rels), bad))

# 2) 部署 scripts 无残留
extra = [os.path.basename(p) for p in
         glob.glob(os.path.join(dep, 'scripts', '*.py'))
         if not os.path.isfile(os.path.join(dev, 'scripts', os.path.basename(p)))]
check(not extra, '部署 scripts/ 无已淘汰脚本残留' + ('：%s' % extra if extra else ''))

# 3) 图集
n = len([f for f in os.listdir(os.path.join(dep, 'atlas')) if f.endswith('.jpg')])
check(n == 11, 'atlas: %d 幅 jpg（应为 11）' % n)

# 4) v2 线值表逐字节一致
KEYS = ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv']
same = all(md5(os.path.join(dev, 'cache', 'manual_labels_v2', k + '_lines.json')) ==
           md5(os.path.join(dep, 'cache', 'manual_labels_v2', k + '_lines.json'))
           for k in KEYS)
check(same, '8 幅 v2 线值表 dev/部署逐字节一致')

# 5) 几何缓存与部署图集指纹自洽
import numpy as np
STAT_FILE = {'1h-Pa': '1--1h-Pa.jpg', '1h-Cv': '2--1h-Cv.jpg', '6h-Pa': '3--6h-Pa.jpg',
             '6h-Cv': '4--6h-Cv.jpg', '24h-Pa': '5--24h-Pa.jpg', '24h-Cv': '6--24h-Cv.jpg',
             '3d-Pa': '7--3d-Pa.jpg', '3d-Cv': '8--3d-Cv.jpg'}
gok, gerr = True, []
for k in KEYS:
    gp = os.path.join(dep, 'cache', 'geometry', k + '.npz')
    if not os.path.isfile(gp):
        gok, gerr = False, gerr + ['%s 缺失' % k]
        continue
    meta = json.loads(str(np.load(gp, allow_pickle=False)['meta'][0]))
    am = md5(os.path.join(dep, 'atlas', meta['file']))
    if am != meta.get('atlas_md5'):
        gok, gerr = False, gerr + ['%s 指纹不符' % k]
check(gok, '几何缓存 8 幅在位且与部署图集 MD5 自洽' + ('：%s' % gerr if gerr else ''))

# 6) 历史定位抽查（期望值为 2026-10 v2 定稿值；v2 重编号后旧抽查表曾过期误报——
#    以人工确认的当前值为准，M1 人工补描线在 manual_labels/ 而非 v2 表）
spot = [('3d-Pa_lines.json', 'L20', '160'), ('1h-Pa_lines.json', 'L15', '40'),
        ('6h-Pa_lines.json', 'L11', '75'), ('6h-Pa_lines.json', 'L4', '75')]
for f, lid, exp in spot:
    dv = json.load(open(os.path.join(dev, 'cache', 'manual_labels_v2', f), encoding='utf-8')).get(lid)
    dd = json.load(open(os.path.join(dep, 'cache', 'manual_labels_v2', f), encoding='utf-8')).get(lid)
    check(str(dd) == exp, '抽查 %s %s=%s (dev=%s)' % (f, lid, dd, dv))
ex = json.load(open(os.path.join(dep, 'cache', 'manual_labels', '24h-Pa_extra_lines.json'), encoding='utf-8'))
m1 = next((r['value'] for r in ex if r['id'] == 'M1'), None)
check(str(m1) == '130', '抽查 24h-Pa 补描线 M1=%s（应为 130）' % m1)

print('部署校验：%s' % ('全部通过' if ok else '有失败项'))
sys.exit(0 if ok else 1)
