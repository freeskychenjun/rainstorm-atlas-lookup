# -*- coding: utf-8 -*-
"""部署版 skill 最终校验"""
import json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
dep = r'C:\Users\Administrator\.agents\skills\rainstorm-atlas-lookup'
dev = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup'
ok = True

checks = [('3d-Pa_lines.json', 'L20', '180'), ('1h-Pa_lines.json', 'L15', '40'),
          ('6h-Pa_lines.json', 'L11', '75'), ('24h-Pa_lines.json', 'M1', '130'),
          ('6h-Pa_lines.json', 'L4', '80')]
for f, lid, exp in checks:
    dv = json.load(open(os.path.join(dev, 'cache', 'manual_labels_v2', f), encoding='utf-8')).get(lid)
    dd = json.load(open(os.path.join(dep, 'cache', 'manual_labels_v2', f), encoding='utf-8')).get(lid)
    good = (str(dd) == exp)
    if not good:
        ok = False
    print('%s %s %s=%s (dev=%s)' % ('✓' if good else '✗', f, lid, dd, dv))

n = len([f for f in os.listdir(os.path.join(dep, 'atlas')) if f.endswith('.jpg')])
print('%s atlas: %d 幅 jpg' % ('✓' if n == 11 else '✗', n))
if n != 11:
    ok = False

p = os.path.join(dep, 'scripts', 'auto_value.py')
has = os.path.isfile(p) and "c['value'] = vals[i]" in open(p, encoding='utf-8').read()
print('%s auto_value.py（含 value 赋值修复）' % ('✓' if has else '✗'))
if not has:
    ok = False

for f in ['zone_region_map.npz', 'region_zone_map.json']:
    e = os.path.isfile(os.path.join(dep, 'cache', f))
    print('%s cache/%s' % ('✓' if e else '✗', f))
    if not e:
        ok = False

# 8 幅 v2 值表 dev/deploy 完全一致
same = all(json.load(open(os.path.join(dep, 'cache', 'manual_labels_v2', k + '_lines.json'), encoding='utf-8')) ==
           json.load(open(os.path.join(dev, 'cache', 'manual_labels_v2', k + '_lines.json'), encoding='utf-8'))
           for k in ['1h-Pa', '1h-Cv', '6h-Pa', '6h-Cv', '24h-Pa', '24h-Cv', '3d-Pa', '3d-Cv'])
print('%s 8 幅 v2 值表 dev/deploy 逐字节一致' % ('✓' if same else '✗'))
if not same:
    ok = False

print('部署校验：%s' % ('全部通过' if ok else '有失败项'))
