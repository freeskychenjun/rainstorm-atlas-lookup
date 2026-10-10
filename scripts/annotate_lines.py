# -*- coding: utf-8 -*-
"""
线位编号标注图：把点位附近的每条等值线编号（L1、L2…）、标出到点距离与已读到的值，
供人工在图上圈注未读值线条的数值。

用法: python annotate_lines.py --lon 115.5105 --lat 28.9894 --out-dir DIR [--kml x.kml]
产物: <out>/lines_<sheet>.jpg 每幅一张（绿十字=点位，红圈=线位，编号=线号）
      <out>/lines_summary.json 线号 → 方位/距离/已知值
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup import STAT_SHEETS, stat_xy, parse_kml, safe, DEFAULT_ATLAS
from parse_atlas import DEFAULT_CACHE

KM = 111.0 / 1162.0


def load_font(size=26):
    for p in (r'C:\Windows\Fonts\msyhbd.ttc', r'C:\Windows\Fonts\msyh.ttc',
              r'C:\Windows\Fonts\simhei.ttf', r'C:\Windows\Fonts\arialbd.ttf'):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lon', type=float)
    ap.add_argument('--lat', type=float)
    ap.add_argument('--kml', default='')
    ap.add_argument('--name', default='')
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--query-json', default='', help='query_atlas.py 产出的 JSON（含各幅命中点）')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    if a.kml:
        name, lon, lat = parse_kml(a.kml)[0]
    else:
        name, lon, lat = (a.name or '未命名'), a.lon, a.lat

    qj = a.query_json or os.path.join(a.out_dir, 'query_%s.json' % safe(name))
    hits_by_sheet = {}
    if os.path.isfile(qj):
        q = json.load(open(qj, encoding='utf-8'))
        hits_by_sheet = {k: v.get('hits', []) for k, v in q['sheets'].items()}

    font = load_font(26)
    font_s = load_font(20)
    summary = {}
    for fn, title in STAT_SHEETS:
        key = fn.split('--')[1].replace('.jpg', '')
        im = Image.open(os.path.join(a.atlas, fn)).convert('RGB')
        x, y = stat_xy(lon, lat, *im.size)
        x, y = int(x), int(y)
        hits = hits_by_sheet.get(key, [])
        # 只保留 100 km 内、且按方位聚类后距离最近的线位
        pick = []
        for h in sorted(hits, key=lambda t: t['dist_km']):
            if h['dist_km'] > 100:
                continue
            if all(abs(h['angle'] - p['angle']) > 12 for p in pick):
                pick.append(h)
        pick.sort(key=lambda h: h['angle'])
        R = 950
        box = (max(x - R, 0), max(y - R, 0), min(x + R, im.size[0]), min(y + R, im.size[1]))
        crop = im.crop(box)
        d = ImageDraw.Draw(crop)
        px, py = x - box[0], y - box[1]
        d.line((px - 60, py, px + 60, py), fill=(0, 200, 0), width=10)
        d.line((px, py - 60, px, py + 60), fill=(0, 200, 0), width=10)
        rows = []
        for i, h in enumerate(pick, 1):
            hx = h['px'] if 'px' in h else None
            # 命中点坐标（由方位与距离反算，与 query_atlas 一致）
            ang = math.radians(h['angle'])
            r = h['dist_km'] / KM
            mx, my = int(x + math.cos(ang) * r), int(y + math.sin(ang) * r)
            cxp, cyp = mx - box[0], my - box[1]
            lvl = h.get('label_val')
            col = (0, 140, 0) if lvl else (220, 0, 0)
            d.ellipse((cxp - 26, cyp - 26, cxp + 26, cyp + 26), outline=col, width=7)
            txt = 'L%d' % i
            d.text((cxp + 30, cyp - 40), txt, fill=col, font=font)
            tag = ('=%s' % lvl) if lvl else '?'
            d.text((cxp + 30, cyp - 12), tag, fill=col, font=font_s)
            rows.append({'id': 'L%d' % i, 'angle': h['angle'], 'dist_km': h['dist_km'],
                         'known_value': lvl})
        crop.save(os.path.join(a.out_dir, 'lines_%s.jpg' % key), quality=90)
        summary[key] = {'title': title, 'point_px': [x, y], 'lines': rows,
                        'image': 'lines_%s.jpg' % key}
        unknown = [r['id'] for r in rows if not r['known_value']]
        print('%-8s 线位 %d 条，其中待读值 %d 条 %s' % (key, len(rows), len(unknown), unknown))
    json.dump(summary, open(os.path.join(a.out_dir, 'lines_summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
