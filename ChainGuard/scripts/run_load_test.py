"""对**运行中的**服务做并发负载测试，输出吞吐、时延分位与错误率。

与被删除的旧基准（benchmarks/test_api_perf.py）的区别，也是这个脚本存在的理由：

- 旧基准用 ``TestClient(app)``，是**进程内 ASGI 调用**——不走网络栈、不经过真实
  uvicorn worker、没有连接池竞争。它测的是处理函数耗时，不是服务吞吐，因此产不出
  能写进 SLA 的数字。本脚本打真实 HTTP。
- 旧基准打的是已随遗留认证路径一并移除的免认证端点。本脚本走正式登录拿 JWT，
  压的是真实 ``/api/v1`` 路径。
- 旧基准固定 20 请求 / 4 线程。本脚本按并发梯度扫描，可看出拐点。

**这个脚本产出的不是生产 SLA。** 数字只对"运行它的那台机器 + 那个 worker 数 +
那个数据库"成立。报告里必须连同环境一起记录，不得外推。

用法：

    # 另开一个终端把服务起起来（记下 worker 数与数据库类型）
    python -m uvicorn src.api:app --host 127.0.0.1 --port 8000 --workers 4

    python scripts/run_load_test.py --base-url http://127.0.0.1:8000 \
        --account admin@chainguard.demo --password Demo@2026 \
        --concurrency 1,2,4,8,16 --requests 60

多账号身份串号检测（并发正确性，不是性能）：

    python scripts/run_load_test.py --base-url http://127.0.0.1:8000 \
        --account admin@chainguard.demo --password Demo@2026 \
        --account scm_lead@chainguard.demo --password Demo@2026 \
        --identity-check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# 压测目标：从"最便宜"到"最贵"，用来看出成本来自哪一层。
# healthz 不查库不鉴权，是这台机器的性能地板；node-health 会为全部物料算库存风险
# 并构建节点图谱，是当前最重的只读端点。
DEFAULT_TARGETS = [
    ("healthz", "GET", "/healthz", False),
    ("dashboard/kpis", "GET", "/api/v1/dashboard/kpis", True),
    ("dashboard/node-health", "GET", "/api/v1/dashboard/node-health", True),
    ("risks", "GET", "/api/v1/risks", True),
]


@dataclass
class Sample:
    elapsed_ms: float
    status: int
    # status=0 时记异常类型。不记成因就无法区分"服务端拒绝"（如 429/500）与
    # "客户端自己连不上"（连接池超时、端口耗尽）——后者是测量工具的产物，
    # 把它当成被测系统的错误率会得出完全错误的结论。
    note: str = ""


@dataclass
class Result:
    target: str
    concurrency: int
    samples: list[Sample] = field(default_factory=list)
    wall_s: float = 0.0

    @property
    def ok(self) -> int:
        return sum(1 for s in self.samples if 200 <= s.status < 300)

    @property
    def errors(self) -> int:
        return len(self.samples) - self.ok

    def pct(self, p: float) -> float:
        """线性插值分位数。样本量小时比"取第 k 个"更稳。"""
        values = sorted(s.elapsed_ms for s in self.samples)
        if not values:
            return float("nan")
        if len(values) == 1:
            return values[0]
        pos = (len(values) - 1) * p / 100
        low = int(pos)
        high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (pos - low)

    @property
    def rps(self) -> float:
        return len(self.samples) / self.wall_s if self.wall_s > 0 else float("nan")


async def _login(client: httpx.AsyncClient, base: str, account: str, password: str) -> dict[str, Any]:
    """登录拿 JWT。登录接口有限流（5 次/分钟），因此每个账号只登一次并复用。"""
    response = await client.post(
        f"{base}/api/v1/auth/login",
        json={"account": account, "password": password},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"登录失败 {account}: HTTP {response.status_code} {response.text[:200]}\n"
            "提示：登录接口限流 5 次/分钟，短时间内反复运行会被拒。"
        )
    payload = response.json()
    return {
        "token": payload["token"],
        "tenant_id": (payload.get("currentUser") or {}).get("tenantId"),
        "account": account,
    }


async def _one(
    client: httpx.AsyncClient, base: str, method: str, path: str, headers: dict[str, str]
) -> Sample:
    start = time.perf_counter()
    note = ""
    try:
        response = await client.request(method, f"{base}{path}", headers=headers, timeout=60.0)
        status = response.status_code
    except Exception as error:  # 连接错误也是错误，不能吞掉
        status = 0
        note = type(error).__name__
    return Sample((time.perf_counter() - start) * 1000, status, note)


async def _measure(
    base: str, name: str, method: str, path: str, headers: dict[str, str],
    concurrency: int, total: int, warmup_rounds: int = 8,
) -> Result:
    """固定总请求数，按 concurrency 控制在飞请求数。"""
    result = Result(target=name, concurrency=concurrency)
    limits = httpx.Limits(max_connections=concurrency + 4, max_keepalive_connections=concurrency + 4)
    async with httpx.AsyncClient(limits=limits) as client:
        # 预热必须覆盖**每一个** worker。多 worker 部署下只打一发只暖到一个进程，
        # 其余进程的首次请求仍要付惰性导入与配置加载的代价（实测冷/暖差 2~4 倍），
        # 那部分开销会被算进压测结果，读起来像是"并发一上去就慢"。
        # 并发发起 warmup_rounds 发，让负载均衡把它们摊到各 worker 上。
        warmup = max(concurrency, warmup_rounds)
        await asyncio.gather(*[
            _one(client, base, method, path, headers) for _ in range(warmup)
        ])

        semaphore = asyncio.Semaphore(concurrency)

        async def guarded() -> Sample:
            async with semaphore:
                return await _one(client, base, method, path, headers)

        started = time.perf_counter()
        result.samples = list(await asyncio.gather(*[guarded() for _ in range(total)]))
        result.wall_s = time.perf_counter() - started
    return result


async def _identity_check(
    base: str, sessions: list[dict[str, Any]], rounds: int
) -> tuple[int, int, int]:
    """并发身份串号检测：请求态是否被跨请求污染。

    这是 FastAPI 应用的经典并发缺陷——把租户/用户存进模块级全局变量，单请求下
    永远正确，并发下才会串。多个账号同时打 /auth/me，每个响应必须与自己的令牌一致。

    返回 (检查次数, 不一致次数, 传输层失败次数)。这测的是**正确性**，不是性能。
    """
    checked = 0
    mismatched = 0
    transport_failures = 0
    async with httpx.AsyncClient() as client:
        async def probe(session: dict[str, Any]) -> tuple[dict[str, Any], httpx.Response | None]:
            # 传输层异常不能让整个检测崩掉：它与"身份串号"是两回事，必须分开计数，
            # 否则一次超时就会伪装成"检测没跑完"，掩盖真正要查的正确性问题。
            try:
                response = await client.get(
                    f"{base}/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {session['token']}"},
                    timeout=30.0,
                )
            except Exception:
                return session, None
            return session, response

        for _ in range(rounds):
            pairs = await asyncio.gather(*[probe(s) for s in sessions for _ in range(4)])
            for session, response in pairs:
                checked += 1
                if response is None:
                    transport_failures += 1
                    continue
                if response.status_code != 200:
                    mismatched += 1
                    print(f"  !! {session['account']} 返回 HTTP {response.status_code}")
                    continue
                # /auth/me 返回 {currentUser, tenant} 的嵌套结构，身份字段在
                # currentUser 里。在顶层取会恒得 None，把每一次都误判成串号——
                # 断言字段取错时，检测会"永远发现问题"，比不检测更糟。
                body = response.json()
                current = body.get("currentUser") or {}
                got_account = current.get("email") or current.get("account")
                got_tenant = current.get("tenantId")
                if got_account != session["account"] or (
                    session["tenant_id"] and got_tenant != session["tenant_id"]
                ):
                    mismatched += 1
                    print(
                        f"  !! 身份串号：令牌属于 {session['account']}"
                        f"（租户 {session['tenant_id']}），响应却是 {got_account}"
                        f"（租户 {got_tenant}）"
                    )
    return checked, mismatched, transport_failures


def _print_table(results: list[Result]) -> None:
    header = f"{'端点':<26}{'并发':>5}{'请求':>6}{'错误':>6}{'RPS':>9}{'P50':>9}{'P95':>9}{'P99':>9}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.target:<26}{r.concurrency:>5}{len(r.samples):>6}{r.errors:>6}"
            f"{r.rps:>9.1f}{r.pct(50):>9.1f}{r.pct(95):>9.1f}{r.pct(99):>9.1f}"
        )
    print("\n时延单位 ms。RPS = 总请求数 / 墙钟耗时。")

    breakdown: dict[str, int] = {}
    for r in results:
        for sample in r.samples:
            if 200 <= sample.status < 300:
                continue
            key = sample.note or f"HTTP {sample.status}"
            breakdown[key] = breakdown.get(key, 0) + 1
    if breakdown:
        print("\n非 2xx 明细（按成因分类）：")
        for key in sorted(breakdown, key=lambda k: -breakdown[k]):
            print(f"  {key:<28}{breakdown[key]:>6}")
        print(
            "  提示：ConnectError / PoolTimeout / ReadTimeout 属于客户端侧成因，"
            "是测量工具的产物，不是被测服务的错误率。"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="ChainGuard 并发负载测试（打真实 HTTP）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--account", action="append", default=[], help="可重复；多个账号用于身份串号检测")
    parser.add_argument("--password", action="append", default=[])
    parser.add_argument("--concurrency", default="1,2,4,8", help="逗号分隔的并发梯度")
    parser.add_argument("--requests", type=int, default=60, help="每个端点每个并发级别的总请求数")
    parser.add_argument("--identity-check", action="store_true", help="只跑并发身份串号检测")
    parser.add_argument("--identity-rounds", type=int, default=25)
    parser.add_argument("--warmup", type=int, default=8,
                        help="每个端点的预热请求数；应不小于服务端 worker 数")
    parser.add_argument("--json-out", default=None, help="把结果写成 JSON")
    args = parser.parse_args()

    if not args.account:
        args.account = ["admin@chainguard.demo"]
    if not args.password:
        args.password = ["Demo@2026"] * len(args.account)
    if len(args.password) != len(args.account):
        parser.error("--account 与 --password 数量必须一致")

    base = args.base_url.rstrip("/")

    async def run() -> int:
        async with httpx.AsyncClient() as client:
            try:
                probe = await client.get(f"{base}/healthz", timeout=10.0)
            except Exception as error:
                print(f"连不上 {base}：{error}\n请先启动服务再运行本脚本。", file=sys.stderr)
                return 2
            if probe.status_code != 200:
                print(f"{base}/healthz 返回 {probe.status_code}", file=sys.stderr)
                return 2
            sessions = [
                await _login(client, base, account, password)
                for account, password in zip(args.account, args.password)
            ]

        print(f"目标 {base}　账号 {', '.join(s['account'] for s in sessions)}")
        print("注意：本结果只对当前机器/worker 数/数据库成立，不是生产 SLA。")

        if args.identity_check:
            if len(sessions) < 2:
                print("身份串号检测需要至少两个账号（--account 传两次）", file=sys.stderr)
                return 2
            print(f"\n并发身份串号检测：{len(sessions)} 账号 × {args.identity_rounds} 轮 × 4 并发")
            checked, mismatched, transport = await _identity_check(
                base, sessions, args.identity_rounds
            )
            print(f"检查 {checked} 次，串号 {mismatched} 次，传输层失败 {transport} 次")
            if transport:
                print("  传输层失败属于客户端/网络成因，不计入串号判定。")
            return 0 if mismatched == 0 else 1

        headers = {"Authorization": f"Bearer {sessions[0]['token']}"}
        levels = [int(x) for x in args.concurrency.split(",") if x.strip()]
        results: list[Result] = []
        for name, method, path, needs_auth in DEFAULT_TARGETS:
            for level in levels:
                print(f"  压测 {name} @ 并发 {level} ...", flush=True)
                results.append(await _measure(
                    base, name, method, path,
                    headers if needs_auth else {}, level, args.requests,
                    warmup_rounds=args.warmup,
                ))
        _print_table(results)

        total_errors = sum(r.errors for r in results)
        if total_errors:
            print(f"\n注意：出现 {total_errors} 个非 2xx 响应，性能数字在有错误时不可采信。")

        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as handle:
                json.dump([
                    {
                        "target": r.target, "concurrency": r.concurrency,
                        "requests": len(r.samples), "errors": r.errors,
                        "rps": round(r.rps, 2), "p50_ms": round(r.pct(50), 2),
                        "p95_ms": round(r.pct(95), 2), "p99_ms": round(r.pct(99), 2),
                        "mean_ms": round(statistics.mean(s.elapsed_ms for s in r.samples), 2),
                    }
                    for r in results
                ], handle, ensure_ascii=False, indent=1)
            print(f"已写入 {args.json_out}")
        return 0 if total_errors == 0 else 1

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
