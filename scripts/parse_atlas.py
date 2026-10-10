# -*- coding: utf-8 -*-
"""
图集预解析：把图幅的红色等值线矢量化并缓存，供 lookup/query 快速使用。
产物（缓存目录，默认 <skill>/cache）：
  <key>.npz           线条掩膜（packbits 压缩）
  <key>.labels.json   标签候选（等值线标签候选，已剔除站点标注/大字号地名/图题）
  <key>_labels_p*.jpg 标签候选分页拼图（每页 64 个，供一次性读值）
  <key>_overlay.jpg   线条+标签框叠加预览（1/4 缩放，校核用）
用法:
  python parse_atlas.py [--atlas DIR] [--cache DIR] [--key 1h-Pa]
"""
import argparse, json, os, time
import numpy as np
from PIL import Image, ImageDraw

STAT_SHEETS = [("1--1h-Pa.jpg", "1h-Pa"), ("2--1h-Cv.jpg", "1h-Cv"),
               ("3--6h-Pa.jpg", "6h-Pa"), ("4--6h-Cv.jpg", "6h-Cv"),
               ("5--24h-Pa.jpg", "24h-Pa"), ("6--24h-Cv.jpg", "24h-Cv"),
               ("7--3d-Pa.jpg", "3d-Pa"), ("8--3d-Cv.jpg", "3d-Cv")]
PART_SHEETS = [("9--产流分区.jpg", "zone-产流"), ("9--瞬时分区.jpg", "zone-瞬时"), ("9--推理分区.jpg", "zone-推理")]
_ATLAS_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'atlas'),
    r"D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集",
]
DEFAULT_ATLAS = next((p for p in _ATLAS_CANDIDATES if os.path.isdir(p)), _ATLAS_CANDIDATES[-1])
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")

def red_mask(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R > 120) & ((R - G) > 45) & ((R - B) > 40)

def runs_per_row(mask):
    runs = []
    mv = mask.view(np.int8)
    for y in range(mask.shape[0]):
        row = mv[y]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row, [0])))
        for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            runs.append((y, int(s), int(e)))
    return runs

def group_runs(runs):
    n = len(runs)
    parent = list(range(n))
    def find(x):
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r
    by_row = {}
    for i, (y, s, e) in enumerate(runs):
        by_row.setdefault(y, []).append(i)
    for y, idxs in by_row.items():
        nxt = by_row.get(y + 1)
        if not nxt:
            continue
        for i in idxs:
            _, s1, e1 = runs[i]
            for j in nxt:
                _, s2, e2 = runs[j]
                if s2 <= e1 + 1 and s1 <= e2 + 1:
                    ra, rb = find(i), find(j)
                    if ra != rb:
                        parent[rb] = ra
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(runs[i])
    return list(groups.values())

def feat(g):
    x0 = min(r[1] for r in g); x1 = max(r[2] for r in g)
    y0 = min(r[0] for r in g); y1 = max(r[0] for r in g)
    return dict(x0=x0, y0=y0, x1=x1, y1=y1, w=x1 - x0, h=y1 - y0,
                npix=sum(r[2] - r[1] for r in g), nruns=len(g))

def is_line(f):
    diag = (f['w'] ** 2 + f['h'] ** 2) ** 0.5
    return (diag > 260 and f['nruns'] >= 80) or (diag > 400)

def is_text(f):
    return 12 <= f['h'] <= 75 and 6 <= f['w'] <= 110 and f['npix'] < 3200 and f['nruns'] <= 110

def cluster_text(feats):
    fs = sorted(feats, key=lambda f: (f['y0'], f['x0']))
    used = [False] * len(fs); out = []
    for i, f in enumerate(fs):
        if used[i]:
            continue
        cur = [f]; used[i] = True; changed = True
        while changed:
            changed = False
            for j, g in enumerate(fs):
                if used[j]:
                    continue
                for c in cur:
                    vov = min(c['y1'], g['y1']) - max(c['y0'], g['y0'])
                    if vov > 0.45 * min(c['h'], g['h']) and (g['x0'] - c['x1'] < 26) and (c['x0'] - g['x1'] < 26):
                        cur.append(g); used[j] = True; changed = True; break
        x0 = min(c['x0'] for c in cur); x1 = max(c['x1'] for c in cur)
        y0 = min(c['y0'] for c in cur); y1 = max(c['y1'] for c in cur)
        out.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, w=x1 - x0, h=y1 - y0,
                        cx=(x0 + x1) // 2, cy=(y0 + y1) // 2, n=len(cur)))
    return out

def drop_station_pairs(cl):
    """剔除站点标注：站点标注是上下两行（均值 / 统计年数），凡上下 75px 内有同行伙伴者成对剔除"""
    drop = set()
    for i, c in enumerate(cl):
        for j, d in enumerate(cl):
            if i == j:
                continue
            if abs(d['cx'] - c['cx']) > 85:
                continue
            dy = d['y0'] - c['y1']
            if -75 <= dy <= 75:
                drop.add(i); drop.add(j); break
    return [c for i, c in enumerate(cl) if i not in drop]

def plausible_label(c, W, H):
    """等值线标签的数字形态过滤"""
    if c['h'] < 16 or c['h'] > 60:
        return False
    if c['w'] < 14 or c['w'] > 130:
        return False
    ar = c['w'] / max(c['h'], 1)
    if ar < 0.4 or ar > 4.2:
        return False
    if c['y0'] > 0.86 * H:          # 图题区
        return False
    if c['x0'] > 0.86 * W and c['y0'] > 0.80 * H:   # 图例区
        return False
    if c['x0'] < 0.02 * W or c['y0'] < 0.02 * H:
        return False
    return True

def build_pages(im, labels, out_prefix, cols=8, rows=8, tile=(170, 105), scale=1.0):
    per = cols * rows
    tw, th = int(tile[0] * scale), int(tile[1] * scale)
    pages = []
    for p in range((len(labels) + per - 1) // per):
        chunk = labels[p * per:(p + 1) * per]
        canvas = Image.new('RGB', (cols * tw, rows * (th + 18)), (255, 255, 255))
        d = ImageDraw.Draw(canvas)
        for i, c in enumerate(chunk):
            gi = p * per + i
            cx, cy = c['cx'], c['cy']
            px, py = tile[0] // 2, tile[1] // 2
            box = (max(cx - px, 0), max(cy - py, 0), min(cx + px, im.size[0]), min(cy + py, im.size[1]))
            crop = im.crop(box).resize((tw, th))
            r, cc = divmod(i, cols)
            canvas.paste(crop, (cc * tw, r * (th + 18) + 18))
            d.text((cc * tw + 3, r * (th + 18) + 3), '#%d' % gi, fill=(0, 0, 200))
        fn = '%s_p%d.jpg' % (out_prefix, p + 1)
        canvas.save(fn, quality=90)
        pages.append(fn)
    return pages

def parse_sheet(atlas, name, key, cache):
    t0 = time.time()
    im = Image.open(os.path.join(atlas, name)).convert('RGB')
    W, H = im.size
    mask = red_mask(os.path.join(atlas, name))
    groups = group_runs(runs_per_row(mask))
    line_mask = np.zeros_like(mask)
    text_feats = []
    for g in groups:
        f = feat(g)
        if is_line(f):
            for (y, s, e) in g:
                line_mask[y, s:e] = True
        elif f['npix'] < 2600 and 8 <= f['h'] <= 95 and f['w'] <= 160:
            text_feats.append(f)      # 数字/文字候选（含被误判为 other 的小斑块）
    labels = [c for c in drop_station_pairs(cluster_text(text_feats)) if plausible_label(c, W, H)]
    labels.sort(key=lambda c: (c['cy'], c['cx']))
    np.savez_compressed(os.path.join(cache, key + '.npz'),
                        shape=np.array(mask.shape), packed=np.packbits(line_mask))
    with open(os.path.join(cache, key + '.labels.json'), 'w', encoding='utf-8') as fh:
        json.dump(labels, fh, ensure_ascii=False)
    pages = build_pages(im, labels, os.path.join(cache, key + '_labels'))
    ov = Image.fromarray((~line_mask * 255).astype(np.uint8)).convert('RGB')
    d = ImageDraw.Draw(ov)
    for c in labels:
        d.rectangle((c['x0'] - 2, c['y0'] - 2, c['x1'] + 2, c['y1'] + 2), outline=(0, 0, 255), width=4)
    ov.resize((W // 4, H // 4)).save(os.path.join(cache, key + '_overlay.jpg'), quality=85)
    print('%-10s 线条掩膜OK  标签候选=%d  拼图页=%d  用时%.1fs' % (key, len(labels), len(pages), time.time() - t0))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--key', default='')
    ap.add_argument('--stat-only', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    sheets = STAT_SHEETS + ([] if a.stat_only else PART_SHEETS)
    for name, key in sheets:
        if a.key and key != a.key:
            continue
        try:
            parse_sheet(a.atlas, name, key, a.cache)
        except Exception as ex:
            print('%s 解析失败: %s' % (key, ex))

if __name__ == '__main__':
    main()
