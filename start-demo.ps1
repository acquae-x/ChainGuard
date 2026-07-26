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

    uvicorn 固定单 worker：演示只需要单进程，少一层不确定性。
    （历史原因已不成立——模型注册表的读-改-写此前无锁、多 worker 下会丢记录，
    现已用 file_lock + 原子写修复；compose 的生产编排就是 --workers 4。）

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

# 中文 Windows 控制台默认 GBK，脚本本身是 UTF-8（带 BOM，否则 PS 5.1 按 ANSI 读会
# 把中文读成乱码并连带吃掉引号导致语法错误）。这里把输出编码也统一到 UTF-8，
# 否则提示信息在控制台里是乱码。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$RepoRoot = $PSScriptRoot
$ApiDir = Join-Path $RepoRoot 'ChainGuard'
$WebDir = Join-Path $RepoRoot 'chainguard-web'

function Step($n, $text) { Write-Host "`n[$n/6] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      $text" -ForegroundColor DarkGray }
function Die($text) { Write-Host "`n启动失败：$text`n" -ForegroundColor Red; exit 1 }

# 跑外部命令并按退出码判定成败。
#
# 不能用 `cmd 2>&1 | ...`：PowerShell 5.1 会把原生命令的 stderr 每一行包成
# ErrorRecord 抛成 NativeCommandError，配合 $ErrorActionPreference='Stop'
# 会在命令实际成功（exit 0）时把脚本打断——alembic / npm 都把普通 INFO 日志
# 写到 stderr，必踩。这里只认退出码。
function Run($what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { Die "$what 失败（退出码 $LASTEXITCODE）" }
}

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

# 文案生成后端：有 DEEPSEEK_API_KEY 就用 DeepSeek，否则落确定性模板。
# 密钥只从环境变量读，绝不写进仓库；未配置也能完整演示，只是解释文案走模板。
$LlmProvider = if ($env:CHAINGUARD_LLM_PROVIDER) { $env:CHAINGUARD_LLM_PROVIDER }
               elseif ($env:DEEPSEEK_API_KEY) { 'deepseek' } else { 'template（未配置 DEEPSEEK_API_KEY）' }
Ok "解释文案后端 $LlmProvider"

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
    try { Run "Python 依赖安装" { python -m pip install -q -r requirements.txt } } finally { Pop-Location }
    Ok "requirements.txt 就绪"

    Step 3 "安装前端依赖"
    Push-Location $WebDir
    try {
        if (Test-Path 'package-lock.json') { Run "npm ci" { npm ci --silent } }
        else { Run "npm install" { npm install --silent } }
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
    # 用 python -m 调用而非裸 alembic：pip 装的入口脚本在 Scripts 目录，
    # 新机器上该目录常常不在 PATH 里，裸命令会直接"找不到 alembic"。
    Run "数据库迁移" { python -m alembic upgrade head }
    # seed 可重入：已存在则跳过，重复执行不会造出第二套演示租户
    Run "演示数据播种" { python -m src.webapi.seed }
    # 场景/监控/校准类演示依赖企业演示资产，固定 SEED 确定性生成
    Run "企业演示资产生成" { python scripts/generate_enterprise_demo_data.py }
    # 上一步只生成 CSV 文件，不进租户。只播种基础演示租户的话全库仅 1 个物料，
    # 低于节点健康相对轨的最小样本量 8，工作台会显示"相对离群线已回退为专家阈值"——
    # 双轨阈值这条能力在演示里根本看不见。这里把企业 CSV 导进租户（241 个物料）。
    # --skip-if-sufficient 保证重复启动不会撞上导入去重。
    Run "企业演示数据导入租户" {
        python scripts/seed_demo_enterprise.py --database $DbPath --tenant-id tenant-demo --skip-if-sufficient
    }
} finally { Pop-Location }

# ---------------------------------------------------------------- 3 前端构建
Step 5 "构建前端"
Push-Location $WebDir
try {
    # umi dev 在默认堆上会 OOM，构建同样吃内存，这里显式抬高上限
    $env:NODE_OPTIONS = '--max-old-space-size=6144'
    Run "前端类型声明生成" { npx max setup }
    Run "前端构建" { npm run build }
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
