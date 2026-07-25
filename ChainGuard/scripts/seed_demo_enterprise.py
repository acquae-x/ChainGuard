"""把企业演示 CSV 导入**已存在的租户**，用于演示/答辩前铺数据。

为什么需要这个脚本：

- ``scripts/phase5b_c2_acceptance.py`` 是验收用的，它强制 ``CHAINGUARD_REQUIRE_GUID_DB``
  且会自建租户，打不到演示库。
- ``scripts/enterprise_import.py`` 导的是决策内核的**场景库**
  （demo_assets/enterprise/database/*.db），不是多租户 Web 库的业务表。

演示租户默认只有 1 个可计算物料，低于节点健康相对轨的最小样本量（8），界面会显示
「已回退为专家阈值」——数据驱动阈值那条能力在演示里根本不会出现。导入企业数据
（materials.csv 共 240 行）之后相对轨才会激活。

用法（服务停掉再跑，避免与运行中的进程抢 SQLite 写锁）：

    python scripts/seed_demo_enterprise.py \
        --database chainguard-demo.db \
        --tenant-id tenant-demo

默认按 ``--dry-run`` 之外的真实写入执行；先加 ``--dry-run`` 看会导入什么。
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="向现有租户导入企业演示数据")
    parser.add_argument("--database", type=Path, required=True, help="目标 SQLite 库路径")
    parser.add_argument("--tenant-id", required=True, help="已存在的租户 id，例如 tenant-demo")
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT / "demo_assets" / "enterprise" / "csv",
        help="企业 CSV 目录",
    )
    parser.add_argument("--job-id", default=None, help="导入批次 id；缺省自动生成")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.exists():
        print(f"库不存在：{database}", file=sys.stderr)
        return 2
    if not args.data_dir.exists():
        print(f"数据目录不存在：{args.data_dir}", file=sys.stderr)
        return 2

    # DATABASE_URL 必须在导入 DB 相关模块**之前**落定，否则 SessionLocal 会绑到
    # 仓库默认库上——这正是 phase5b_c2_acceptance.py 里那段注释在防的事。
    os.environ["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    os.environ.setdefault("CHAINGUARD_DISABLE_SCHEDULER", "1")
    os.environ.setdefault("JWT_SECRET", "seed-only-not-for-deployment")
    os.environ.setdefault("CHAINGUARD_ENCRYPTION_KEY", "seed-only-not-for-deployment")

    from src.webapi.database import SessionLocal
    from src.webapi.entity_import import import_enterprise_directory
    from src.webapi.models import ImportJob, Material, Tenant

    job_id = args.job_id or f"import-demo-{uuid.uuid4().hex[:12]}"

    with SessionLocal() as db:
        tenant = db.get(Tenant, args.tenant_id)
        if tenant is None:
            print(f"租户不存在：{args.tenant_id}", file=sys.stderr)
            return 2

        before = db.query(Material).filter(Material.tenant_id == args.tenant_id).count()
        print(f"租户 {args.tenant_id}　导入前物料数 {before}")

        if args.dry_run:
            csvs = sorted(p.name for p in args.data_dir.glob("*.csv"))
            print(f"[dry-run] 将从 {args.data_dir} 读取 {len(csvs)} 个 CSV：{', '.join(csvs)}")
            return 0

        # 导入需要一条 ImportJob 记录承载批次血缘，导入的行会挂在它下面。
        db.add(ImportJob(
            id=job_id,
            tenant_id=args.tenant_id,
            file_name="enterprise_demo_csv",
            import_type="entity_csv",
            status="succeeded",
            progress=100,
            requester_id="seed_demo_enterprise",
        ))
        db.commit()

        report = import_enterprise_directory(db, args.tenant_id, job_id, args.data_dir)
        db.commit()

        after = db.query(Material).filter(Material.tenant_id == args.tenant_id).count()

    print(f"导入批次 {job_id}")
    for table in sorted(report):
        entry = report[table]
        if isinstance(entry, dict) and "imported" in entry:
            print(f"  {table:<24}导入 {entry.get('imported', 0):>6}　拒绝 {entry.get('rejected', 0):>5}")
    print(f"导入后物料数 {after}（新增 {after - before}）")
    if after < 8:
        print("注意：物料数仍低于 8，节点健康的相对轨不会激活，界面会显示已回退专家阈值。")
    else:
        print("物料数已满足相对轨最小样本量（8），节点健康会显示数据推导的离群线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
