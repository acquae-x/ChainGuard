from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.data_source import enterprise_source, tenant_scenario_db_path


@dataclass(frozen=True)
class IngestResult:
    tenant_id: str
    db_path: str
    table_results: list[dict[str, Any]]
    ok_tables: int
    smoke_ok: bool
    smoke_message: str


def import_tenant_from_dir(tenant_id: str, data_dir: str) -> IngestResult:
    """
    把 data_dir 下的企业 CSV 导入租户库并做冒烟校验。

    步骤：
      1. run_import(data_dir, 租户库路径, overwrite=True)
      2. 冒烟：ScenarioLoader(租户库, tenant_id).list_scenarios() 非空
         且 load_context(首个事件) 不抛异常
    冒烟失败时 smoke_ok=False，调用方不得激活该数据源。
    """
    from scripts.enterprise_import import run_import

    source = enterprise_source(tenant_id, require_exists=False)
    tenant_id = source.tenant_id
    db_path = tenant_scenario_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    results = run_import(str(data_dir), str(db_path), dry_run=False, overwrite=True)
    table_results = [
        {
            "table": r.table_name,
            "status": r.status,
            "rows": r.rows_imported,
            "warning": r.warning,
        }
        for r in results
    ]
    ok_tables = sum(1 for r in results if r.status == "ok")

    smoke_ok, smoke_message = _smoke_check(tenant_id, db_path)
    return IngestResult(
        tenant_id=tenant_id,
        db_path=str(db_path),
        table_results=table_results,
        ok_tables=ok_tables,
        smoke_ok=smoke_ok,
        smoke_message=smoke_message,
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
