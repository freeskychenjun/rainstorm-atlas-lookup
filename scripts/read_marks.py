# -*- coding: utf-8 -*-
"""
从人工标注图（用户用黑色椭圆圈出每根等值线的值）中提取所有椭圆圈，逐个裁图放大，
拼成一页供读值，并输出每个圈的中心坐标（供与线位编号对照）。
用法: python read_marks.py --image <标注图> --out-dir DIR [--min 40 --max 170]
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def dark_mask(path, thr=80):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.int16)
    return (a.max(axis=2) < thr)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--min', type=int, default=38)
    ap.add_argument('--max', type=int, default=190)
    ap.add_argument('--thr', type=int, default=80)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    im = Image.open(a.image).convert('RGB')
    mask = dark_mask(a.image, a.thr)
    groups = group_runs(runs_per_row(mask))
    cands = []
    for g in groups:
        x0 = min(r[1] for r in g); x1 = max(r[2] for r in g)
        y0 = min(r[0] for r in g); y1 = max(r[0] for r in g)
        w, h = x1 - x0, y1 - y0
        npix = sum(r[2] - r[1] for r in g)
        if not (a.min <= w <= a.max and a.min <= h <= a.max):
            continue
        if not (0.45 <= w / max(h, 1) <= 2.2):
            continue
        fill = npix / max(w * h, 1)
        if not (0.04 <= fill <= 0.42):      # 空心环
            continue
        # 四角应为空（椭圆特征）
        k = max(int(min(w, h) * 0.25), 4)
        sub = mask[y0:y1 + 1, x0:x1 + 1]
        corners = (sub[:k, :k].mean() + sub[:k, -k:].mean() + sub[-k:, :k].mean() + sub[-k:, -k:].mean()) / 4
        if corners > 0.22:
            continue
        cands.append(dict(cx=(x0 + x1) // 2, cy=(y0 + y1) // 2, w=w, h=h, npix=npix,
                          fill=round(float(fill), 3)))
    cands.sort(key=lambda c: (c['cy'], c['cx']))
    print('检出椭圆圈:', len(cands))
    json.dump(cands, open(os.path.join(a.out_dir, 'marks.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    # 拼图（放大 4 倍）
    tile = (300, 220); cols = 5; sc = 4
    rows = max((len(cands) + cols - 1) // cols, 1)
    cv = Image.new('RGB', (cols * tile[0], rows * (tile[1] + 20)), (255, 255, 255))
    dr = ImageDraw.Draw(cv)
    for i, c in enumerate(cands):
        half_w, half_h = tile[0] // (2 * sc) + 6, tile[1] // (2 * sc) + 6
        box = (max(c['cx'] - half_w, 0), max(c['cy'] - half_h, 0),
               min(c['cx'] + half_w, im.size[0]), min(c['cy'] + half_h, im.size[1]))
        crop = im.crop(box).resize((tile[0] - 8, tile[1] - 8))
        r, cc = divmod(i, cols)
        cv.paste(crop, (cc * tile[0] + 4, r * (tile[1] + 20) + 18))
        dr.text((cc * tile[0] + 4, r * (tile[1] + 20) + 3),
                '#%d (%d,%d)' % (i, c['cx'], c['cy']), fill=(0, 0, 200))
    out = os.path.join(a.out_dir, 'marks_montage.jpg')
    cv.save(out, quality=93)
    print('拼图:', out, cv.size)
    # 在原图上标出检出结果，便于核对是否有遗漏
    ov = im.copy()
    d2 = ImageDraw.Draw(ov)
    for i, c in enumerate(cands):
        d2.rectangle((c['cx'] - c['w'] // 2 - 4, c['cy'] - c['h'] // 2 - 4,
                      c['cx'] + c['w'] // 2 + 4, c['cy'] + c['h'] // 2 + 4),
                     outline=(0, 150, 0), width=3)
        d2.text((c['cx'] + c['w'] // 2, c['cy'] - c['h'] // 2), '#%d' % i, fill=(0, 120, 0))
    ov.save(os.path.join(a.out_dir, 'marks_overlay.jpg'), quality=88)


if __name__ == '__main__':
    main()
