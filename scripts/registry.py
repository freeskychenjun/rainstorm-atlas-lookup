# -*- coding: utf-8 -*-
"""配准常数与坐标换算 —— 全 skill 的单一来源，勿在他处复制（历史事故：常数三处
重复，改一处漏两处即系统性错值）。

坐标 → 像素：
  统计图（附图2-1~2-8）: x = X0·(w/W0) + (lon-114)·S_STAT
                         y = Y0·(h/H0) + (30-lat)·S_STAT
  分区图（附图3-1/3-2/4-2）: x = CX + (lon-115.88)·S9
                             y = CY + (28.68-lat)·S9
像素距离 → km（各向异性，2026-10 修正）：
  1° 纬距 ≈ 111 km；1° 经距 ≈ 111·cos(φ) km。旧版按 111 各向同性换算，东西向
  距离高估 11~13%、方位角偏差最大 5~7°；修正后报告的 km/方位角才可作为取值依据。
"""
import math
import os

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------- 统计图（附图 2-1 ~ 2-8，等值线） ----------------
S_STAT = 1162.0                                   # px/°（实测标定，勿随意改动）
STAT_BASE = {"W": 5495, "H": 7076, "X0": 433.0, "Y0": 345.0}   # 1h-Pa 幅实测基准
STAT_KEYS = ["1h-Pa", "1h-Cv", "6h-Pa", "6h-Cv", "24h-Pa", "24h-Cv", "3d-Pa", "3d-Cv"]
STAT_FILE = {
    "1h-Pa": "1--1h-Pa.jpg", "1h-Cv": "2--1h-Cv.jpg",
    "6h-Pa": "3--6h-Pa.jpg", "6h-Cv": "4--6h-Cv.jpg",
    "24h-Pa": "5--24h-Pa.jpg", "24h-Cv": "6--24h-Cv.jpg",
    "3d-Pa": "7--3d-Pa.jpg", "3d-Cv": "8--3d-Cv.jpg",
}
STAT_TITLES = {
    "1h-Pa": "1h 暴雨均值 Pa", "1h-Cv": "1h Cv",
    "6h-Pa": "6h 暴雨均值 Pa", "6h-Cv": "6h Cv",
    "24h-Pa": "24h 暴雨均值 Pa", "24h-Cv": "24h Cv",
    "3d-Pa": "3d 暴雨均值 Pa", "3d-Cv": "3d Cv",
}
# STAT_SHEETS 兼容旧引用（query_atlas/annotate_lines 等按 (文件名, 标题) 使用）
STAT_SHEETS = [(STAT_FILE[k], STAT_TITLES[k]) for k in STAT_KEYS]

# ---------------- 分区图（附图 3-1 / 3-2 / 4-2） ----------------
# 【重要规律】三张分区图分区号完全一致——只判读产流分区图，另两张仅供人工复核。
# 推理公式分区页（4-2）图框位置与前两页不同，锚点不可混用！
S9 = 1170.0                                       # px/°
ZONE_ANCHOR_LON, ZONE_ANCHOR_LAT = 115.88, 28.68
ZONE_CX, ZONE_CY = 3160, 3390                     # 产流/瞬时两页同锚
PART_SHEETS = [
    ("9--产流分区.jpg", "产流计算分区",     ZONE_CX, ZONE_CY, True),
    ("9--瞬时分区.jpg", "瞬时单位线分区",   ZONE_CX, ZONE_CY, False),
    ("9--推理分区.jpg", "推理公式计算分区", 3135, 2770, False),
]

# ---------------- 覆盖范围与换算口径 ----------------
BOUNDS = (113.8, 24.8, 118.2, 30.2)               # lon_min, lat_min, lon_max, lat_max
KM_PER_DEG = 111.0                                # 1° 纬距的 km 数

_ATLAS_FALLBACK = r"D:\DSH工作区\自动查找图集参数\江西省暴雨洪水查算手册图集"


def resolve_atlas():
    """图集目录：优先 skill 内置 atlas/，回退开发机外置目录。"""
    cand = [os.path.join(SKILL_ROOT, "atlas"), _ATLAS_FALLBACK]
    for p in cand:
        if os.path.isdir(p):
            return p
    return cand[-1]


def stat_xy(lon, lat, w, h):
    """统计图：经纬度 → 像素（w/h 为该幅实际尺寸，基准常数按幅面比例缩放）。"""
    x0 = STAT_BASE["X0"] * w / STAT_BASE["W"]
    y0 = STAT_BASE["Y0"] * h / STAT_BASE["H"]
    return x0 + (lon - 114) * S_STAT, y0 + (30 - lat) * S_STAT


def part_xy(lon, lat, cx, cy):
    """分区图：经纬度 → 像素（锚点=南昌 115.88E, 28.68N）。"""
    return cx + (lon - ZONE_ANCHOR_LON) * S9, cy + (ZONE_ANCHOR_LAT - lat) * S9


def zone_xy(lon, lat):
    """产流/瞬时分区图：经纬度 → 像素。"""
    return part_xy(lon, lat, ZONE_CX, ZONE_CY)


def out_of_bounds(lon, lat):
    """出界返回错误描述（中文），界内返回空串。"""
    lo_min, la_min, lo_max, la_max = BOUNDS
    if not (lo_min <= lon <= lo_max and la_min <= lat <= la_max):
        return "点位 (%.4f, %.4f) 超出图幅覆盖范围(%g~%gE, %g~%gN)，本图集仅适用江西境内" % (
            lon, lat, lo_min, lo_max, la_min, la_max)
    return ""


def km_scales(lat):
    """统计图像素的 km 换算系数（各向异性）：返回 (kx, ky)。

    kx 用于 dx 像素（东西向），ky 用于 dy 像素（南北向）；
    方位角 = atan2(dx·kx, dy·ky)（正北 0°，顺时针）。
    """
    kx = KM_PER_DEG * math.cos(math.radians(lat)) / S_STAT
    ky = KM_PER_DEG / S_STAT
    return kx, ky


def zone_px_km():
    """分区图 1 像素对应的 km 数（用于分区边界邻近提示）。"""
    return KM_PER_DEG / S9
