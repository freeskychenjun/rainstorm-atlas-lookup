# -*- coding: utf-8 -*-
"""
江西省暴雨洪水查算手册图集 —— 按经纬度/KML 查暴雨参数/分区参数
用法（详见 SKILL.md）:
  裁剪图（读图复核用）:
    python lookup.py --lon 115.88 --lat 28.68 --name 南昌 --out-dir D:\\out
    python lookup.py --kml C:\\points.kml --out-dir D:\\out        # 支持多点位
  正式报告（两种取值来源）:
    python lookup.py --kml ... --out-dir ... --from-auto values.json   # auto_value 输出自动填值（推荐草稿）
    python lookup.py --kml ... --out-dir ... --values-file values.json # 人工定稿 values.json
values.json:
  单点位: {"1h": {"Pa":..,"Pa_s":..,"Pa_q":..,"Cv":..,"Cv_s":..,"Cv_q":..}, ..., "zones": {...}, "summary": ".."}
  多点位: {"points": {"点名": {同上}}, "summary": ".."}   （缺省点位键时按第一个点处理）
"""
import argparse, base64, hashlib, json, os, re, sys
import html as _html
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

# 配准常数/坐标换算的单一来源在 registry.py（勿在本文件另立常数）
from registry import (resolve_atlas, stat_xy, part_xy, out_of_bounds,
                      STAT_SHEETS, PART_SHEETS, STAT_KEYS, STAT_FILE,
                      S_STAT, S9, STAT_BASE, SKILL_ROOT)

# 兼容旧引用（query_atlas / trace_line / annotate_lines 等从 lookup 导入这些名字）
DEFAULT_ATLAS = resolve_atlas()
DEFAULT_CACHE = os.path.join(SKILL_ROOT, 'cache')
DURATIONS = ["1h", "6h", "24h", "3d"]

def rich(s):
    """把文本里的警示内容渲染为红色粗体。
    用法一（显式）：用 **...** 包住警示文字；
    用法二（兜底）：未显式标记时，含警示关键词的分句自动标红。
    """
    if not s:
        return s
    t = _html.escape(str(s))
    t = re.sub(r'\*\*(.+?)\*\*', r'<b class="warn">\1</b>', t)
    if '<b class="warn">' not in t:
        segs = re.split(r'(?<=[；;。])', t)
        t = ''.join('<b class="warn">%s</b>' % seg if any(w in seg for w in WARN_WORDS) else seg
                    for seg in segs)
    return t


WARN_WORDS = ('极远', '较远', '不确定度大', '不确定度较大', '不确定度略大', '不确定度偏大',
              '必须人工复核', '建议人工复核', '需人工复核', '以最近线为准', '以最近线值为准',
              '不可靠', '同侧双线', '改取反方向')


def crop_mark(im, cx, cy, r=2000, out_size=1700):
    """裁剪定位图：覆盖点位周边 ±r 原图像素（r=2000 ≡ ±190 km），再缩到 out_size 见方。
    HTML 里图片按容器宽度自适应，屏上可见的地理范围由 r 决定（r 加倍 = 内容缩小一半）；
    out_size 只决定放大查看时的清晰度。"""
    x0, y0 = max(cx - r, 0), max(cy - r, 0)
    x1, y1 = min(cx + r, im.size[0]), min(cy + r, im.size[1])
    c = im.crop((x0, y0, x1, y1)).convert("RGB")
    px, py = cx - x0, cy - y0
    d = ImageDraw.Draw(c)
    d.line((px - 50, py, px + 50, py), fill=(0, 190, 0), width=6)
    d.line((px, py - 50, px, py + 50), fill=(0, 190, 0), width=6)
    return c.resize((out_size, out_size))

def img_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def parse_kml(path):
    """返回 [(name, lon, lat, src), ...]，src ∈ {"point", "polygon-centroid"}。

    兼容 kml/2.2 命名空间。每个 Placemark 取第一个 Point 坐标；无 Point 时
    取第一个 Polygon（外环第一个 coordinates，即外边界）的几何中心——
    水库/工程 KML 常为面要素，质心仅代表面中心，报告会注明。
    """
    tree = ET.parse(path)
    root = tree.getroot()
    uri = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
    def q(tag):
        return "{%s}%s" % (uri, tag) if uri else tag

    def coords_of(el):
        txt = (el.text or "").strip()
        out = []
        for line in re.split(r"\s+", txt):
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    out.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass
        return out

    pts = []
    for pm in root.iter(q("Placemark")):
        name = (pm.findtext(q("name")) or "未命名").strip()
        p = pm.find(q("Point"))
        co = p.find(q("coordinates")) if p is not None else None
        if co is not None and coords_of(co):
            lon, lat = coords_of(co)[0]
            if 113.0 < lon < 119.0 and 24.0 < lat < 31.0:
                pts.append((name, lon, lat, "point"))
            continue
        # 面要素：取第一个 Polygon 的外环坐标求几何中心（文档顺序中外环在前）
        poly = next((el for el in pm.iter() if el.tag == q("Polygon")), None)
        if poly is not None:
            ring = next((c for c in poly.iter(q("coordinates"))), None)
            cs = coords_of(ring) if ring is not None else []
            if cs:
                lon = sum(c[0] for c in cs) / len(cs)
                lat = sum(c[1] for c in cs) / len(cs)
                if 113.0 < lon < 119.0 and 24.0 < lat < 31.0:
                    pts.append((name, lon, lat, "polygon-centroid"))
    # 去重（同名同坐标）
    seen, out = set(), []
    for n, lo, la, src in pts:
        key = (n, round(lo, 6), round(la, 6))
        if key not in seen:
            seen.add(key)
            out.append((n, lo, la, src))
    return out

def safe(s):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s) or "pt"


def _file_md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def data_stamp():
    """线值库/几何缓存指纹（报告可追溯用：回答"当时用的哪版数据"）。"""
    import time as _t
    try:
        h, n = hashlib.md5(), 0
        for k in STAT_KEYS:
            p = os.path.join(DEFAULT_CACHE, 'manual_labels_v2', k + '_lines.json')
            h.update(_file_md5(p).encode())
            n += len(json.load(open(p, encoding='utf-8')))
        g = hashlib.md5()
        for k in STAT_KEYS:
            gp = os.path.join(DEFAULT_CACHE, 'geometry', k + '.npz')
            if os.path.isfile(gp):
                g.update(_file_md5(gp).encode())
        return '生成 %s · 线值库 v2（%d 条人工确认，指纹 %s）· 几何缓存 %s' % (
            _t.strftime('%Y-%m-%d %H:%M'), n, h.hexdigest()[:8], g.hexdigest()[:8])
    except Exception:
        return '生成 %s · 数据指纹不可用' % _t.strftime('%Y-%m-%d %H:%M')


def values_from_auto(auto):
    """auto_value 输出 JSON → 报告 values.json 结构（草稿自动填值）。

    填值规则（与人工口径一致，见 SKILL.md）：
      Pa = 距离加权内插值（mm 取整）；Cv = 内插值（2 位小数）；
      建议采用值(_s) = 内插值向大值方向抬 1/4 等值线间隔，不越过夹持区间的大值线
        （"抬 1/5~1/4 档、不越半档"，内插位置越靠近大值线，上抬余量越小）；
      取值依据(_q) = 线号/线值/距离/方位自动成文，warning 原文附后（模板按关键词标红）。
    """
    def one(av):
        val, warns = {'zones': {}}, []
        for du in DURATIONS:
            d = {}
            for metric in ('Pa', 'Cv'):
                ent = (av.get('values') or {}).get('%s-%s' % (du, metric))
                if not ent:
                    continue
                near = ent['nearest']
                v = ent.get('interpolated', near['value'])
                opp = ent.get('opposite')
                if opp:
                    hi = max(near['value'], opp['value'])
                    step = abs(opp['value'] - near['value'])
                    sug = min(v + 0.25 * step, hi)
                    q = ('距 %g 线 %.1f km（方位 %s°），对侧 %g 线 %.1f km（方位 %s°），'
                         '距离加权内插；线号 %s/%s'
                         % (near['value'], near['km'], near['azimuth'],
                            opp['value'], opp['km'], opp['azimuth'], near['id'], opp['id']))
                else:
                    sug = v
                    q = ('最近 %g 线 %.1f km（方位 %s°），无对侧线，暂取最近线值；线号 %s'
                         % (near['value'], near['km'], near['azimuth'], near['id']))
                if ent.get('warning'):
                    q += '；' + ent['warning']
                    warns.append('%s-%s：%s' % (du, metric, ent['warning']))
                if metric == 'Pa':
                    v, sug = int(round(v)), int(round(sug))
                else:
                    v, sug = round(v, 2), round(sug, 2)
                d[metric], d[metric + '_s'], d[metric + '_q'] = v, sug, q
            if d:
                val[du] = d
        zone = av.get('zone')
        val['zones']['产流'] = zone or ''
        if av.get('zone_warning'):
            warns.append('产流分区：' + av['zone_warning'])
        seg = '、'.join('%s Pa %s→%s mm、Cv %s→%s'
                        % (du, val[du]['Pa'], val[du]['Pa_s'], val[du]['Cv'], val[du]['Cv_s'])
                        for du in DURATIONS if du in val)
        summary = ('（机器初值草稿，复核 warning 项后定稿）本工程点位于产流分区第 %s 区'
                   '（三张分区图同号）；%s。箭头后为建议采用值（偏安全：内插值向大值方向'
                   '抬约 1/4 等值线间隔，不越夹持区间大值线）。' % (zone or '?', seg))
        if warns:
            summary += '**以下 %d 项须人工对图复核：%s**' % (len(warns), '；'.join(warns))
        val['summary'] = summary
        return val

    if isinstance(auto.get('points'), dict):
        # 多点位：不给顶层 summary，各点块用自己的结论（含各自 warning），逐点展示
        return {'points': {k: one(v) for k, v in auto['points'].items()}}
    return one(auto)

def gen_crops(lon, lat, sub, atlas, all_zones=False):
    """生成单点裁剪图（8 幅统计图 + 默认 1 幅产流分区图），返回 [(key, title, path)]"""
    crops = []
    for fn, title in STAT_SHEETS:
        im = Image.open(os.path.join(atlas, fn))
        cx, cy = stat_xy(lon, lat, *im.size)
        key = fn.split("--")[1].replace(".jpg", "")
        p = os.path.join(sub, key + ".jpg")
        crop_mark(im, cx, cy).save(p, quality=85)
        crops.append((key, title, p))
    for fn, title, cx, cy, primary in PART_SHEETS:
        if not primary and not all_zones:
            continue
        im = Image.open(os.path.join(atlas, fn))
        px, py = part_xy(lon, lat, cx, cy)
        key = "zone-" + title[:2]
        p = os.path.join(sub, key + ".jpg")
        crop_mark(im, px, py).save(p, quality=85)
        crops.append((key, title + "（只判读区号）", p))
    return crops

DUR_LABEL = {"1h": "历时 1 小时", "6h": "历时 6 小时", "24h": "历时 24 小时", "3d": "历时 3 天"}
PLATE_LABEL = {"Pa": "点暴雨均值 Pa", "Cv": "变差系数 Cv"}

def fmt_num(v, metric):
    if v in ("", None):
        return "—"
    return f"{v}" if metric == "Cv" else f"{v}"


ROMAN = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
         "Ⅵ": "VI", "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX"}

def roman_disp(v):
    """罗马数字用 ASCII 显示，避免部分字体缺 U+2160~ 字形"""
    return ROMAN.get(v, v)


def point_section(name, lon, lat, val, crops, summary="", src="point"):
    val = val or {}
    # 多点报告无全局结论时，回退用该点自己的 summary（from-auto 草稿把该点 warning 写进点内 summary）
    summary = summary or val.get("summary", "")
    z = val.get("zones", {})
    z_main = z.get("产流", "")
    zones = [(k, z.get(k) or z_main) for k in ["产流", "瞬时", "推理"]]
    zone_names = [("产流计算分区", "产流参数"), ("瞬时单位线分区", "m₁ / K 参数"), ("推理公式计算分区", "汇流参数")]
    src_row = ('<div class="tb-row"><span class="tb-k">点位来源</span>'
               '<span class="tb-v">KML 面要素 · 取几何中心查值</span></div>') \
        if src == "polygon-centroid" else ""

    # ---- 参数卡：每个历时一张，Pa / Cv 两栏 ----
    cards = []
    for i, du in enumerate(DURATIONS):
        d = val.get(du, {})
        metrics = ""
        for mi, metric in enumerate(["Pa", "Cv"]):
            v, vs = d.get(metric, ""), d.get(metric + "_s", "")
            unit = "mm" if metric == "Pa" else ""
            basis = d.get(metric + "_q", "") or "（未填写依据）"
            metrics += f"""
      <div class="metric">
        <div class="metric-name">{'点暴雨均值' if metric == 'Pa' else '变差系数'} <em>{metric}</em></div>
        <div class="metric-vals">
          <span class="v">{fmt_num(v, metric)}</span><span class="unit">{unit}</span>
          <span class="arrow">→</span>
          <span class="vs">{fmt_num(vs, metric)}</span><span class="unit">{unit}</span>
        </div>
        <div class="metric-tag">建议采用（偏安全）</div>
        <p class="basis">{rich(basis)}</p>
      </div>"""
        cards.append(f"""
    <article class="spec" style="--i:{i}">
      <header class="spec-head">
        <span class="dur">{du}</span>
        <span class="dur-sub">{DUR_LABEL.get(du, '')}</span>
      </header>{metrics}
    </article>""")

    # ---- 分区条 ----
    zone_cells = "".join(f"""
      <div class="zone">
        <span class="zone-no">{roman_disp(v) or '—'}</span>
        <span class="zone-name">{zone_names[i][0]}</span>
        <span class="zone-use">{zone_names[i][1]}</span>
      </div>""" for i, (k, v) in enumerate(zones))

    # ---- 图版：每幅裁剪图一块，图上方为该幅取值与依据 ----
    plates = []
    for i, (key, title, p) in enumerate(crops):
        if key.startswith("zone"):
            head_val = f"第 {roman_disp(z_main)} 区" if z_main else "—"
            basis = (f"产流分区号 {z_main}；三张分区图（产流 / 瞬时单位线 / 推理公式）分区号一致，故三列同值"
                     if z_main else "（未判读）")
            name_html = title.replace("（只判读区号）", "")
            unit_html = ""
        else:
            du, metric = key.split("-")
            d = val.get(du, {})
            v, vs = d.get(metric, ""), d.get(metric + "_s", "")
            unit = "mm" if metric == "Pa" else ""
            head_val = f"{fmt_num(v, metric)} {unit}".strip()
            basis = d.get(metric + "_q", "") or "（未填写依据）"
            name_html = f"{du} {PLATE_LABEL.get(metric, metric)}"
            unit_html = f"<span class='plate-alt'>建议采用 {fmt_num(vs, metric)} {unit}</span>"
        plates.append(f"""
    <article class="plate" style="--i:{i}">
      <div class="plate-head">
        <span class="plate-no">图版 {i + 1:02d}</span>
        <h3>{name_html}</h3>
        <span class="plate-val">{head_val}{unit_html}</span>
      </div>
      <p class="basis"><b>取值依据（等值线）</b>{rich(basis)}</p>
      <figure class="plate-fig">
        <img src="data:image/jpeg;base64,{img_b64(p)}" alt="{name_html} 定位裁剪图">
        <figcaption><span class="cross">✛</span> 绿十字 = 查图点位　·　图幅 1:150 万　·　点位周边 ±190 km</figcaption>
      </figure>
    </article>""")

    conclusion = ""
    if summary:
        conclusion = f"""
    <div class="sec-head"><span class="sec-no">04</span><h2>综合结论</h2><span class="sec-rule"></span>
      <span class="sec-hint">供设计直接引用</span></div>
    <p class="summary-text">{rich(summary)}</p>"""

    return f"""
  <section class="point-block">
    <div class="titleblock">
      <div class="tb-row"><span class="tb-k">查图点位</span><span class="tb-v strong">{name or '未命名'}</span></div>
      {src_row}<div class="tb-row"><span class="tb-k">经度 λ</span><span class="tb-v mono">{lon:.4f}° E</span></div>
      <div class="tb-row"><span class="tb-k">纬度 φ</span><span class="tb-v mono">{lat:.4f}° N</span></div>
      <div class="tb-row"><span class="tb-k">投影配准</span><span class="tb-v mono">1162 px/°　误差 &lt; 2 km</span></div>
      <div class="tb-row"><span class="tb-k">读值口径</span><span class="tb-v">等值线标签内插，测站值不参与定值</span></div>
      <div class="tb-row"><span class="tb-k">偏安全</span><span class="tb-v">向大值方向抬 1/5~1/4 档，不越半档</span></div>
    </div>

    <div class="sec-head"><span class="sec-no">01</span><h2>暴雨参数查值成果</h2><span class="sec-rule"></span>
      <span class="sec-hint">左＝内插值　右＝建议采用值</span></div>
    <div class="spec-grid">{''.join(cards)}</div>

    <div class="sec-head"><span class="sec-no">02</span><h2>产汇流分区</h2><span class="sec-rule"></span>
      <span class="sec-hint">三张分区图分区号一致</span></div>
    <div class="zone-strip">{zone_cells}</div>

    <div class="sec-head"><span class="sec-no">03</span><h2>定位裁剪图版</h2><span class="sec-rule"></span>
      <span class="sec-hint">逐幅对图复核</span></div>
    <div class="plates">{''.join(plates)}</div>
{conclusion}  </section>"""


HTML_HEAD = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>暴雨参数查值报告 __TAG__</title>
<style>
:root{
  --paper:#f4f1e9; --paper-2:#ece7db; --ink:#101a22; --ink-soft:#3f4d58; --ink-mid:#2c3944;
  --red:#a81b17; --red-2:#8d1512; --blue:#3a6480; --rule:rgba(16,26,34,.24);
  --rule-soft:rgba(16,26,34,.12);
  --display:"Bahnschrift SemiCondensed","Bahnschrift","汉仪中黑 197","Noto Sans SC Medium",sans-serif;
  --head:"Noto Sans SC Medium","Noto Sans SC","等线",sans-serif;
  --body:"Noto Sans SC","Microsoft YaHei UI","等线",sans-serif;
  --mono:"JetBrainsMono NF","Cascadia Mono",Consolas,"Courier New",monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; padding:0 0 72px; color:var(--ink); background:var(--paper);
  font-family:var(--body); font-weight:400; font-size:15.5px; line-height:1.75;
  background-image:
    linear-gradient(rgba(16,26,34,.05) 1px,transparent 1px),
    linear-gradient(90deg,rgba(16,26,34,.05) 1px,transparent 1px),
    radial-gradient(circle at 12% 8%,rgba(168,27,23,.05),transparent 45%),
    radial-gradient(circle at 88% 4%,rgba(58,100,128,.07),transparent 42%);
  background-size:40px 40px,40px 40px,100% 100%,100% 100%;
}
.grain{position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.5;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2'/><feColorMatrix type='saturate' values='0'/></filter><rect width='160' height='160' filter='url(%23n)' opacity='.055'/></svg>")}
.wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:0 28px}

/* ---------- 报头 ---------- */
.masthead{padding:52px 0 26px;border-bottom:2px solid var(--ink);position:relative;overflow:hidden}
.masthead .contours{position:absolute;right:-40px;top:-30px;width:520px;height:230px;opacity:.5;pointer-events:none}
.masthead .contours path{fill:none;stroke:var(--red);stroke-width:1.4;stroke-dasharray:6 5;opacity:.55;
  animation:trace 26s linear infinite}
.masthead .contours path:nth-child(2){stroke:var(--blue);animation-duration:34s;opacity:.45}
.masthead .contours path:nth-child(3){animation-duration:44s;opacity:.35}
@keyframes trace{to{stroke-dashoffset:-560}}
.eyebrow{font-family:var(--display);letter-spacing:.34em;text-transform:uppercase;font-size:11.5px;
  color:var(--red);margin:0 0 14px}
.masthead h1{font-family:var(--head);font-weight:500;font-size:clamp(26px,3.6vw,42px);line-height:1.18;
  margin:0;letter-spacing:.01em}
.masthead h1 small{display:block;font-family:var(--display);font-weight:400;font-size:clamp(14px,1.5vw,19px);
  letter-spacing:.22em;color:var(--ink-soft);margin-top:12px;text-transform:uppercase}
.masthead .lede{margin:20px 0 0;max-width:74ch;color:var(--ink-mid);font-size:15px}
.masthead .lede b{color:var(--ink);font-weight:500}

/* ---------- 点位块 ---------- */
.point-block{animation:rise .7s cubic-bezier(.2,.7,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.titleblock{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:0;
  margin:34px 0 10px;border:1px solid var(--rule);background:linear-gradient(180deg,rgba(255,255,255,.66),rgba(255,255,255,.28))}
.tb-row{display:flex;gap:12px;align-items:baseline;justify-content:space-between;
  padding:11px 16px;border-bottom:1px solid var(--rule-soft);border-right:1px solid var(--rule-soft)}
.tb-row:last-child{border-right:none}
.tb-k{font-family:var(--display);letter-spacing:.16em;font-size:11.5px;color:var(--ink-mid);
  text-transform:uppercase;white-space:nowrap;font-weight:600}
.tb-v{font-size:14px;text-align:right;color:var(--ink);font-weight:400}
.tb-v.strong{font-family:var(--head);font-weight:500;font-size:17px}
.mono{font-family:var(--mono);font-size:12.5px;font-variant-numeric:tabular-nums}

/* ---------- 节标题 ---------- */
.sec-head{display:flex;align-items:baseline;gap:16px;margin:46px 0 18px;position:relative}
.sec-no{font-family:var(--mono);font-weight:500;font-size:46px;line-height:.9;color:rgba(176,32,28,.26);
  letter-spacing:.02em}
.sec-head h2{font-family:var(--head);font-weight:500;font-size:20px;margin:0;letter-spacing:.04em}
.sec-rule{flex:1;height:1px;background:var(--rule);transform:translateY(-6px)}
.sec-hint{font-family:var(--display);font-size:11.5px;letter-spacing:.18em;color:var(--ink-mid);
  text-transform:uppercase;transform:translateY(-6px);white-space:nowrap;font-weight:600}

/* ---------- 参数卡 ---------- */
.spec-grid{display:grid;gap:18px}
.spec{display:grid;grid-template-columns:96px 1fr 1fr;gap:0;border:1px solid var(--rule);
  background:rgba(255,255,255,.55);animation:rise .7s cubic-bezier(.2,.7,.2,1) both;
  animation-delay:calc(var(--i) * 90ms)}
.spec-head{display:flex;flex-direction:column;justify-content:center;gap:6px;padding:18px 14px;
  border-right:1px solid var(--rule);background:linear-gradient(180deg,rgba(176,32,28,.06),transparent)}
.spec-head .dur{font-family:var(--display);font-weight:600;font-size:30px;letter-spacing:.02em;line-height:1}
.spec-head .dur-sub{font-size:11.5px;color:var(--ink-mid);letter-spacing:.08em;font-weight:500}
.metric{padding:18px 20px;border-right:1px solid var(--rule-soft)}
.metric:last-child{border-right:none}
.metric-name{font-size:13px;letter-spacing:.06em;color:var(--ink-mid);font-weight:500}
.metric-name em{font-family:var(--mono);font-style:normal;color:var(--red);font-size:12.5px;letter-spacing:.04em}
.metric-vals{display:flex;align-items:baseline;gap:6px;margin:6px 0 2px}
.metric-vals .v{font-family:var(--mono);font-size:29px;font-weight:600;font-variant-numeric:tabular-nums}
.metric-vals .unit{font-size:12.5px;color:var(--ink-mid);font-weight:500}
.metric-vals .arrow{color:var(--rule);font-size:18px;margin:0 4px}
.metric-vals .vs{font-family:var(--mono);font-size:29px;font-weight:700;color:var(--red);
  font-variant-numeric:tabular-nums}
.metric-tag{font-family:var(--display);font-size:11px;letter-spacing:.16em;color:var(--red);
  text-transform:uppercase;margin-bottom:8px;font-weight:600}
.basis{font-size:13.5px;line-height:1.72;color:var(--ink-mid);margin:8px 0 0;font-weight:400;
  padding-left:12px;border-left:2.5px solid rgba(168,27,23,.45)}
.basis b{display:block;color:var(--red);font-weight:600;font-size:11.5px;letter-spacing:.1em;
  font-family:var(--display);text-transform:uppercase;margin-bottom:4px}

/* ---------- 分区 ---------- */
.zone-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:18px}
.zone{border:1px solid var(--rule);background:rgba(255,255,255,.55);padding:20px 22px;
  display:grid;gap:2px;position:relative;overflow:hidden}
.zone::after{content:"";position:absolute;right:-30px;bottom:-30px;width:110px;height:110px;
  border:1px solid rgba(58,100,128,.18);border-radius:50%}
.zone-no{font-family:"Constantia",Georgia,"Times New Roman",serif;font-weight:600;font-size:44px;
  line-height:1;letter-spacing:.04em;color:var(--ink)}
.zone-name{font-family:var(--head);font-size:15px;font-weight:500}
.zone-use{font-size:12.5px;color:var(--ink-mid);letter-spacing:.06em;font-weight:400}

/* ---------- 图版 ---------- */
.plates{display:grid;gap:34px}
.plate{border:1px solid var(--rule);background:rgba(255,255,255,.5);padding:20px 20px 14px;
  animation:rise .7s cubic-bezier(.2,.7,.2,1) both;animation-delay:calc(var(--i) * 70ms)}
.plate-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid var(--rule);padding-bottom:10px}
.plate-no{font-family:var(--mono);font-size:12.5px;letter-spacing:.14em;color:var(--red);font-weight:600}
.plate-head h3{font-family:var(--head);font-weight:500;font-size:18px;margin:0;flex:1}
.plate-val{font-family:var(--mono);font-size:21px;font-weight:700;font-variant-numeric:tabular-nums}
.plate-alt{font-family:var(--body);font-size:12.5px;font-weight:500;color:var(--ink-mid);
  margin-left:10px;letter-spacing:.04em}
.plate .basis{margin:12px 0 14px}
.summary-text{
  font-size:15.5px;line-height:1.95;color:var(--ink);margin:14px 0 6px;
  padding:18px 22px;background:var(--paper-2);border-left:3px solid var(--red);
  border-radius:0 8px 8px 0;
}
.warn{color:var(--red);font-weight:700;font-style:normal}
.plate-fig{margin:0}
.plate-fig img{display:block;width:100%;height:auto;border:1px solid var(--rule);
  transition:transform .5s cubic-bezier(.2,.7,.2,1),box-shadow .5s}
.plate-fig img:hover{transform:translateY(-3px);box-shadow:0 14px 34px rgba(23,34,44,.16)}
.plate-fig figcaption{font-size:12.5px;color:var(--ink-mid);letter-spacing:.05em;margin-top:9px;font-weight:400;
  display:flex;gap:8px;align-items:center}
.plate-fig .cross{color:var(--red);font-size:14px}

/* ---------- 页脚 ---------- */
.colophon{margin-top:56px;border-top:2px solid var(--ink);padding-top:18px;
  display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;
  font-size:12px;color:var(--ink-mid);letter-spacing:.06em;font-family:var(--display);
  text-transform:uppercase;font-weight:600}

@media (max-width:860px){
  .spec{grid-template-columns:1fr}
  .spec-head{flex-direction:row;align-items:baseline;gap:12px;border-right:none;
    border-bottom:1px solid var(--rule)}
  .metric{border-right:none;border-bottom:1px solid var(--rule-soft)}
  .sec-no{font-size:40px}
}
@media print{
  body{background:#fff}
  .grain,.masthead .contours{display:none}
  .plate,.spec,.zone{break-inside:avoid;background:#fff}
  .plate-fig img:hover{transform:none;box-shadow:none}
}
</style></head><body>
<div class="grain"></div>
<div class="wrap">
  <header class="masthead">
    <svg class="contours" viewBox="0 0 520 230" aria-hidden="true">
      <path d="M-10 190 C 90 150 150 200 240 160 S 420 110 540 140"/>
      <path d="M-10 150 C 110 100 190 160 300 118 S 460 70 540 96"/>
      <path d="M-10 108 C 120 62 240 118 330 78 S 470 34 540 52"/>
    </svg>
    <p class="eyebrow">附图 2-1 ~ 2-8 &nbsp;·&nbsp; 3-1 / 3-2 / 4-2 &nbsp;·&nbsp; 1 : 1 500 000</p>
    <h1>江西省暴雨洪水查算手册图集<small>Rainstorm Parameter Lookup · 暴雨参数查值报告</small></h1>
    <p class="lede">依据等值线及线上标签内插求取 <b>点暴雨均值 Pa</b> 与 <b>变差系数 Cv</b>（1h / 6h / 24h / 3d），
      并判读 <b>产流计算分区</b>、<b>瞬时单位线分区</b>、<b>推理公式计算分区</b>。测站值不参与定值，仅作旁证。</p>
  </header>
  __BODY__
  <footer class="colophon">
    <span>数据来源：《江西省暴雨洪水查算手册》附图 2-1~2-8、3-1、3-2、4-2</span>
    <span>图幅经纬网仿射配准（1162 px/度）· 定位误差 &lt; 2 km</span>
    <span>__STAMP__</span>
  </footer>
</div>
</body></html>"""

HTML_TAIL = ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kml", default="", help="KML 文件路径（Point / Polygon 型 Placemark，支持多点位）")
    ap.add_argument("--lon", type=float, help="经度 (114~118)")
    ap.add_argument("--lat", type=float, help="纬度 (25~30)")
    ap.add_argument("--name", default="", help="点名（单点模式可选）")
    ap.add_argument("--atlas", default=DEFAULT_ATLAS)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--values", default="", help="读值 JSON 字符串")
    ap.add_argument("--values-file", dest="values_file", default="", help="读值 JSON 文件（人工定稿）")
    ap.add_argument("--from-auto", dest="from_auto", default="",
                    help="auto_value.py 输出的 JSON 文件：自动填值出报告草稿（Pa/建议值/依据/warning），"
                         "并另存 values_auto_filled.json 供人工微调后用 --values-file 定稿")
    ap.add_argument("--all-zones", action="store_true", help="生成全部 3 张分区图裁剪（默认只生成产流分区，因三图分区号一致）")
    args = ap.parse_args()

    # 组装点位列表
    if args.kml:
        if not os.path.isfile(args.kml):
            print(json.dumps({"error": "KML 文件不存在: " + args.kml}, ensure_ascii=False)); sys.exit(2)
        points = parse_kml(args.kml)
        if not points:
            print(json.dumps({"error": "KML 中未找到有效点位（支持 Point 与 Polygon 外环质心）"}, ensure_ascii=False)); sys.exit(2)
    else:
        if args.lon is None or args.lat is None:
            print(json.dumps({"error": "需提供 --kml 或 --lon/--lat"}, ensure_ascii=False)); sys.exit(2)
        points = [(args.name or "未命名", args.lon, args.lat, "point")]
    for n, lo, la, _src in points:
        err = out_of_bounds(lo, la)
        if err:
            print(json.dumps({"error": "点位 {} {}".format(n, err)}, ensure_ascii=False)); sys.exit(2)

    os.makedirs(args.out_dir, exist_ok=True)
    crop_dir = os.path.join(args.out_dir, "crops")

    # 取值解析：--from-auto（机器草稿）或 --values/--values-file（人工定稿）
    multi = len(points) > 1
    values_by_name, global_summary = None, ""
    auto_draft = None
    if args.from_auto:
        auto = json.load(open(args.from_auto, encoding="utf-8-sig"))
        auto_draft = values_from_auto(auto)
        # 草稿另存，供人工微调后 --values-file 定稿（闭环）
        _dp = os.path.join(args.out_dir, "values_auto_filled.json")
        json.dump(auto_draft, open(_dp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if auto_draft is not None:
        v = auto_draft
    elif args.values_file or args.values:
        v = json.load(open(args.values_file, encoding="utf-8-sig")) if args.values_file else json.loads(args.values)
    else:
        v = None
    if v is not None:
        if "points" in v and isinstance(v["points"], dict):
            values_by_name = v["points"]
            global_summary = v.get("summary", "")
        else:
            values_by_name = {points[0][0]: v}
            global_summary = v.get("summary", "")

    # 生成裁剪图
    all_crops, manifest = [], []
    for i, (n, lo, la, src) in enumerate(points, 1):
        sub = os.path.join(crop_dir, "{:02d}_{}".format(i, safe(n))) if multi else crop_dir
        os.makedirs(sub, exist_ok=True)
        cr = gen_crops(lo, la, sub, args.atlas, all_zones=args.all_zones)
        all_crops.append((n, lo, la, src, cr))
        manifest.append({"name": n, "lon": lo, "lat": la, "src": src, "dir": sub,
                         "crops": [{"key": k, "title": t, "path": p} for k, t, p in cr]})

    if v is None:
        print(json.dumps({"status": "crops-ready", "out_dir": args.out_dir, "points": manifest,
                          "next": "跑 auto_value.py 后用 --from-auto 出报告草稿；或逐幅读图后 --values-file 定稿"},
                         ensure_ascii=False))
        return

    # 正式报告
    tag = "_" + safe(points[0][0]) if len(points) == 1 else "_{}点".format(len(points))
    secs = ""
    for n, lo, la, src, cr in all_crops:
        val = values_by_name.get(n) if values_by_name else None
        secs += point_section(n, lo, la, val, cr, global_summary, src=src)
    html = (HTML_HEAD.replace("__TAG__", tag).replace("__BODY__", secs)
            .replace("__STAMP__", _html.escape(data_stamp())) + HTML_TAIL)
    out_html = os.path.join(args.out_dir, "暴雨参数查值报告{}.html".format(tag))
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(json.dumps({"status": "report-done", "html": out_html,
                      "values_draft": os.path.join(args.out_dir, "values_auto_filled.json")
                      if auto_draft is not None else ""}, ensure_ascii=False))

if __name__ == "__main__":
    main()
