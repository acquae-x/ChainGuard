#!/usr/bin/env bash
# ChainGuard 一键演示启动（macOS / Linux）。Windows 用 start-demo.ps1。
#
# 演示态刻意做成"单进程、单端口"：前端构建产物由 FastAPI 直接托管，不起 umi dev。
# 这样现场不存在首屏现编译、开发服务器 OOM、前后端端口错配、CORS 配置错误这几类事故。
#
# uvicorn 固定单 worker：模型注册表当前是本地文件的读-改-写且无锁，
# 多 worker 并发写会丢记录。演示只需单进程，不冒这个险。
set -euo pipefail

PORT=8000
SKIP_INSTALL=0
FRESH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --fresh) FRESH=1; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$REPO_ROOT/ChainGuard"
WEB_DIR="$REPO_ROOT/chainguard-web"

step() { printf '\n\033[36m[%s/6] %s\033[0m\n' "$1" "$2"; }
ok()   { printf '      \033[90m%s\033[0m\n' "$1"; }
die()  { printf '\n\033[31m启动失败：%s\033[0m\n\n' "$1" >&2; exit 1; }

printf '\033[32mChainGuard 演示环境启动\033[0m\n'

step 1 "检查运行环境"
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null || die "找不到 $PYTHON_BIN，需要 Python 3.13+"
command -v node >/dev/null || die "找不到 node，需要 Node.js 20+"
command -v npm  >/dev/null || die "找不到 npm"
ok "$($PYTHON_BIN --version)  node $(node --version)"

# 凭证加密是 fail-closed 的，缺 CHAINGUARD_ENCRYPTION_KEY 后端会拒绝启动。
# 以下仅为本地演示密钥，不是生产配置。
export JWT_SECRET="${JWT_SECRET:-chainguard-demo-jwt-secret-not-for-production}"
export CHAINGUARD_ENCRYPTION_KEY="${CHAINGUARD_ENCRYPTION_KEY:-chainguard-demo-encryption-key-not-for-production}"
export SEED_DEMO_PASSWORD="${SEED_DEMO_PASSWORD:-Demo@2026}"

# DATABASE_URL 必须是绝对路径：相对路径会随工作目录漂移，
# 导致"迁移建的库"和"服务读的库"不是同一个。
DB_PATH="$API_DIR/chainguard-demo.db"
if [[ $FRESH -eq 1 && -f "$DB_PATH" ]]; then rm -f "$DB_PATH"; ok "已删除旧演示库"; fi
export DATABASE_URL="sqlite:///$DB_PATH"
ok "演示库 $DB_PATH"

if [[ $SKIP_INSTALL -eq 0 ]]; then
  step 2 "安装 Python 依赖"
  (cd "$API_DIR" && "$PYTHON_BIN" -m pip install -q -r requirements.txt)
  ok "requirements.txt 就绪"

  step 3 "安装前端依赖"
  if [[ -f "$WEB_DIR/package-lock.json" ]]; then
    (cd "$WEB_DIR" && npm ci --silent)
  else
    (cd "$WEB_DIR" && npm install --silent)
  fi
  ok "node_modules 就绪"
else
  step 2 "跳过 Python 依赖安装（--skip-install）"
  step 3 "跳过前端依赖安装（--skip-install）"
fi

step 4 "迁移数据库并播种演示数据"
cd "$API_DIR"
alembic upgrade head 2>&1 | tail -1 | while read -r l; do ok "$l"; done
# seed 可重入：已存在则跳过，重复执行不会造出第二套演示租户
"$PYTHON_BIN" -m src.webapi.seed 2>&1 | tail -1 | while read -r l; do ok "$l"; done
# 场景/监控/校准类演示依赖企业演示资产，固定 SEED 确定性生成
"$PYTHON_BIN" scripts/generate_enterprise_demo_data.py 2>&1 | tail -1 | while read -r l; do ok "$l"; done

step 5 "构建前端"
cd "$WEB_DIR"
# umi 构建吃内存，默认堆下可能 OOM，显式抬高上限
export NODE_OPTIONS=--max-old-space-size=6144
npx max setup >/dev/null 2>&1
npm run build 2>&1 | tail -3 | while read -r l; do ok "$l"; done
[[ -f "$WEB_DIR/dist/index.html" ]] || die "前端构建产物缺失（chainguard-web/dist/index.html）"
ok "dist/index.html 就绪，将由 FastAPI 直接托管"

step 6 "启动服务"
cat <<EOF

  $(printf '\033[32m演示地址   http://127.0.0.1:%s\033[0m' "$PORT")
  API 文档   http://127.0.0.1:$PORT/docs
  健康检查   http://127.0.0.1:$PORT/readyz

  $(printf '\033[32m演示账号   admin@chainguard.demo / %s\033[0m' "$SEED_DEMO_PASSWORD")
             其余角色同域名：boss / scm_lead / buyer / warehouse /
             sales / finance / planner / auditor

  $(printf '\033[33m注意：登录接口限流 5 次/分钟，连续切换多个角色账号时请稍作间隔\033[0m')

  Ctrl+C 停止

EOF

cd "$API_DIR"
# 单 worker：见文件头说明（模型注册表无锁，多 worker 会丢写）
exec "$PYTHON_BIN" -m uvicorn src.api:app --host 127.0.0.1 --port "$PORT" --workers 1
