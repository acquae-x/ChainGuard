import json
from pathlib import Path
from typing import Any

from src.vector_store import get_vector_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return PROJECT_ROOT / target


def generate_experience_card(
    context: dict[str, Any],
    proposals: list[dict[str, Any]],
    arbitration_result: dict[str, Any],
    retrieval_result: Any | None = None,
) -> dict[str, Any]:
    inventory = context["inventory"]
    events = context.get("events") or [{}]
    event = events[0]
    hourly_consumption = max(float(inventory.get("hourly_consumption", 0.01)), 0.01)
    current_stock = float(inventory.get("current_stock", 0.0))
    safety_stock = float(inventory.get("safety_stock", 0.0))
    support_hours = current_stock / hourly_consumption
    safety_gap = max(safety_stock - current_stock, 0.0)
    delay_hours = float(
        event.get(
            "estimated_delay_hours",
            event.get("delay_hours", 0.0),
        )
        or 0.0
    )
    event_label = event.get("title") or event.get("event_type") or event.get("type") or "未知事件"
    affected_supplier = event.get("affected_supplier") or "主供应商"
    tags = sorted(
        {
            str(event.get("event_type") or event.get("type") or ""),
            str(event.get("severity") or ""),
            str(inventory.get("material_name") or ""),
            "库存不足" if safety_gap > 0 else "库存充足",
            "客户分级保障",
        }
        - {""}
    )
    historical_references = []
    confidence_adjustment = 0.0
    if retrieval_result is not None:
        confidence_adjustment = float(getattr(retrieval_result, "confidence_adjustment", 0.0))
        historical_references = [
            {
                "case_id": reference.case_id,
                "scenario": reference.scenario,
                "recommended_pattern": reference.recommended_pattern,
            }
            for reference in getattr(retrieval_result, "references", [])
        ]

    return {
        "case_id": f"{event.get('event_id', 'UNKNOWN')}-{inventory['material_id']}",
        "scenario": (
            f"{event_label} 导致 {affected_supplier} 受影响，"
            f"库存支撑约 {support_hours:.0f} 小时"
        ),
        "trigger_conditions": [
            f"库存可支撑时间 ≤ {support_hours:.0f} 小时",
            f"安全库存缺口 {safety_gap:.0f} 件",
            f"供应商延误约 {delay_hours:.0f} 小时",
        ],
        "failed_reason": "如果采用全量空运，会过度关注时效，忽略订单毛利和客户分级。",
        "improvement_strategy": "未来类似场景中，不应默认全量空运，应优先采用客户分级保障策略。",
        "recommended_pattern": "备用供应商 + 关键订单空运 + 非关键订单延期",
        "tags": tags,
        "parameter_note": "当前经验卡片基于模拟数据生成，真实落地时应结合企业历史应急结果校准。",
        "source_agents": [proposal["agent_name"] for proposal in proposals],
        "final_decision_title": arbitration_result["final_decision_title"],
        "confidence_score": round(0.5 + confidence_adjustment, 2),
        "historical_references": historical_references,
    }


def load_experience_cards(path: str | Path = "data/experience_cards.json") -> list[dict[str, Any]]:
    card_path = _resolve_path(path)
    if not card_path.exists():
        return []

    try:
        data = json.loads(card_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"经验卡片 JSON 格式错误：{card_path}，{error}") from error

    if not isinstance(data, list):
        raise ValueError(f"经验卡片文件必须是列表：{card_path}")
    return data


def save_experience_card(
    card: dict[str, Any],
    path: str | Path = "data/experience_cards.json",
) -> dict[str, Any]:
    card_path = _resolve_path(path)
    card_path.parent.mkdir(parents=True, exist_ok=True)

    cards = load_experience_cards(card_path)
    existing_index = next(
        (index for index, item in enumerate(cards) if item.get("case_id") == card.get("case_id")),
        None,
    )
    if existing_index is None:
        cards.append(card)
    else:
        cards[existing_index] = card

    card_path.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "path": str(card_path),
        "saved_count": len(cards),
        "case_id": card.get("case_id", ""),
    }


def search_similar_experiences(
    query: str,
    path: str | Path = "data/experience_cards.json",
) -> list[dict[str, Any]]:
    return get_vector_store(mode="simple", path=path).search(query)


def card_from_historical_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert one historical_decisions row to experience card format."""
    case_id = str(record.get("case_id") or "").strip()
    scenario = str(record.get("scenario") or "").strip()
    selected_strategy = str(record.get("selected_strategy") or "").strip()
    outcome_status = str(record.get("outcome_status") or "").strip()
    lessons_learned = str(record.get("lessons_learned") or "").strip()

    try:
        human_rating = int(record.get("human_rating", ""))
    except (TypeError, ValueError):
        confidence_score = 0.5
    else:
        confidence_score = round(human_rating / 5.0, 2) if 1 <= human_rating <= 5 else 0.5

    trigger_conditions = []
    numeric_fields = [
        ("covered_demand_rate", "历史需求覆盖率", "{:.0%}"),
        ("actual_cost", "实际成本", "{:.0f}"),
        ("actual_delay_hours", "实际延误", "{:.0f}h"),
    ]
    for field_name, label, formatter in numeric_fields:
        try:
            value = float(record.get(field_name, ""))
        except (TypeError, ValueError):
            rendered = "N/A"
        else:
            rendered = formatter.format(value)
        trigger_conditions.append(f"{label} {rendered}")

    failed_reason = ""
    if outcome_status == "failed":
        failed_reason = f"历史决策失败：{lessons_learned or '未记录原因'}"

    tags = sorted(
        {
            scenario[:20],
            selected_strategy[:20],
            outcome_status,
        }
        - {""}
    )

    return {
        "case_id": case_id,
        "scenario": scenario,
        "trigger_conditions": trigger_conditions,
        "failed_reason": failed_reason,
        "improvement_strategy": lessons_learned or "未记录",
        "recommended_pattern": selected_strategy,
        "tags": tags,
        "parameter_note": "来源：历史决策数据库批量转换",
        "source_agents": ["历史批量"],
        "final_decision_title": f"历史决策：{selected_strategy}",
        "confidence_score": confidence_score,
        "historical_references": [],
    }


def build_experience_cards_from_history(
    records: list[dict[str, Any]],
    *,
    path: str | Path = "data/experience_cards.json",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Batch convert historical records to experience cards with deduplication."""
    existing_cards = load_experience_cards(path)
    existing_ids = {str(card.get("case_id") or "") for card in existing_cards}

    added = 0
    skipped = 0
    for record in records:
        if not str(record.get("case_id") or "").strip():
            skipped += 1
            continue

        card = card_from_historical_record(record)
        if not overwrite and card["case_id"] in existing_ids:
            skipped += 1
            continue

        save_experience_card(card, path)
        existing_ids.add(card["case_id"])
        added += 1

    return {
        "added": added,
        "skipped": skipped,
        "total_after": len(load_experience_cards(path)),
    }
