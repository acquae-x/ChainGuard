#!/usr/bin/env bash
# Phase 2 四条核心流程 + 导入 联调冒烟脚本
# 在你的机器上运行（后端可正常启动的环境）。前置：
#   1) 已设置 SEED_DEMO_PASSWORD，后端已起：python -m src.webapi.seed
#                  uvicorn src.api:app --host 127.0.0.1 --port 8000
#   2) 需要 curl 与 jq（Windows 可用 git-bash / WSL）。
# 用法：  bash phase2_smoke.sh
set -euo pipefail
BASE="http://127.0.0.1:8000/api/v1"
DEMO_PASSWORD="${SEED_DEMO_PASSWORD:?请先设置 SEED_DEMO_PASSWORD}"
say(){ printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

say "0. 存活探针 /healthz /readyz"
curl -sf http://127.0.0.1:8000/healthz && echo " healthz OK"
curl -sf http://127.0.0.1:8000/readyz && echo " readyz OK"

say "1. 登录 scm_lead（供应链负责人，有 decision:modify / approval）"
TOKEN=$(curl -sf -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg account 'scm_lead@chainguard.demo' --arg password "$DEMO_PASSWORD" '{account:$account,password:$password}')" | jq -r .token)
echo "token=${TOKEN:0:16}..."
AUTH=(-H "Authorization: Bearer $TOKEN")

say "2. /auth/me 权限码"
curl -sf "${AUTH[@]}" "$BASE/auth/me" | jq '{name:.currentUser.name, role:.currentUser.roleCode, perms:(.currentUser.permissions|length)}'

say "3. 取一条风险，创建应急事件"
RISK_ID=$(curl -sf "${AUTH[@]}" "$BASE/risks" | jq -r '.data[0].id')
INC=$(curl -sf "${AUTH[@]}" -X POST "$BASE/incidents" -H 'Content-Type: application/json' \
  -d "{\"riskIds\":[\"$RISK_ID\"],\"title\":\"联调-供应中断\"}")
INC_ID=$(echo "$INC" | jq -r .id); echo "incident=$INC_ID status=$(echo "$INC"|jq -r .status)"

say "4. 异步生成方案（202 + jobId 轮询）"
JOB=$(curl -sf "${AUTH[@]}" -X POST "$BASE/incidents/$INC_ID/proposals:generate" -d '{}' | jq -r .jobId)
for i in $(seq 1 40); do
  ST=$(curl -sf "${AUTH[@]}" "$BASE/jobs/$JOB" | jq -r .status)
  echo "  job=$JOB status=$ST"; [ "$ST" = succeeded ] && break; [ "$ST" = failed ] && { echo FAIL; exit 1; }; sleep 1.5
done
PROP_ID=$(curl -sf "${AUTH[@]}" "$BASE/proposals?incidentId=$INC_ID" | jq -r '.data[0].id')
echo "proposal=$PROP_ID"

say "5. 提交审批 → 通过（scm_lead 对低/中风险可批）"
curl -sf "${AUTH[@]}" -X POST "$BASE/proposals/$PROP_ID/submit" -d '{}' >/dev/null || true
AP_ID=$(curl -sf "${AUTH[@]}" "$BASE/approvals?tab=pending" | jq -r '.data[0].id')
echo "approval=$AP_ID"
curl -sf "${AUTH[@]}" -X POST "$BASE/approvals/$AP_ID/approve" -H 'Content-Type: application/json' -d '{"reason":"联调通过"}' \
  | jq '{status:.status}' || echo "（若 403：该风险等级需 boss/finance，换账号重试）"

say "6. 审批通过后任务自动生成"
curl -sf "${AUTH[@]}" "$BASE/tasks" | jq '{total:.total, first:.data[0].title}'

say "7. 审计可查"
AUDITOR_TOKEN=$(curl -sf -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg account 'auditor@chainguard.demo' --arg password "$DEMO_PASSWORD" '{account:$account,password:$password}')" | jq -r .token)
AUDITOR_AUTH=(-H "Authorization: Bearer $AUDITOR_TOKEN")
curl -sf "${AUDITOR_AUTH[@]}" "$BASE/audit-logs" | jq '{total:.total, latest:.data[0].action}'

say "8. 500 不泄漏异常类名（访问不存在资源应得规范信封，不含堆栈）"
curl -s "${AUTH[@]}" "$BASE/incidents/not-exist" | jq '{code, hasTrace:(.traceId!=null)}'

say "9. 导入流水线（需 admin/scm_lead 有 data:import）：upload→preflight→confirm→execute→poll"
printf 'name,leadTime,supplierPrice,status\n宁波微电,3,21.2,可替代\n' > /tmp/sup.csv
UP=$(curl -sf "${AUTH[@]}" -X POST "$BASE/imports/upload?type=supplier" -F "file=@/tmp/sup.csv")
IMP_ID=$(echo "$UP" | jq -r .id); echo "importJob=$IMP_ID"
curl -sf "${AUTH[@]}" -X POST "$BASE/imports/$IMP_ID/preflight" >/dev/null || true
curl -sf "${AUTH[@]}" -X POST "$BASE/imports/$IMP_ID/confirm" -H 'Content-Type: application/json' -d '{"values":{"duplicatePolicy":"skip","onlyValidRows":true}}' >/dev/null
curl -sf "${AUTH[@]}" -X POST "$BASE/imports/$IMP_ID/execute" >/dev/null
for i in $(seq 1 30); do ST=$(curl -sf "${AUTH[@]}" "$BASE/imports/$IMP_ID" | jq -r .status); echo "  import status=$ST"; case "$ST" in succeeded|failed|done|completed) break;; esac; sleep 1.2; done

say "10. 租户隔离：不带 token 应 401"
curl -s -o /dev/null -w "no-token GET /risks -> %{http_code}\n" "$BASE/risks"

echo -e "\n\033[1;32mSMOKE DONE\033[0m  逐条核对上面输出与 acceptance/Phase2_验收清单.md"
