# 部署脚本：把开发目录同步到 skill 部署目录
# 用法: powershell -ExecutionPolicy Bypass -File deploy.ps1        （增量，按时间戳）
#       powershell -ExecutionPolicy Bypass -File deploy.ps1 -All   （强制全量）
# 注意: 本文件必须保存为 UTF-8 with BOM。Windows PowerShell 5.1 会把无 BOM 的 UTF-8
#       按 ANSI 解析，中文注释会导致 ParserError 而使整份脚本无法执行（历史踩坑）。
param([switch]$All)
$ErrorActionPreference = 'Stop'
$dev  = $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.agents\skills\rainstorm-atlas-lookup'
if (-not (Test-Path "$dev\SKILL.md")) { Write-Error "开发目录缺少 SKILL.md: $dev"; exit 1 }

function Sync-One($src, $dst) {
    if ((-not $All) -and (Test-Path $dst)) {
        if ((Get-Item $src).LastWriteTimeUtc -le (Get-Item $dst).LastWriteTimeUtc) { return $false }
    }
    Copy-Item $src $dst -Force
    return $true
}

$n = 0
New-Item -ItemType Directory -Force -Path "$dest\scripts" | Out-Null
if (Sync-One "$dev\SKILL.md" $dest) { $n++ }
Get-ChildItem "$dev\scripts" -Filter *.py -File | ForEach-Object {
    if (Sync-One $_.FullName "$dest\scripts\$($_.Name)") { $n++ }
}
# 缓存目录（预解析产物 + 人工确认线值库 + 几何缓存）：必须同步，否则部署副本查到旧值
foreach ($sub in @('cache')) {
    if (Test-Path "$dev\$sub") {
        New-Item -ItemType Directory -Force -Path "$dest\$sub" | Out-Null
        Get-ChildItem "$dev\$sub" -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring("$dev\$sub".Length).TrimStart('\')
            $tgt = Join-Path "$dest\$sub" $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $tgt) | Out-Null
            if (Sync-One $_.FullName $tgt) { $n++ }
        }
    }
}
# 清理部署目录中已从源码 scripts/ 移除的旧脚本（一次性数字化工具已移 tools/，不部署）
Get-ChildItem "$dest\scripts" -Filter *.py -File -ErrorAction SilentlyContinue | ForEach-Object {
    if (-not (Test-Path "$dev\scripts\$($_.Name)")) {
        Remove-Item $_.FullName -Force
        Write-Output "清理部署残留: scripts\$($_.Name)"
    }
}
# 图集（分辨率不可变，配准依赖绝对像素）
if (Test-Path "$dev\atlas") {
    New-Item -ItemType Directory -Force -Path "$dest\atlas" | Out-Null
    Get-ChildItem "$dev\atlas" -Filter *.jpg -File | ForEach-Object {
        if (Sync-One $_.FullName "$dest\atlas\$($_.Name)") { $n++ }
    }
}
Write-Output "已部署 -> $dest  (更新 $n 个文件)"

# ---- 一致性校验：源码关键文件必须与部署副本逐字节一致 ----
$rels = @('SKILL.md') + (Get-ChildItem "$dev\scripts" -Filter *.py -File | ForEach-Object { "scripts\$($_.Name)" })
$bad = @()
foreach ($r in $rels) {
    $a = (Get-FileHash "$dev\$r" -Algorithm MD5).Hash
    $b = if (Test-Path "$dest\$r") { (Get-FileHash "$dest\$r" -Algorithm MD5).Hash } else { '' }
    if ($a -ne $b) { $bad += $r }
}
if ($bad.Count -gt 0) {
    Write-Output "!! 校验失败，仍不一致: $($bad -join ', ')"
    exit 1
}
Write-Output "校验通过：SKILL.md + scripts/*.py 与部署副本一致"
