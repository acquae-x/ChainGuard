from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.data_source import enterprise_source, tenant_scenario_db_path


@dataclass(frozen=True)
class IngestResult:
    tenant_id: str
    db_path: str
    table_results: list[dict[str, Any]]
    ok_tables: int
    smoke_ok: bool
    smoke_message: str
    preflight: dict[str, Any] | None
    reconciled: bool
    csv_rows: int
    db_rows: int


def import_tenant_from_dir(
    tenant_id: str,
    data_dir: str,
    *,
    batch_size: int = 10000,
    run_preflight_check: bool = True,
    progress: Callable[[str, int], None] | None = None,
) -> IngestResult:
    """
    把 data_dir 下的企业 CSV 导入租户库并做冒烟校验。

    步骤：
      1. run_import(data_dir, 租户库路径, overwrite=True)
      2. 冒烟：ScenarioLoader(租户库, tenant_id).list_scenarios() 非空
         且 load_context(首个事件) 不抛异常
    冒烟失败时 smoke_ok=False，调用方不得激活该数据源。
    """
    from src.import_preflight import run_preflight
    from src.streaming_import import create_indexes, reconcile, stream_import_csv

    source = enterprise_source(tenant_id, require_exists=False)
    tenant_id = source.tenant_id
    db_path = tenant_scenario_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    csv_paths = sorted(Path(data_dir).glob("*.csv"), key=lambda p: p.stem.lower())
    preflight_report = run_preflight(csv_paths, db_path) if run_preflight_check else None
    preflight = asdict(preflight_report) if preflight_report is not None else None
    if preflight_report is not None and not preflight_report.can_proceed:
        return IngestResult(
            tenant_id=tenant_id,
            db_path=str(db_path),
            table_results=[],
            ok_tables=0,
            smoke_ok=False,
            smoke_message="容量预检未通过，已阻止导入；数据库未写入。",
            preflight=preflight,
            reconciled=False,
            csv_rows=0,
            db_rows=0,
        )

    table_results: list[dict[str, Any]] = []
    for csv_path in csv_paths:
        table_name = csv_path.stem.lower()
        warning = ""
        status = "ok"
        rows_imported = 0
        indexes: list[str] = []
        reconciled = False
        csv_rows = 0
        db_rows = 0
        try:
            rows_imported = stream_import_csv(
                csv_path,
                table_name,
                db_path,
                batch_size=batch_size,
                overwrite=True,
                progress=(
                    (lambda rows, name=table_name: progress(name, rows))
                    if progress is not None
                    else None
                ),
            )
            indexes = create_indexes(db_path, table_name)
            reconciled, csv_rows, db_rows = reconcile(csv_path, table_name, db_path)
            if not reconciled:
                status = "mismatch"
                warning = f"对账不一致：CSV {csv_rows} 行，数据库 {db_rows} 行"
        except Exception as exc:  # noqa: BLE001
            status = "skipped"
            warning = str(exc)

        table_results.append(
            {
                "table": table_name,
                "status": status,
                "rows": rows_imported,
                "warning": warning,
                "indexes": indexes,
                "reconciled": reconciled,
                "csv_rows": csv_rows,
                "db_rows": db_rows,
            }
        )

    ok_tables = sum(1 for r in table_results if r["status"] == "ok")
    all_reconciled = all(r["reconciled"] for r in table_results) if table_results else True
    total_csv_rows = sum(int(r["csv_rows"]) for r in table_results)
    total_db_rows = sum(int(r["db_rows"]) for r in table_results)

    smoke_ok, smoke_message = _smoke_check(tenant_id, db_path)
    if not all_reconciled:
        smoke_ok = False
        smoke_message = f"{smoke_message}；对账不一致，请检查 table_results 中的 csv_rows/db_rows。"
    return IngestResult(
        tenant_id=tenant_id,
        db_path=str(db_path),
        table_results=table_results,
        ok_tables=ok_tables,
        smoke_ok=smoke_ok,
        smoke_message=smoke_message,
        preflight=preflight,
        reconciled=all_reconciled,
        csv_rows=total_csv_rows,
        db_rows=total_db_rows,
    )


def _smoke_check(tenant_id: str, db_path: Path) -> tuple[bool, str]:
    import gc

    from src.scenario_loader import ScenarioLoader

    try:
        loader = ScenarioLoader(db_path, tenant_id="default")
        scenarios = loader.list_scenarios(limit=5)
        if not scenarios:
            gc.collect()
            return False, "导入完成但未发现可用事件（disruption_events 为空）"
        loader.load_context(scenarios[0]["event_id"])
        gc.collect()
        return True, f"冒烟校验通过：可加载 {len(scenarios)} 个事件，首个事件 context 正常"
    except Exception as exc:  # noqa: BLE001
        gc.collect()
        return False, f"冒烟校验失败：{exc}"
