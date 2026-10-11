# -*- coding: utf-8 -*-
"""一次性固化等值线几何：把 build_lines 的确定性输出存入 cache/geometry/<key>.npz。

背景：auto_value.py 旧版每次查询都对 8 幅大图重新数字化，实测单点 103 秒；
几何固化后查询只需加载缓存（~2 秒）。本脚本只在下列情况需要重跑：
  1) 更换/重扫图集 jpg（分辨率不可变，配准依赖绝对像素）；
  2) 调整 digitize.build_lines 的参数（min_px / merge_px）；
  3) 重新数字化改变了线集。
改完必须运行 deploy.ps1 同步 cache/geometry/ 到部署目录。

用法:
  python tools/build_geometry.py            # 全部 8 幅（约 2 分钟）
  python tools/build_geometry.py --key 1h-Pa

自校验：npz 内记录图集 jpg 的 MD5 与数字化参数；auto_value.py 加载时核对，
不一致直接报错（防换图后旧几何继续查值）。
"""
import argparse, hashlib, json, os, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..', 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
from registry import SKILL_ROOT, STAT_KEYS, STAT_FILE, resolve_atlas
from digitize import build_lines

GEOM_DIR = os.path.join(SKILL_ROOT, 'cache', 'geometry')
DIGITIZE_PARAMS = {"min_px": 1200, "merge_px": 60}   # 必须与线值库 v2 建库时一致


def md5_of(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def build_one(key, atlas, force=False):
    src = os.path.join(atlas, STAT_FILE[key])
    if not os.path.isfile(src):
        print('[%s] !! 图集文件缺失: %s' % (key, src))
        return False
    out = os.path.join(GEOM_DIR, key + '.npz')
    os.makedirs(GEOM_DIR, exist_ok=True)

    _, W, H, lines = build_lines(src, min_px=DIGITIZE_PARAMS["min_px"],
                                 merge_px=DIGITIZE_PARAMS["merge_px"])
    ids = [c['id'] for c in lines]
    flat = np.concatenate([np.asarray(c['samples'], dtype=np.int32) for c in lines]) \
        if lines else np.zeros((0, 2), dtype=np.int32)
    offsets = np.zeros(len(lines) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum([len(c['samples']) for c in lines])
    meta = {"key": key, "file": STAT_FILE[key], "W": W, "H": H,
            "atlas_md5": md5_of(src), "params": DIGITIZE_PARAMS,
            "n_lines": len(lines), "built_at": time.strftime('%Y-%m-%d %H:%M:%S')}
    np.savez_compressed(out, meta=np.array([json.dumps(meta, ensure_ascii=False)]),
                        ids=np.array(ids, dtype='<U16'),
                        offsets=offsets, flat=flat,
                        closed=np.array([bool(c.get('closed')) for c in lines]))

    # 一致性核对：线值库 v2 的每个线号都必须能在新几何里找到，否则值会挂空
    v2p = os.path.join(SKILL_ROOT, 'cache', 'manual_labels_v2', key + '_lines.json')
    ok = True
    if os.path.isfile(v2p):
        v2 = json.load(open(v2p, encoding='utf-8'))
        missing = [k for k in v2 if k not in set(ids)]
        if missing:
            ok = False
            print('[%s] !! 线值库 %d 个线号在新几何中不存在（几何与线值库不同源，勿部署！）: %s'
                  % (key, len(missing), ', '.join(missing[:10])))
    n_valued = len(set(ids) & set(v2)) if os.path.isfile(v2p) else 0
    print('[%s] 线 %d 条（闭合 %d），挂上 v2 值 %d 条 → %s'
          % (key, len(lines), sum(bool(c.get('closed')) for c in lines), n_valued, out))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', default='', help='只建单幅（如 1h-Pa）；默认全部 8 幅')
    ap.add_argument('--atlas', default=resolve_atlas())
    a = ap.parse_args()
    keys = [a.key] if a.key else STAT_KEYS
    bad = [k for k in keys if not build_one(k, a.atlas)]
    print('完成。失败图幅：' + (', '.join(bad) if bad else '无'))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
