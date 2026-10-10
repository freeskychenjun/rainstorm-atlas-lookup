# -*- coding: utf-8 -*-
r"""
基于预解析缓存的快速查值 + 校核图生成。
用法:
  python query_atlas.py --lon 115.398 --lat 26.115 --name 测试位置 --out-dir D:\out
  python query_atlas.py --kml points.kml --out-dir D:\out
  python query_atlas.py --lon ... --lat ... --out-dir D:\out --save-values '{"1h-Pa":{"12":45}}'
输出:
  <out-dir>/query_<name>.json      各幅最近等值线（距离、关联标签、已知值、内插结果）
  <out-dir>/query_<name>_evidence.jpg  3x3 九宫格校核图（8 统计幅 + 产流分区，彩色原图）
  <out-dir>/query_<name>_labels.jpg    未识别标签的拼图（如需人工读值）
"""
import argparse, base64, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup import STAT_SHEETS, PART_SHEETS, stat_xy, part_xy, parse_kml, safe, DEFAULT_ATLAS
from parse_atlas import DEFAULT_CACHE

KM_PER_PX = 111.0 / 1162.0

def load_mask(cache, key):
    z = np.load(os.path.join(cache, key + '.npz'))
    shape = tuple(z['shape'])
    return np.unpackbits(z['packed'])[:shape[0] * shape[1]].reshape(shape).astype(bool)

def load_labels(cache, key):
    p = os.path.join(cache, key + '.labels.json')
    return json.load(open(p, encoding='utf-8')) if os.path.isfile(p) else []

def load_values(cache):
    p = os.path.join(cache, 'label_values.json')
    return json.load(open(p, encoding='utf-8')) if os.path.isfile(p) else {}

def save_values(cache, new):
    vals = load_values(cache)
    for key, kv in new.items():
        vals.setdefault(key, {}).update({str(k): v for k, v in kv.items()})
    json.dump(vals, open(os.path.join(cache, 'label_values.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return vals

def path_on_line(mask, x0, y0, x1, y1, tol=5, samples=40):
    """检查两点间是否存在沿线条的连续路径（采样点到线条的距离占比）"""
    hit = 0
    H, W = mask.shape
    for t in np.linspace(0.05, 0.95, samples):
        x = int(round(x0 + (x1 - x0) * t)); y = int(round(y0 + (y1 - y0) * t))
        if 0 <= y < H and 0 <= x < W:
            if mask[max(0, y - tol):y + tol + 1, max(0, x - tol):x + tol + 1].any():
                hit += 1
    return hit / samples

def ray_hits(mask, x, y, max_km=180, step=2, min_gap_px=28, max_per_ray=4):
    """多方向射线求交：每条射线记录至多 max_per_ray 个交点（用于判断点的两侧夹持次序）"""
    H, W = mask.shape
    maxr = int(max_km / KM_PER_PX)
    hits = []
    for deg in range(0, 360, 3):
        rad = math.radians(deg)
        dx, dy = math.cos(rad), math.sin(rad)
        found = []
        last = -10 ** 9
        for r in range(12, maxr, step):
            xx = int(round(x + dx * r)); yy = int(round(y + dy * r))
            if not (0 <= xx < W and 0 <= yy < H):
                break
            if mask[max(0, yy - 1):yy + 2, max(0, xx - 1):xx + 2].any():
                if r - last >= min_gap_px:
                    found.append(r)
                    last = r
                    if len(found) >= max_per_ray:
                        break
        for n, r in enumerate(found):
            hits.append((deg, r * KM_PER_PX, int(round(x + dx * r)), int(round(y + dy * r)), n))
    # 合并不同角度但空间上重合的同一交点
    merged = []
    for h in hits:
        for m in merged:
            if math.hypot(h[2] - m[2], h[3] - m[3]) * KM_PER_PX < 15:
                break
        else:
            merged.append(h)
    return merged

def associate(mask, labels, hit, max_px=380):
    """把命中点与最近的标签关联（要求路径大致沿线条）"""
    hx, hy = hit[2], hit[3]
    cands = []
    for i, c in enumerate(labels):
        d = math.hypot(c['cx'] - hx, c['cy'] - hy)
        if d <= max_px:
            cands.append((d, i, c))
    cands.sort(key=lambda t: t[0])
    for d, i, c in cands[:6]:
        frac = path_on_line(mask, hx, hy, c['cx'], c['cy'])
        if frac >= 0.55:
            return i, c, d, frac
    return None, None, None, None

def crop_color(atlas, fn, x, y, half=380, out_size=460):
    im = Image.open(os.path.join(atlas, fn)).convert('RGB')
    W, H = im.size
    x0, y0 = max(int(x - half), 0), max(int(y - half), 0)
    x1, y1 = min(int(x + half), W), min(int(y + half), H)
    c = im.crop((x0, y0, x1, y1))
    d = ImageDraw.Draw(c)
    px, py = int(x - x0), int(y - y0)
    d.line((px - 30, py, px + 30, py), fill=(0, 200, 0), width=5)
    d.line((px, py - 30, px, py + 30), fill=(0, 200, 0), width=5)
    return c.resize((out_size, out_size))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lon', type=float); ap.add_argument('--lat', type=float)
    ap.add_argument('--kml', default=''); ap.add_argument('--name', default='')
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--max-km', type=float, default=180)
    ap.add_argument('--save-values', default='', help='JSON: {"sheet_key": {"label_index": value}}')
    ap.add_argument('--save-values-file', dest='save_values_file', default='', help='同上，从文件读（推荐）')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    if a.save_values or a.save_values_file:
        if a.save_values_file:
            newvals = json.load(open(a.save_values_file, encoding='utf-8-sig'))
        else:
            newvals = json.loads(a.save_values)
        save_values(a.cache, newvals)

    if a.kml:
        pts = parse_kml(a.kml)
        if not pts:
            print(json.dumps({'error': 'KML 无有效坐标'}, ensure_ascii=False)); sys.exit(2)
        name, lon, lat = pts[0]
    else:
        name, lon, lat = a.name or '未命名', a.lon, a.lat
    if lon is None or lat is None:
        print(json.dumps({'error': '需 --lon/--lat 或 --kml'}, ensure_ascii=False)); sys.exit(2)

    vals = load_values(a.cache)
    result = {'name': name, 'lon': lon, 'lat': lat, 'sheets': {}}
    unknown = []
    for fn, tkey in STAT_SHEETS:
        key = fn.split('--')[1].replace('.jpg', '')      # 与 parse_atlas.py 的缓存键一致
        mp = os.path.join(a.cache, key + '.npz')
        if not os.path.isfile(mp):
            result['sheets'][key] = {'error': '未解析（先运行 parse_atlas.py）'}
            continue
        mask = load_mask(a.cache, key)
        labels = load_labels(a.cache, key)
        im = Image.open(os.path.join(a.atlas, fn))
        x, y = stat_xy(lon, lat, *im.size)
        hits = ray_hits(mask, x, y, max_km=a.max_km)
        rows = []
        for h in sorted(hits, key=lambda t: t[1]):
            li, c, d, frac = associate(mask, labels, h, max_px=700)
            v = vals.get(key, {}).get(str(li)) if li is not None else None
            rows.append({'angle': h[0], 'dist_km': round(h[1], 1), 'order': h[4],
                         'label_index': li, 'label_xy': [c['cx'], c['cy']] if c else None,
                         'label_val': v, 'trace_frac': round(frac, 2) if frac else None})
            if li is not None and v is None:
                unknown.append((key, li, c['cx'], c['cy']))
        result['sheets'][key] = {'px': [round(x), round(y)], 'hits': rows}
    # 分区图（只取产流）
    for fn, tkey, cx, cy, primary in PART_SHEETS:
        if not primary:
            continue
        im = Image.open(os.path.join(a.atlas, fn))
        x, y = part_xy(lon, lat, cx, cy)
        result['sheets']['zone-产流'] = {'px': [round(x), round(y)], 'hits': []}

    # 未识别标签拼图
    if unknown:
        uniq = []
        for k, li, cx, cy in unknown:
            if (k, li) not in [(u[0], u[1]) for u in uniq]:
                uniq.append((k, li, cx, cy))
        tile_w, tile_h, cols2 = 240, 150, 5
        rows2 = (len(uniq) + cols2 - 1) // cols2
        mc = Image.new('RGB', (cols2 * tile_w, rows2 * (tile_h + 18)), (255, 255, 255))
        dm = ImageDraw.Draw(mc)
        for i, (k, li, cx, cy) in enumerate(uniq):
            src = dict((ff.split('--')[1].replace('.jpg', ''), ff) for ff, _ in STAT_SHEETS)[k]
            im2 = Image.open(os.path.join(a.atlas, src))
            half_w, half_h = 85, 52
            box = (max(cx - half_w, 0), max(cy - half_h, 0), min(cx + half_w, im2.size[0]), min(cy + half_h, im2.size[1]))
            crop = im2.crop(box).resize((tile_w - 8, tile_h - 8))
            r, cc = divmod(i, cols2)
            mc.paste(crop, (cc * tile_w + 4, r * (tile_h + 18) + 16))
            dm.text((cc * tile_w + 4, r * (tile_h + 18) + 2), '%s#%d' % (k, li), fill=(0, 0, 200))
        lu = os.path.join(a.out_dir, 'query_%s_labels.jpg' % safe(name))
        mc.save(lu, quality=92)
        result['labels_image'] = lu

    out = os.path.join(a.out_dir, 'query_%s.json' % safe(name))
    json.dump(result, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    brief = {k: [[round(h['dist_km']), h['label_val']] for h in v.get('hits', [])[:5]] for k, v in result['sheets'].items()}
    print(json.dumps({'status': 'ok', 'json': out,
                      'labels_image': result.get('labels_image'),
                      'nearest': brief}, ensure_ascii=False))

if __name__ == '__main__':
    main()
