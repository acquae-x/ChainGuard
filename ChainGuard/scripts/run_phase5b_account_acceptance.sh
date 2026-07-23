#!/usr/bin/env bash
# Phase 5B「账户完善」Chromium 验收：一键重置隔离库、起后端与 mock IdP、跑 Playwright。
#
# LOGIN_IP_RATE_LIMIT 放宽到 100/minute 是为了单独观测账号维度锁定——IP 维度的
# 默认 5/minute 由 pytest test_ip_rate_limit_is_independent_of_account_lock 锁定，
# 两条防线都在，只是分开验证。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$HERE/../chainguard-web"
API_PORT="${ACCT_API_PORT:-8460}"
IDP_PORT="${ACCT_IDP_PORT:-8470}"
WEB_PORT="${E2E_PORT:-8100}"
DB="$HERE/.workspace/acct-e2e.db"

export DATABASE_URL="sqlite:///./.workspace/acct-e2e.db"
export JWT_SECRET="${JWT_SECRET:-acct-e2e-signing-key-not-for-deployment}"
export CHAINGUARD_ENCRYPTION_KEY="${CHAINGUARD_ENCRYPTION_KEY:-acct-e2e-encryption-key}"
export CHAINGUARD_DISABLE_SCHEDULER=1
export LOGIN_IP_RATE_LIMIT="100/minute"

cd "$HERE"
rm -f "$DB"
python -m alembic upgrade head
python scripts/seed_phase5b_account_e2e.py

python -m uvicorn src.api:app --host 127.0.0.1 --port "$API_PORT" > .workspace/acct-api.log 2>&1 &
API_PID=$!
python scripts/mock_oidc_server.py --port "$IDP_PORT" > .workspace/acct-idp.log 2>&1 &
IDP_PID=$!
trap 'kill $API_PID $IDP_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$API_PORT/healthz" > /dev/null && break
  sleep 1
done

cd "$WEB"
E2E_DATA_MODE=api \
E2E_API_PROXY_TARGET="http://127.0.0.1:$API_PORT" \
E2E_PORT="$WEB_PORT" \
ACCT_API_PORT="$API_PORT" \
ACCT_IDP_PORT="$IDP_PORT" \
npx playwright test e2e/account-lifecycle-api-acceptance.spec.ts "$@"
