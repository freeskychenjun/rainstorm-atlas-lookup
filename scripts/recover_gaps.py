# -*- coding: utf-8 -*-
"""缺口恢复诊断：在主流程已提取段之外，用更温和的形态学参数找回丢失的红线延伸段。
候选条件：骨长>=120px、平均粗细>=5px（排除文字）、R-G>=115（排除橙色高速）、>=50% 在省内。"""
import json, os, sys
import numpy as np
import cv2
from skimage.morphology import skeletonize
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_atlas import red_mask, DEFAULT_ATLAS
from digitize_zones import (CX, CY, S9, KM, TITLE_Y, LEGEND_X, LEGEND_Y,
                            degree_map, province_roi, seg_median_rg, font)

SHEET = '9--产流分区.jpg'
OUT = r'D:\DSH工作区\自动查找图集参数\数字化_产流分区'
GEO = r'D:\DSH工作区\自动查找图集参数\rainstorm-atlas-lookup\cache\jiangxi_360000.json'


def diameter_path(sk):
    """双 BFS 求分量直径路径（8 邻域），返回有序点列 [(x,y),...]"""
    ys, xs = np.nonzero(sk)
    if len(ys) == 0:
        return []
    pts = set(zip(xs.tolist(), ys.tolist()))
    start = (int(xs[0]), int(ys[0]))

    def bfs(src):
        dist = {src: 0}
        par = {src: None}
        q = [src]
        far = src
        for p in q:
            if dist[p] > dist[far]:
                far = p
            x, y = p
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    np_ = (x + dx, y + dy)
                    if np_ in pts and np_ not in dist:
                        dist[np_] = dist[p] + 1
                        par[np_] = p
                        q.append(np_)
        return far, par

    a, _ = bfs(start)
    b, par = bfs(a)
    path = []
    p = b
    while p is not None:
        path.append(p)
        p = par[p]
    return path[::-1]


def main():
    path = os.path.join(DEFAULT_ATLAS, SHEET)
    im = Image.open(path).convert('RGB')
    W, H = im.size
    im_arr = np.asarray(im).astype(np.int16)

    raw = red_mask(path)
    # 同 clean_mask 的区域剔除
    raw[int(TITLE_Y * H):, :] = False
    raw[int(LEGEND_Y * H):, int(LEGEND_X * W):] = False
    # 温和形态学：k=5 开 + k=5 闭
    m = raw.astype(np.uint8) * 255
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k5)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k5)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 300:
            keep[lab == i] = 255
    mask = keep > 0

    # 已提取段 → 覆盖区（膨胀 20px）
    J = json.load(open(os.path.join(OUT, 'zones_产流.json'), encoding='utf-8'))
    cov = np.zeros((H, W), np.uint8)
    for s in J['segments']:
        pts = np.array(s['polyline_px'], np.int32).reshape(-1, 1, 2)
        cv2.polylines(cov, [pts], s['closed'], 255, thickness=40)
    missing = mask & (cov == 0)

    roi, _wall, _poly = province_roi(GEO, W, H)

    n, lab, stats, cent = cv2.connectedComponentsWithStats(missing.astype(np.uint8), 8)
    cands = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 150:
            continue
        comp = lab == i
        sk = skeletonize(comp)
        pth = diameter_path(sk)
        if len(pth) < 120:
            continue
        thick = area / max(len(pth), 1)
        if thick < 5:
            continue
        arr = np.array(pth)
        inside = roi[arr[:, 1], arr[:, 0]].mean()
        rg = seg_median_rg(im_arr, pth)
        cands.append(dict(i=i, area=int(area), len_px=len(pth), thick=round(thick, 1),
                          inside=round(float(inside), 2), rg=None if rg is None else round(rg),
                          x0=int(arr[:, 0].min()), x1=int(arr[:, 0].max()),
                          y0=int(arr[:, 1].min()), y1=int(arr[:, 1].max()),
                          lon0=round(115.88 + (arr[:, 0].min() - CX) / S9, 2),
                          lon1=round(115.88 + (arr[:, 0].max() - CX) / S9, 2),
                          lat0=round(28.68 - (arr[:, 1].min() - CY) / S9, 2),
                          lat1=round(28.68 - (arr[:, 1].max() - CY) / S9, 2),
                          path=[(int(x), int(y)) for x, y in pth]))
    cands.sort(key=lambda c: -c['len_px'])
    for c in cands:
        print('cand#%-3d len=%5dpx(%5.1fkm) thick=%4.1f in=%.2f rg=%s lon %.2f-%.2f lat %.2f-%.2f'
              % (c['i'], c['len_px'], c['len_px'] * KM, c['thick'], c['inside'], c['rg'],
                 c['lon0'], c['lon1'], c['lat0'], c['lat1']))

    # 预览图
    a = (np.asarray(im).astype(np.float32) * 0.35).astype(np.uint8)
    pal = [(0, 255, 255), (255, 0, 255), (0, 255, 0), (255, 255, 0), (255, 128, 0), (0, 128, 255)]
    for k, c in enumerate(cands):
        pts = np.array(c['path'], np.int32).reshape(-1, 1, 2)
        cv2.polylines(a, [pts], False, pal[k % len(pal)], thickness=10)
    ov = Image.fromarray(a)
    d = ImageDraw.Draw(ov)
    f = font(56)
    for k, c in enumerate(cands):
        mx, my = c['path'][len(c['path']) // 2]
        d.text((mx + 8, my - 52), '#%d' % c['i'], fill=(255, 255, 255), font=f)
        d.text((mx + 6, my - 54), '#%d' % c['i'], fill=pal[k % len(pal)], font=f)
    ov.resize((W // 4, H // 4)).save(os.path.join(OUT, 'recover.jpg'), quality=90)
    json.dump([{k2: v for k2, v in c.items()} for c in cands],
              open(os.path.join(OUT, 'recover_cands.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('共 %d 个候选 → recover.jpg / recover_cands.json' % len(cands))


if __name__ == '__main__':
    main()
