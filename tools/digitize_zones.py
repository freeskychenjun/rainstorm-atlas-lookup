# -*- coding: utf-8 -*-
"""
产流分区边界数字化（对标 digitize.py 的等值线数字化）：
 1) 提取附图3-1（9--产流分区.jpg）的红色粗线分区边界：区域剔除（图题/图例）→
    形态学开运算（蚀掉红色市名等细笔画，断开压线文字与粗线的连接）→ 小闭运算桥接发丝断口 →
    连通分量面积过滤 → 骨架化
 2) 骨架上 8 邻域度数 ≥3 的像素为交叉结点（膨胀聚簇），挖掉结点盘后连通分量即段；
    每段双 BFS 求直径路径得有序折线；无端点分量按闭合环处理
 3) 毛刺剔除（短且带自由端）→ 自由端点共线桥接（恢复文字压线造成的断口）→
    过近结点合并（粗线交叉的骨架结点簇常被拆成多个相距几~二十 px 的假结点）→
    自由端就近吸附结点（文字断口恰在结点旁，桥接够不到）→
    省界 ROI + 颜色过滤（剔除省外大字、褐色国道 R-G<115、橙色高速等误入段）→
    度=1 假结点拆回自由端 → 自由端沿±90°扇形射线延长到省界（分区边界必终于省界或结点）→
    Douglas-Peucker 抽稀 → 编号 B1、B2…（结点 N1、N2…）
产物：
  <out>/zones_产流.json      段/结点折线（像素 + 经纬度；端点 node=结点号 / border=true=终于省界）
  <out>/zones_产流_p1..p3.jpg 编号校核图（3 页）
  <out>/zones_产流_debug.jpg  文字剔除对比图（蓝=被剔红像素，绿=保留粗线）
自检：--check-zones 段回画 + 省界墙洪水填充，封闭区域（质心须在省域内、面积≥10万px）应=9
用法:
  python digitize_zones.py --out-dir DIR [--atlas DIR] [--open-k 9] [--min-area 600]
      [--close-k 5] [--bridge-px 80] [--absorb-px 100] [--min-rg 115] [--spur-px 30]
      [--epsilon 4.0] [--check-zones]
注意：配准常数 CX/CY/S9 是按当前扫描尺寸（6522×8924）标定的绝对像素（锚点南昌 115.88E,28.68N），
     换扫描件需重新标定；JSON 中已记录图幅 W/H 供核对。
     省界用阿里云 DataV 矢量（cache/jiangxi_360000.json），仅作过滤/延长/外墙，
     与图面粉红省界存在 km 级偏差，border 延长段是接到矢量省界的连接线，非图上实测线。
"""
import argparse, json, math, os, sys
from collections import deque
import numpy as np
import cv2
from PIL import Image, ImageDraw

for _p in (os.path.dirname(os.path.abspath(__file__)),
           os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from parse_atlas import red_mask, DEFAULT_ATLAS, DEFAULT_CACHE

# ---------------- 配准常数（与 lookup.py 一致，勿随意改动） ----------------
CX, CY, S9 = 3160.0, 3390.0, 1170.0
A_LON, A_LAT = 115.88, 28.68          # 锚点：南昌
KM = 111.0 / S9                       # 每像素 km（近似）
SHEET = '9--产流分区.jpg'
# 区域剔除比例（图题 / 图例）
TITLE_Y, LEGEND_X, LEGEND_Y = 0.94, 0.78, 0.72

PAL = [(220, 30, 30), (30, 140, 30), (30, 80, 220), (230, 140, 20),
       (150, 40, 160), (0, 160, 160), (200, 60, 120), (120, 120, 20),
       (90, 90, 90), (0, 100, 60), (180, 0, 80), (60, 140, 200)]


def px2ll(x, y):
    return A_LON + (x - CX) / S9, A_LAT - (y - CY) / S9


def font(size):
    from PIL import ImageFont
    for p in (r'C:\Windows\Fonts\msyhbd.ttc', r'C:\Windows\Fonts\msyh.ttc'):
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def ellipse(k):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def clean_mask(mask, W, H, open_k, close_k, min_area):
    """区域剔除 → 开运算去文字 → 小闭运算桥断口 → 面积过滤 → 干净粗线掩膜"""
    m = mask.copy()
    m[int(TITLE_Y * H):, :] = False                       # 图题
    m[int(LEGEND_Y * H):, int(LEGEND_X * W):] = False     # 图例
    u = (m * 255).astype(np.uint8)
    u = cv2.morphologyEx(u, cv2.MORPH_OPEN, ellipse(open_k))
    u = cv2.morphologyEx(u, cv2.MORPH_CLOSE, ellipse(close_k))
    n, lab, stats, _ = cv2.connectedComponentsWithStats((u > 0).astype(np.uint8), connectivity=8)
    out = np.zeros_like(m)
    ndrop = 0
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[lab == i] = True
        else:
            ndrop += 1
    return out, ndrop


def degree_map(sk):
    """骨架像素的 8 邻域邻居数"""
    k = np.ones((3, 3), np.float32)
    cnt = cv2.filter2D(sk.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
    return np.rint(cnt).astype(np.int16) - sk.astype(np.int16)


def find_nodes(sk, deg, junc_dilate):
    """度数≥3 的像素膨胀聚簇为结点；返回 (结点列表, 结点盘掩膜, 结点盘标签图)"""
    jpix = (sk & (deg >= 3)).astype(np.uint8)
    disk = cv2.dilate(jpix, ellipse(2 * junc_dilate + 1)) if jpix.any() else jpix
    n, lab, stats, cents = cv2.connectedComponentsWithStats(disk, connectivity=8)
    nodes = []
    for i in range(1, n):
        ys, xs = np.nonzero((lab == i) & (jpix > 0))
        if len(xs) == 0:
            ys, xs = np.nonzero(lab == i)
        nodes.append(dict(x=float(xs.mean()), y=float(ys.mean()), npix=int(len(xs))))
    return nodes, disk > 0, lab


def trace_component(comp, deg, junc_near):
    """单个段分量 → 有序折线。
    comp: set[(x,y)]；junc_near: 与结点盘相邻的段像素集合（全局掩膜）。
    返回 (pts, closed, dropped_px)"""
    if len(comp) <= 2:
        return sorted(comp, key=lambda p: (p[1], p[0])), False, 0

    def neighbors(p):
        x, y = p
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                q = (x + dx, y + dy)
                if q in comp:
                    yield q

    def bfs(src):
        """返回 (最远点, {点: 父点})"""
        far, dmax = src, 0
        par = {src: None}
        q = deque([(src, 0)])
        while q:
            p, d = q.popleft()
            if d > dmax:
                far, dmax = p, d
            for nb in neighbors(p):
                if nb not in par:
                    par[nb] = p
                    q.append((nb, d + 1))
        return far, par

    # 端点候选：整体骨架上 deg==1，或与结点盘相邻（被挖断处的尖端）
    tips = [p for p in comp if deg[p[1], p[0]] == 1 or p in junc_near]
    if not tips:
        # 闭合环：贪心走圈
        start = min(comp, key=lambda p: (p[1], p[0]))
        path = [start]
        prev, cur = None, start
        while True:
            nxts = [q for q in neighbors(cur) if q != prev]
            unvis = [q for q in nxts if q not in set(path)]
            if not unvis:
                break
            nxt = unvis[0]
            prev, cur = cur, nxt
            if cur == start:
                break
            path.append(cur)
        return path, True, max(len(comp) - len(path), 0)
    # 普通段：双 BFS 求直径路径（免疫残留小分叉）
    a0 = tips[0]
    A, _ = bfs(a0)
    B, par = bfs(A)
    path = []
    p = B
    while p is not None:
        path.append(p)
        p = par[p]
    path.reverse()
    return path, False, max(len(comp) - len(path), 0)


def arc_len(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def tip_dir(pts, at_start, k=6):
    """端点朝外单位向量"""
    n = len(pts)
    k = min(k, n - 1)
    if at_start:
        dx, dy = pts[0][0] - pts[k][0], pts[0][1] - pts[k][1]
    else:
        dx, dy = pts[-1][0] - pts[-1 - k][0], pts[-1][1] - pts[-1 - k][1]
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d


def build_segments(sk, deg, nodes, junc_disk, junc_lab, spur_px):
    """挖结点盘 → 连通分量 → 逐段追踪 → 毛刺剔除"""
    seg_mask = (sk & ~junc_disk).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(seg_mask, connectivity=8)
    near = cv2.dilate(junc_disk.astype(np.uint8), ellipse(3)) > 0   # 与结点盘相邻
    junc_near = set(map(tuple, np.column_stack(np.nonzero(near & (lab > 0)))[:, ::-1])) if near.any() else set()
    segs, nspur = [], 0
    for i in range(1, n):
        ys, xs = np.nonzero(lab == i)
        comp = set(zip(xs.tolist(), ys.tolist()))
        pts, closed, dropped = trace_component(comp, deg, junc_near)
        L = arc_len(pts) if len(pts) > 1 else 0.0
        # 端点 → 结点归属（在结点盘标签图的 6px 邻域内查）
        ends = []
        for p, at_start in ((pts[0], True), (pts[-1], False)):
            nid = None
            if not closed:
                x0, y0 = max(p[0] - 6, 0), max(p[1] - 6, 0)
                x1, y1 = min(p[0] + 7, sk.shape[1]), min(p[1] + 7, sk.shape[0])
                sub = junc_lab[y0:y1, x0:x1]
                ids = np.unique(sub[sub > 0])
                if len(ids):
                    nid = int(ids[0]) - 1
            ends.append(nid)
        if not closed and L < spur_px and (ends[0] is None or ends[1] is None):
            nspur += 1
            continue
        segs.append(dict(pts=pts, closed=closed, ends=ends, gaps=[], dropped=dropped,
                         len_px=L))
    return segs, nspur


def bridge_segments(segs, bridge_px):
    """自由端点共线桥接：距离≤bridge_px 且端点朝向互指（夹角<45°）的段并查集合并"""
    cands = []
    for i, s in enumerate(segs):
        if s['closed']:
            continue
        for side in (0, 1):
            if s['ends'][side] is not None:
                continue
            p = s['pts'][0] if side == 0 else s['pts'][-1]
            u = tip_dir(s['pts'], side == 0)
            s.setdefault('free', []).append((side, p, u))
    pool = [(i, side, p, u) for i, s in enumerate(segs) for (side, p, u) in s.get('free', [])]
    COS45 = math.cos(math.radians(45))
    for a in range(len(pool)):
        for b in range(a + 1, len(pool)):
            ia, sa, pa, ua = pool[a]
            ib, sb, pb, ub = pool[b]
            if ia == ib:
                continue
            vx, vy = pb[0] - pa[0], pb[1] - pa[1]
            d = math.hypot(vx, vy)
            if d > bridge_px or d < 1e-6:
                continue
            if (ua[0] * vx + ua[1] * vy) / d < COS45:      # a 的朝向须指向 b
                continue
            if (-ub[0] * vx - ub[1] * vy) / d < COS45:     # b 的朝向须指向 a
                continue
            cands.append((d, ia, sa, ib, sb))
    cands.sort()
    parent = list(range(len(segs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    used = set()
    nbridge = 0
    for d, ia, sa, ib, sb in cands:
        if (ia, sa) in used or (ib, sb) in used:
            continue
        ra, rb = find(ia), find(ib)
        if ra == rb:
            continue
        A, B = segs[ra], segs[rb]
        # 定向：A 的桥接端放到末尾，B 的桥接端放到开头
        if sa == 0:
            A['pts'].reverse(); A['ends'].reverse(); A['free'] = [(1 - s0, p, u) for s0, p, u in A.get('free', [])]
        if sb == 1:
            B['pts'].reverse(); B['ends'].reverse(); B['free'] = [(1 - s0, p, u) for s0, p, u in B.get('free', [])]
        A['gaps'].append([len(A['pts']) - 1, round(d, 1)])
        A['pts'].extend(B['pts'])
        A['ends'][1] = B['ends'][1]
        A['free'] = [f for f in A.get('free', []) if f[0] == 0 and A['ends'][0] is None] + \
                    [f for f in B.get('free', []) if f[0] == 1 and B['ends'][1] is None]
        A['free'] = [(s0, p, u) for s0, p, u in A.get('free', []) if A['ends'][s0] is None]
        A['len_px'] = arc_len(A['pts'])
        A['dropped'] += B['dropped']
        parent[rb] = ra
        used.add((ia, sa)); used.add((ib, sb))
        nbridge += 1
    out = [s for i, s in enumerate(segs) if find(i) == i]
    return out, nbridge


def merge_nodes(nodes, segs, merge_px=30):
    """合并过近结点：粗线交叉处的骨架结点簇常被拆成相距几~二十 px 的多个"结点"，
    真实分区交汇点间距都在 km 级，<30px 必为同一交点。段端归属同步改写到合并后主结点。
    返回合并减少的结点数"""
    parent = list(range(len(nodes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if math.hypot(nodes[i]['x'] - nodes[j]['x'], nodes[i]['y'] - nodes[j]['y']) <= merge_px:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    for i, nd in enumerate(nodes):
        if find(i) == i:
            mem = [j for j in range(len(nodes)) if find(j) == i]
            nd['x'] = float(np.mean([nodes[j]['x'] for j in mem]))
            nd['y'] = float(np.mean([nodes[j]['y'] for j in mem]))
    keepers = [i for i in range(len(nodes)) if find(i) == i]
    remap = {old: new for new, old in enumerate(keepers)}
    n_merged = len(nodes) - len(keepers)
    for s in segs:
        s['ends'] = [remap[find(e)] if e is not None else None for e in s['ends']]
    nodes[:] = [nodes[i] for i in keepers]
    return n_merged


def strip_deadend_nodes(segs, nodes):
    """度=1 的结点是线端 Y 形骨架分叉造成的假结点（如 B28 东端 N27 实际终于省界），
    其唯一引用端改回自由端，供 extend_to_border 处理。返回被拆端数"""
    deg = {}
    for s in segs:
        for e in s['ends']:
            if e is not None:
                deg[e] = deg.get(e, 0) + 1
    dead = {e for e, d in deg.items() if d <= 1}
    n = 0
    for s in segs:
        for side in (0, 1):
            if s['ends'][side] in dead:
                s['ends'][side] = None
                n += 1
    return n


def absorb_free_ends(segs, nodes, absorb_px=100):
    """自由端点就近吸附到结点质心：文字压线断口常恰好在结点旁几十 px（如南山 35px），
    桥接只能连自由端对、够不到结点，故补此步。返回吸附次数"""
    cents = [(nd['x'], nd['y']) for nd in nodes]
    n_abs = 0
    for s in segs:
        if s['closed']:
            continue
        for side in (0, 1):
            if s['ends'][side] is not None:
                continue
            p = s['pts'][0] if side == 0 else s['pts'][-1]
            best, bd = None, absorb_px
            for ni, (nx, ny) in enumerate(cents):
                d = math.hypot(nx - p[0], ny - p[1])
                if d < bd:
                    best, bd = ni, d
            if best is None:
                continue
            q = cents[best]
            if side == 0:
                s['pts'].insert(0, q)
                s['gaps'].insert(0, [0, round(bd, 1)])
            else:
                s['gaps'].append([len(s['pts']) - 1, round(bd, 1)])
                s['pts'].append(q)
            s['ends'][side] = best
            s['len_px'] = arc_len(s['pts'])
            n_abs += 1
    return n_abs


def extend_to_border(segs, poly, max_px=600):
    """剩余自由端点（应都在省界附近）沿端点朝外方向延长到省界多边形边，
    端点标记 border[side]=True；射线 max_px 内未出省界的留作自由端。
    端部走向可能与省界走向接近平行，故在 ±90° 扇形内搜索最短出界射线。
    返回 (延长数, 未达数)"""
    H, W = poly.shape
    n_ext, n_left = 0, 0
    for s in segs:
        if s['closed']:
            continue
        s.setdefault('border', [False, False])
        for side in (0, 1):
            if s['ends'][side] is not None or s['border'][side]:
                continue
            p = s['pts'][0] if side == 0 else s['pts'][-1]
            ux, uy = tip_dir(s['pts'], side == 0, k=12)
            best = None       # (hit, ux, uy)
            for ang in (0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90):
                r = math.radians(ang)
                ca, sa = math.cos(r), math.sin(r)
                vx, vy = ux * ca - uy * sa, ux * sa + uy * ca
                hit = None
                for t in range(2, max_px, 2):
                    qx, qy = int(p[0] + vx * t), int(p[1] + vy * t)
                    if not (0 <= qx < W and 0 <= qy < H):
                        break
                    if not poly[qy, qx]:
                        hit = t
                        break
                if hit is not None and (best is None or hit < best[0]):
                    best = (hit, vx, vy)
                if best is not None and ang == 0:
                    break     # 正向已出界，不必再搜
            if best is None:
                n_left += 1
                continue
            hit, ux2, uy2 = best
            nstep = max(int(hit // 8), 1)
            newpts = [(p[0] + ux2 * hit * k / nstep, p[1] + uy2 * hit * k / nstep)
                      for k in range(1, nstep + 1)]
            if side == 0:
                s['pts'] = newpts[::-1] + s['pts']
                s['gaps'] = [[g[0] + len(newpts), g[1]] for g in s['gaps']]
            else:
                s['pts'].extend(newpts)
            s['border'][side] = True
            s['len_px'] = arc_len(s['pts'])
            n_ext += 1
    return n_ext, n_left


def simplify(pts, epsilon, closed):
    if len(pts) < 5:
        return pts
    arr = np.array(pts, np.float32).reshape(-1, 1, 2)
    out = cv2.approxPolyDP(arr, epsilon, closed)
    return [(float(p[0][0]), float(p[0][1])) for p in out]


def render(im, W, H, segs, nodes, out_prefix, npages=3, scale=0.30):
    pages = []
    step = H // npages
    f_seg, f_node = font(54), font(36)
    for pi in range(npages):
        ya, yb = pi * step, (pi + 1) * step if pi < npages - 1 else H
        crop = im.crop((0, ya, W, yb)).convert('RGB')
        d = ImageDraw.Draw(crop)
        for si, s in enumerate(segs):
            col = PAL[si % len(PAL)]
            pts = [(x, y - ya) for x, y in s['pts'] if ya - 20 <= y < yb + 20]
            if len(pts) >= 2:
                d.line(pts, fill=col, width=8, joint='curve')
            txt = s['id'] + ('·闭' if s['closed'] else '') + ('·接' if s['gaps'] else '')
            npts = len(s['pts'])
            placed = 0
            for ai in (npts // 4, npts // 2, 3 * npts // 4):
                if placed >= 3 or ai >= npts:
                    continue
                ax, ay = s['pts'][ai]
                if not (ya + 10 <= ay < yb - 10):
                    continue
                d.text((ax + 14, ay - ya - 42), txt, fill=(255, 255, 255), font=f_seg)
                d.text((ax + 12, ay - ya - 44), txt, fill=col, font=f_seg)
                placed += 1
        for nd in nodes:
            nx, ny = nd['x'], nd['y'] - ya
            if not (0 <= ny < yb - ya):
                continue
            d.ellipse((nx - 10, ny - 10, nx + 10, ny + 10), fill=col if False else (255, 255, 255),
                      outline=(0, 0, 0), width=3)
            d.text((nx + 14, ny - 40), nd['id'], fill=(255, 255, 255), font=f_node)
            d.text((nx + 12, ny - 42), nd['id'], fill=(0, 0, 0), font=f_node)
        out = '%s_p%d.jpg' % (out_prefix, pi + 1)
        crop.resize((int(W * scale), int((yb - ya) * scale))).save(out, quality=88)
        pages.append(out)
    return pages


def render_debug(im, raw, clean, out_path):
    """原图压暗 + 被剔红像素叠蓝 + 保留粗线叠绿（1/4 缩放）"""
    a = (np.asarray(im.convert('RGB')).astype(np.float32) * 0.55)
    removed = raw & ~clean
    a[removed] = a[removed] * 0.3 + np.array([40, 40, 255], np.float32) * 0.7
    a[clean] = a[clean] * 0.3 + np.array([30, 220, 30], np.float32) * 0.7
    H, W = clean.shape
    Image.fromarray(a.astype(np.uint8)).resize((W // 4, H // 4)).save(out_path, quality=85)


def province_roi(geojson_path, W, H, buffer_px=30, wall_px=10):
    """江西省矢量边界（阿里云 DataV 360000）栅格化 → ROI（含 buffer 外扩）与边界墙。
    返回 (roi 掩膜, 边界墙掩膜, 未外扩省域掩膜)；墙供 --check-zones 作外墙，
    未外扩省域供自由端点延长到省界时判定出界"""
    with open(geojson_path, encoding='utf-8') as f:
        J = json.load(f)
    roi = np.zeros((H, W), np.uint8)
    wall = np.zeros((H, W), np.uint8)
    for feat in J['features']:
        for poly in feat['geometry']['coordinates']:
            rings = [np.array([[CX + (lo - A_LON) * S9, CY + (A_LAT - la) * S9]
                               for lo, la in ring], np.int32) for ring in poly]
            cv2.fillPoly(roi, [rings[0]], 255)
            for hole in rings[1:]:
                cv2.fillPoly(roi, [hole], 0)
            for ring in rings:
                cv2.polylines(wall, [ring], True, 255, thickness=wall_px)
    poly = roi > 0
    if buffer_px > 0:
        roi = cv2.dilate(roi, ellipse(2 * buffer_px + 1))
    return roi > 0, wall > 0, poly


def seg_median_rg(im_arr, pts):
    """段折线沿途最红像素的中位 R-G（橙色公路/褐色等高线 <90，纯红边界 >120）"""
    a = im_arr.astype(np.int16)
    H, W = a.shape[:2]
    cols = []
    for x, y in pts[::5]:
        x, y = int(x), int(y)
        patch = a[max(y - 2, 0):y + 3, max(x - 2, 0):x + 3].reshape(-1, 3)
        i = int(np.argmax(patch[:, 0] - patch[:, 2]))
        cols.append(patch[i, 0] - patch[i, 1])
    return float(np.median(cols)) if cols else 0.0


def filter_segments(segs, roi, im_arr, min_rg=115, stub_km=3.0):
    """剔除误入段：省外段（ROI 内点数<50%）、非纯红段（公路/等高线 R-G<115，
    纯红边界实测 123~190，褐色国道 65~104，橙色高速 ~48）、结点自环小残桩"""
    kept, dropped = [], []
    for s in segs:
        xs = np.clip([int(p[0]) for p in s['pts']], 0, roi.shape[1] - 1)
        ys = np.clip([int(p[1]) for p in s['pts']], 0, roi.shape[0] - 1)
        frac_in = float(roi[ys, xs].mean()) if len(xs) else 0.0
        rg = seg_median_rg(im_arr, s['pts'])
        reason = None
        if frac_in < 0.5:
            reason = '省外（ROI内%.0f%%）' % (frac_in * 100)
        elif rg < min_rg:
            reason = '非纯红（R-G=%.0f）' % rg
        elif (not s['closed'] and s['len_px'] * KM < stub_km
              and s['ends'][0] is not None and s['ends'][0] == s['ends'][1]):
            reason = '结点自环残桩（%.1fkm）' % (s['len_px'] * KM)
        if reason:
            dropped.append((s, reason))
        else:
            kept.append(s)
    return kept, dropped


def check_zones(im, segs, ring, W, H, ray_px=400, poly=None):
    """段折线回画 + 省界圆环为墙 + 自由端点射线补接到墙，洪水填充统计封闭区域数（应≈9）。
    区域质心须落在省域多边形内（排除矢量省界与图面省界不吻合产生的痂片），面积≥100000px"""
    wall = np.zeros((H, W), np.uint8)
    for s in segs:
        pts = np.array(s['pts'], np.int32).reshape(-1, 1, 2)
        cv2.polylines(wall, [pts], s['closed'], 1, thickness=14)
    wall[ring] = 1
    # 自由端点：沿朝外方向投射线，碰到墙则补连线（边界终点接到省界圆环/断口对端）
    for s in segs:
        if s['closed']:
            continue
        for side in (0, 1):
            if s['ends'][side] is not None:
                continue
            p = s['pts'][0] if side == 0 else s['pts'][-1]
            ux, uy = tip_dir(s['pts'], side == 0)
            for t in range(10, ray_px, 2):
                qx, qy = int(p[0] + ux * t), int(p[1] + uy * t)
                if not (0 <= qx < W and 0 <= qy < H):
                    break
                if wall[qy, qx]:
                    cv2.line(wall, (int(p[0]), int(p[1])), (qx, qy), 1, thickness=10)
                    break
    wall = cv2.dilate(wall, ellipse(5))
    ys, xs = np.nonzero(wall)
    x0, x1 = max(xs.min() - 40, 0), min(xs.max() + 40, W)
    y0, y1 = max(ys.min() - 40, 0), min(ys.max() + 40, H)
    sub = wall[y0:y1, x0:x1]
    bg = (1 - sub).astype(np.uint8)
    n, lab, stats, cents = cv2.connectedComponentsWithStats(bg, connectivity=4)
    hh, ww = bg.shape
    regions = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        touches = stats[i, cv2.CC_STAT_LEFT] == 0 or stats[i, cv2.CC_STAT_TOP] == 0 or \
            stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] >= ww or \
            stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] >= hh
        if not touches and area >= 100000:
            cxp, cyp = cents[i]
            gx, gy = int(cxp + x0), int(cyp + y0)
            if poly is not None and not poly[gy, gx]:
                continue                      # 痂片：质心在省域外
            lo, la = px2ll(gx, gy)
            regions.append(dict(area=int(area), center=[round(lo, 3), round(la, 3)]))
    regions.sort(key=lambda r: -r['area'])
    return regions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--atlas', default=DEFAULT_ATLAS)
    ap.add_argument('--sheet-name', default=SHEET)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--open-k', type=int, default=9, help='开运算核（去文字，笔画粗则调大）')
    ap.add_argument('--close-k', type=int, default=5, help='闭运算核（桥接发丝断口）')
    ap.add_argument('--min-area', type=int, default=600)
    ap.add_argument('--junc-dilate', type=int, default=2)
    ap.add_argument('--spur-px', type=float, default=30, help='带自由端的短毛刺剔除阈值')
    ap.add_argument('--bridge-px', type=float, default=80, help='自由端点桥接距离上限')
    ap.add_argument('--absorb-px', type=float, default=100, help='自由端点吸附到结点的距离上限')
    ap.add_argument('--min-rg', type=float, default=115, help='纯红判定下限 R-G（国道/高速 <115）')
    ap.add_argument('--epsilon', type=float, default=4.0, help='抽稀容差 px（≈0.4km）')
    ap.add_argument('--pages', type=int, default=3)
    ap.add_argument('--jx-geo', default=os.path.join(DEFAULT_CACHE, 'jiangxi_360000.json'),
                    help='江西省界 GeoJSON（阿里云 DataV 360000），用于省内 ROI 过滤与自检外墙')
    ap.add_argument('--check-zones', action='store_true', help='封闭区域数自检（应≈9）')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    path = os.path.join(a.atlas, a.sheet_name)
    im = Image.open(path).convert('RGB')
    W, H = im.size
    print('图幅 %s  %d×%d' % (a.sheet_name, W, H))
    raw = red_mask(path)
    clean, ndrop = clean_mask(raw, W, H, a.open_k, a.close_k, a.min_area)
    print('红像素 %d → 粗线掩膜 %d（面积过滤剔小组件 %d 个）' % (raw.sum(), clean.sum(), ndrop))
    dbg = os.path.join(a.out_dir, 'zones_产流_debug.jpg')
    render_debug(im, raw, clean, dbg)

    from skimage.morphology import skeletonize
    sk = skeletonize(clean)
    deg = degree_map(sk)
    nodes, junc_disk, junc_lab = find_nodes(sk, deg, a.junc_dilate)
    segs, nspur = build_segments(sk, deg, nodes, junc_disk, junc_lab, a.spur_px)
    nfree0 = sum(1 for s in segs for e in s['ends'] if e is None and not s['closed'])
    segs, nbridge = bridge_segments(segs, a.bridge_px)
    n_nmerge = merge_nodes(nodes, segs)
    n_abs = absorb_free_ends(segs, nodes, a.absorb_px)
    print('骨架像素 %d  结点 %d  段 %d（剔毛刺 %d，桥接 %d 次，并结点 %d，吸附结点 %d 端，桥接前自由端 %d）'
          % (int(sk.sum()), len(nodes), len(segs), nspur, nbridge, n_nmerge, n_abs, nfree0))

    # 省界 ROI 过滤：剔除省外大字/公路/等高线等误入段
    im_arr = np.asarray(im)
    roi, ring, poly = province_roi(a.jx_geo, W, H)
    segs, filtered = filter_segments(segs, roi, im_arr, min_rg=a.min_rg)
    for s, why in filtered:
        xs = [p[0] for p in s['pts']]; ys = [p[1] for p in s['pts']]
        lo, la = px2ll((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        print('  剔除误入段：中心(%.2fE,%.2fN) 长%.1fkm  原因=%s' % (lo, la, s['len_px'] * KM, why))
    # 度=1 假结点拆回自由端（如 B28 东端实际终于省界），供后续省界延长
    n_strip = strip_deadend_nodes(segs, nodes)
    # 回收不再被引用的结点
    used_n = sorted({e for s in segs for e in s['ends'] if e is not None})
    remap = {old: new for new, old in enumerate(used_n)}
    nodes = [nodes[i] for i in used_n]
    for s in segs:
        s['ends'] = [remap[e] if e is not None else None for e in s['ends']]
    print('过滤后：段 %d，结点 %d（假结点拆回自由端 %d）' % (len(segs), len(nodes), n_strip))

    # 剩余自由端点延长到省界（分区边界必终于省界或结点；实测各自由端距省界均 <10km）
    n_ext, n_left = extend_to_border(segs, poly)
    print('省界延长：%d 端接到省界，%d 端未达（留自由端）' % (n_ext, n_left))

    # 端点延伸到结点质心 + 抽稀 + 编号
    for s in segs:
        for side in (0, 1):
            nid = s['ends'][side]
            if nid is not None:
                p = (nodes[nid]['x'], nodes[nid]['y'])
                if side == 0:
                    s['pts'].insert(0, p)
                else:
                    s['pts'].append(p)
        s['pts_raw_n'] = len(s['pts'])
        s['pts'] = simplify(s['pts'], a.epsilon, s['closed'])
    segs.sort(key=lambda s: (min(p[1] for p in s['pts']) // 500, min(p[0] for p in s['pts'])))
    for i, s in enumerate(segs, 1):
        s['id'] = 'B%d' % i
    nmap = {}
    norder = sorted(range(len(nodes)), key=lambda i: (nodes[i]['y'] // 500, nodes[i]['x']))
    for k, i in enumerate(norder, 1):
        nodes[i]['id'] = 'N%d' % k
        nmap[i] = 'N%d' % k
    nodes_out = [nd for nd in (dict(id=nodes[i]['id'], x=round(nodes[i]['x'], 1), y=round(nodes[i]['y'], 1),
                                    lon=round(px2ll(nodes[i]['x'], nodes[i]['y'])[0], 4),
                                    lat=round(px2ll(nodes[i]['x'], nodes[i]['y'])[1], 4)) for i in range(len(nodes)))]
    nodes_out.sort(key=lambda nd: int(nd['id'][1:]))

    segs_out = []
    for s in segs:
        xs = [p[0] for p in s['pts']]; ys = [p[1] for p in s['pts']]
        ll = [px2ll(x, y) for x, y in s['pts']]
        eps = []
        for side in (0, 1):
            x, y = (s['pts'][0] if side == 0 else s['pts'][-1])
            lo, la = px2ll(x, y)
            eps.append(dict(x=round(x, 1), y=round(y, 1), lon=round(lo, 4), lat=round(la, 4),
                            node=(nmap.get(s['ends'][side]) if s['ends'][side] is not None else None),
                            border=bool(s.get('border', [False, False])[side])))
        segs_out.append(dict(id=s['id'], closed=s['closed'],
                             len_px=round(s['len_px'], 1), len_km=round(s['len_px'] * KM, 1),
                             n_points_raw=s['pts_raw_n'], n_points=len(s['pts']),
                             endpoints=eps, gaps=s['gaps'],
                             dropped_px=s['dropped'],
                             bbox=[round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
                             polyline_px=[[round(x, 1), round(y, 1)] for x, y in s['pts']],
                             polyline_lonlat=[[round(lo, 4), round(la, 4)] for lo, la in ll]))
    warn = [s['id'] for s in segs if s['dropped'] > 50]
    if warn:
        print('警告：以下段追踪丢弃像素>50（可能有残留分叉，请核对校核图）: %s' % ','.join(warn))

    prefix = os.path.join(a.out_dir, 'zones_产流')
    pages = render(im, W, H, segs, [nodes[i] for i in range(len(nodes)) if 'id' in nodes[i]],
                   prefix, a.pages)
    result = dict(sheet=a.sheet_name, image=dict(w=W, h=H),
                  calib=dict(cx=CX, cy=CY, s=S9, anchor=dict(lon=A_LON, lat=A_LAT),
                             note='lon=115.88+(x-cx)/s ; lat=28.68-(y-cy)/s'),
                  params=dict(open_k=a.open_k, close_k=a.close_k, min_area=a.min_area,
                              junc_dilate=a.junc_dilate, spur_px=a.spur_px,
                              bridge_px=a.bridge_px, absorb_px=a.absorb_px,
                              min_rg=a.min_rg, epsilon_px=a.epsilon),
                  n_segments=len(segs_out), n_nodes=len(nodes_out),
                  nodes=nodes_out, segments=segs_out,
                  dropped=dict(spur=nspur, small_components=ndrop, bridged=nbridge,
                               absorbed=n_abs, border_extended=n_ext, filtered=len(filtered)),
                  debug=dbg, pages=pages)
    if a.check_zones:
        regions = check_zones(im, segs, ring, W, H, poly=poly)
        result['check_zones'] = dict(n_regions=len(regions), expect=9, regions=regions)
        print('封闭区域自检：%d 个（期望≈9）' % len(regions))
        for r in regions:
            print('  面积 %9d px  中心 %s' % (r['area'], r['center']))
    jp = prefix + '.json'
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print('JSON: %s\n校核图: %s\ndebug: %s' % (jp, ', '.join(pages), dbg))


if __name__ == '__main__':
    main()
