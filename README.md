# rainstorm-atlas-lookup

按经纬度坐标查询《江西省暴雨洪水查算手册》图集：**1h / 6h / 24h / 3d 四个历时的点暴雨均值（Pa）与变差系数（Cv）等值线查值**，以及**产流计算分区、瞬时单位线分区、推理公式计算分区**的自动判定。

## 核心特性

- **349 条等值线已全量数字化并经人工逐线确认**（`cache/manual_labels_v2/`）——查值不再依赖逐幅读图
- **一键查值**：输入经纬度，输出 8 个参数 + 产流分区号，每项附判定依据（线号、线值、实测距离 km、方位角）
- **分区自动判定**：产流分区边界已数字化（31 段边界 / 23 结点 / 9 个封闭区域校验通过），点位落区程序化
- **自包含**：图集随 skill 打包（`atlas/`），换机即用
- **HTML 查值报告**：内嵌 9 幅绿十字定位裁剪图 + 逐幅取值依据，可独立分发

## 环境要求

| 依赖 | 用途 |
|---|---|
| Python 3.x + Pillow + numpy | 查值 / 报告（必需） |
| opencv-python-headless | 分区边界重数字化（仅重建分区时需要） |
| 图集 | 已随仓库外置：放入本目录 `atlas\` 子目录（11 幅 jpg，约 196 MB，**分辨率不可变更**——配准常数为绝对像素） |

## 快速开始

```bash
# 一键查值（8 参数 + 产流分区，约 1 分钟）
python scripts/auto_value.py --lon 114.497 --lat 29.259

# 单独查产流分区号
python scripts/zone_lookup.py --lon 114.497 --lat 29.259

# 生成 HTML 查值报告（内嵌定位裁剪图）
python scripts/lookup.py --kml 某工程.kml --out-dir 输出目录
```

`auto_value.py` 输出 JSON 示例（每项含最近线 / 对侧线的线号、值、距离、方位与内插值）：

```json
{
  "zone": "Ⅷ",
  "values": {
    "24h-Pa": {
      "nearest":  { "id": "L11", "value": 120, "km": 9.9, "azimuth": 78 },
      "opposite": { "id": "L18", "value": 140, "km": 17.0, "azimuth": 136 },
      "interpolated": 127.4
    }
  }
}
```

## 脚本一览

| 脚本 | 功能 |
|---|---|
| `auto_value.py` | **一键查值**：经纬度 → 8 参数 + 分区（基于确认线值库内插） |
| `zone_lookup.py` | 产流分区快速查询（数字化边界 + 参考点对照） |
| `lookup.py` | 生成 HTML 查值报告（配准 / 裁剪图 / 模板） |
| `digitize.py` | 等值线数字化：提取→合并→编号→挂值→出编号校核图 |
| `parse_atlas.py` | 图幅预解析（红色通道提取掩膜与标签候选） |
| `digitize_zones.py` | 产流分区边界数字化（骨架/结点/段/省界吸附/封闭校验） |
| `query_atlas.py` | 路径 A 查询（最近线距离 + 标签候选拼图） |
| `read_marks.py` / `follow_line.py` / `trace_line.py` / `label_hunt.py` / `annotate_lines.py` | 圈注提取 / 追线 / 断点检测 / 编号标注等辅助工具 |
| `deploy.ps1` | 同步到 `~/.agents/skills/`（含 atlas 同步） |

## 数据资产（本仓库的核心价值）

| 路径 | 内容 |
|---|---|
| `cache/manual_labels_v2/` | **8 幅 × 349 条等值线的线值**（全部经人工逐线确认，2026-10）+ 审计记录 |
| `cache/manual_labels/` | 人工补描线（省界带漏检段）与圈注值库 |
| `cache/zone_region_map.npz` + `region_zone_map.json` | 产流分区逐像素区域标签 + 9 个参考点对照 |
| `cache/jiangxi_360000.json` | 江西省界矢量（阿里云 DataV，供分区提取过滤用） |
| `cache/marks_values.json` | 人工圈注值库（277 个圈） |

## 部署到本机 agent

```powershell
powershell -File deploy.ps1    # 同步 scripts + cache + atlas 到 ~/.agents/skills/
```

## 读图纪律（历史教训摘要，完整版见 SKILL.md）

1. **等值线值以线上标签为准**，站值标注（"站名 ⊙ 均值/年数"两行式）严禁参与定值；
2. 标签可能在线的两头、中间或沿线斜排，也可能压在线上——放大视场后两种形态都要找；
3. **闭合等值线的值在圈内**，且内外侧判读必须结合圈内站值分布，不能凭"外侧递减"直觉；
4. 夹持区间必须四面排查并确认两侧线的标签，"点在某线上"必须以追到标签为证；
5. 省界带等值线被截断变短，注意数字化时的小段过滤漏检；
6. 不同值的等值线可能被过度桥接合并——重数字化时 merge 阈值不宜过大（本库已按 60 px 重建并全量确认）。

## 版本

- **v1.0.1**（2026-10-10）：首发布。8 幅线值全量人工确认；产流分区自动判定；一键查值。
- 已同步发布到规划院 skill 平台（v1.0.1）。
