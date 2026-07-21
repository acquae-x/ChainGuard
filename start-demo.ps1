<#
.SYNOPSIS
    ChainGuard 一键演示启动（Windows / PowerShell）。

.DESCRIPTION
    从干净的源码包到可演示状态，一条命令走完：
      依赖安装 → 数据库迁移 → 演示数据播种 → 前端构建 → 启动服务

    演示态刻意做成"单进程、单端口"：前端构建产物由 FastAPI 直接托管，
    不起 umi dev。这样现场不存在以下几类事故：
      - umi dev 首屏现编译慢、默认堆下 OOM、崩溃后 src/.umi 残留损坏产物
      - 前后端端口错配（后端 8000 与 umi 默认端口相撞）
      - 反向代理/CORS 配置错误

    uvicorn 固定单 worker：模型注册表当前是本地文件的读-改-写且无锁，
    多 worker 下并发写会丢记录。演示只需要单进程，这里不冒这个险。

.PARAMETER Port
    服务端口，默认 8000。

.PARAMETER SkipInstall
    跳过 pip / npm 依赖安装（已装过时可加速）。

.PARAMETER Fresh
    删除既有演示库，从零重建。

.EXAMPLE
    .\start-demo.ps1
    .\start-demo.ps1 -Port 8080 -SkipInstall
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipInstall,
    [switch]$Fresh
)

$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$ApiDir = Join-Path $RepoRoot 'ChainGuard'
$WebDir = Join-Path $RepoRoot 'chainguard-web'

function Step($n, $text) { Write-Host "`n[$n/6] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      $text" -ForegroundColor DarkGray }
function Die($text) { Write-Host "`n启动失败：$text`n" -ForegroundColor Red; exit 1 }

Write-Host "ChainGuard 演示环境启动" -ForegroundColor Green

# ---------------------------------------------------------------- 0 前置检查
Step 1 "检查运行环境"
foreach ($cmd in @('python', 'node', 'npm')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Die "找不到 $cmd。需要 Python 3.13+ 与 Node.js 20+。"
    }
}
Ok "python $((python --version) -replace 'Python ','')  node $(node --version)"

# 演示用固定密钥：仅用于本地演示，不是生产配置。
# 凭证加密是 fail-closed 的，缺 CHAINGUARD_ENCRYPTION_KEY 后端会拒绝启动。
$env:JWT_SECRET = if ($env:JWT_SECRET) { $env:JWT_SECRET } else { 'chainguard-demo-jwt-secret-not-for-production' }
$env:CHAINGUARD_ENCRYPTION_KEY = if ($env:CHAINGUARD_ENCRYPTION_KEY) { $env:CHAINGUARD_ENCRYPTION_KEY } else { 'chainguard-demo-encryption-key-not-for-production' }
$env:SEED_DEMO_PASSWORD = if ($env:SEED_DEMO_PASSWORD) { $env:SEED_DEMO_PASSWORD } else { 'Demo@2026' }

# DATABASE_URL 必须是绝对路径：相对路径会随工作目录漂移，
# 导致"迁移建的库"和"服务读的库"不是同一个。
$DbPath = (Join-Path $ApiDir 'chainguard-demo.db')
if ($Fresh -and (Test-Path $DbPath)) { Remove-Item -Force $DbPath; Ok "已删除旧演示库" }
$env:DATABASE_URL = "sqlite:///$($DbPath -replace '\\','/')"
Ok "演示库 $DbPath"

# ---------------------------------------------------------------- 1 依赖
if (-not $SkipInstall) {
    Step 2 "安装 Python 依赖"
    Push-Location $ApiDir
    try { python -m pip install -q -r requirements.txt } finally { Pop-Location }
    Ok "requirements.txt 就绪"

    Step 3 "安装前端依赖"
    Push-Location $WebDir
    try {
        if (Test-Path 'package-lock.json') { npm ci --silent } else { npm install --silent }
    } finally { Pop-Location }
    Ok "node_modules 就绪"
} else {
    Step 2 "跳过 Python 依赖安装（-SkipInstall）"
    Step 3 "跳过前端依赖安装（-SkipInstall）"
}

# ---------------------------------------------------------------- 2 数据库
Step 4 "迁移数据库并播种演示数据"
Push-Location $ApiDir
try {
    alembic upgrade head 2>&1 | Select-Object -Last 1 | ForEach-Object { Ok $_ }
    # seed 可重入：已存在则跳过，重复执行不会造出第二套演示租户
    python -m src.webapi.seed 2>&1 | Select-Object -Last 1 | ForEach-Object { Ok $_ }
    # 场景/监控/校准类演示依赖企业演示资产，固定 SEED 确定性生成
    python scripts/generate_enterprise_demo_data.py 2>&1 | Select-Object -Last 1 | ForEach-Object { Ok $_ }
} finally { Pop-Location }

# ---------------------------------------------------------------- 3 前端构建
Step 5 "构建前端"
Push-Location $WebDir
try {
    # umi dev 在默认堆上会 OOM，构建同样吃内存，这里显式抬高上限
    $env:NODE_OPTIONS = '--max-old-space-size=6144'
    npx max setup 2>&1 | Out-Null
    npm run build 2>&1 | Select-Object -Last 3 | ForEach-Object { Ok $_ }
} finally { Pop-Location }
if (-not (Test-Path (Join-Path $WebDir 'dist/index.html'))) { Die "前端构建产物缺失（chainguard-web/dist/index.html）" }
Ok "dist/index.html 就绪，将由 FastAPI 直接托管"

# ---------------------------------------------------------------- 4 启动
Step 6 "启动服务"
Write-Host ""
Write-Host "  演示地址   http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "  API 文档   http://127.0.0.1:$Port/docs" -ForegroundColor DarkGray
Write-Host "  健康检查   http://127.0.0.1:$Port/readyz" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  演示账号   admin@chainguard.demo / $($env:SEED_DEMO_PASSWORD)" -ForegroundColor Green
Write-Host "             其余角色同域名：boss / scm_lead / buyer / warehouse /" -ForegroundColor DarkGray
Write-Host "             sales / finance / planner / auditor" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  注意：登录接口限流 5 次/分钟，连续切换多个角色账号时请稍作间隔" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Ctrl+C 停止" -ForegroundColor DarkGray
Write-Host ""

Push-Location $ApiDir
try {
    # 单 worker：见文件头说明（模型注册表无锁，多 worker 会丢写）
    python -m uvicorn src.api:app --host 127.0.0.1 --port $Port --workers 1
} finally { Pop-Location }
