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
) -> dict[str, Any]:
    inventory = context["inventory"]
    event = context["events"][0]

    return {
        "case_id": f"{event['event_id']}-{inventory['material_id']}",
        "scenario": "台风导致港口停运，库存仅支撑36小时",
        "trigger_conditions": [
            "库存可支撑时间 < 48小时",
            "港口关闭或供应商延误 > 48小时",
            "空运成本可能超过订单毛利30%",
        ],
        "failed_reason": "如果采用全量空运，会过度关注时效，忽略订单毛利和客户分级。",
        "improvement_strategy": "未来类似场景中，不应默认全量空运，应优先采用客户分级保障策略。",
        "recommended_pattern": "备用供应商 + 关键订单空运 + 非关键订单延期",
        "tags": [
            "台风",
            "港口停运",
            "库存不足",
            "供应商延误",
            "客户分级保障",
            "空运成本",
        ],
        "parameter_note": "当前经验卡片基于模拟数据生成，真实落地时应结合企业历史应急结果校准。",
        "source_agents": [proposal["agent_name"] for proposal in proposals],
        "final_decision_title": arbitration_result["final_decision_title"],
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
