from typing import Any


Proposal = dict[str, Any]


def _find_by_name(items: list[dict[str, Any]], keyword: str) -> dict[str, Any]:
    for item in items:
        searchable = " ".join(str(value) for value in item.values())
        if keyword in searchable:
            return item
    return {}


class ProcurementAgent:
    agent_name = "采购 Agent"
    role = "供应商替代、采购周期、供货稳定性"

    def generate_proposal(self, context: dict[str, Any]) -> Proposal:
        inventory = context["inventory"]
        suppliers = context["suppliers"]
        supplier_a = _find_by_name(suppliers, "A供应商")
        supplier_b = _find_by_name(suppliers, "B备用供应商")
        supplier_c = _find_by_name(suppliers, "C第二备用供应商")

        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "proposal_title": "启用B备用供应商进行紧急补货",
            "proposal": (
                f"针对 {inventory['material_name']} 的库存缺口，立即启用B备用供应商进行紧急补货，"
                "优先覆盖A类关键客户订单，同时保留C供应商作为兜底来源。"
            ),
            "reasoning": [
                f"A供应商受台风影响，预计延误 {supplier_a.get('delay_hours', 72)} 小时，无法覆盖48小时交付窗口。",
                f"B备用供应商可供 {supplier_b.get('available_qty', 0)} 件，交期约 {supplier_b.get('lead_time_hours', 0)} 小时，能较快补齐关键缺口。",
                f"C第二备用供应商可供 {supplier_c.get('available_qty', 0)} 件，虽然交期更长，但适合作为第二层兜底。",
            ],
            "risks": [
                "B供应商成本高于A供应商，会抬升应急采购成本。",
                "B供应商可供量仍需在2小时内确认，否则可能影响关键订单覆盖。",
                "C供应商供货少且交期更长，只能作为兜底而非主方案。",
            ],
            "actions": [
                "2小时内确认B供应商可供量。",
                "锁定关键物料M-AX100的应急采购批次。",
                "准备C供应商兜底询价和小批量采购计划。",
            ],
            "scores": {
                "timeliness": 82,
                "cost": 68,
                "risk_reduction": 86,
                "feasibility": 88,
                "service_level": 84,
            },
        }


class LogisticsAgent:
    agent_name = "物流 Agent"
    role = "运输时效、路线风险、交付保障"

    def generate_proposal(self, context: dict[str, Any]) -> Proposal:
        inventory = context["inventory"]
        event = context["events"][0]
        air_option = _find_by_name(context["transport_options"], "空运")

        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "proposal_title": "对受影响订单执行紧急空运",
            "proposal": (
                f"对受影响的 {inventory['material_name']} 订单执行全量紧急空运，"
                "用最短运输时效压缩宁波港停运和A供应商延误带来的交付风险。"
            ),
            "reasoning": [
                f"{event['title']}，海运链路当前不可用，继续等待会扩大断供风险。",
                f"空运预计 {air_option.get('estimated_hours', 18)} 小时，是当前最快的替代运输方式。",
                "关键客户订单48小时后交付，物流侧应优先保证交付时效。",
            ],
            "risks": [
                "全量空运成本显著高于常规运输，可能引发财务方案冲突。",
                "若全量空运覆盖低毛利订单，可能导致部分订单利润转负。",
                "空运舱位需要立即确认，否则时效优势会下降。",
            ],
            "actions": [
                "立即锁定空运舱位和提货窗口。",
                "将受影响订单按交期排序，先安排48小时内交付订单。",
                "同步采购侧确认B供应商货源是否可直接转空运。",
            ],
            "scores": {
                "timeliness": 96,
                "cost": 32,
                "risk_reduction": 92,
                "feasibility": 76,
                "service_level": 94,
            },
        }


class FinanceAgent:
    agent_name = "财务 Agent"
    role = "应急成本、订单毛利、违约损失"

    def generate_proposal(self, context: dict[str, Any]) -> Proposal:
        orders = context["orders"]
        high_priority_orders = [order for order in orders if order["priority"] == "A"]
        low_margin_orders = [order for order in orders if order["priority"] in {"B", "C"}]

        return {
            "agent_name": self.agent_name,
            "role": self.role,
            "proposal_title": "反对全量空运，建议客户分级保障",
            "proposal": (
                "不建议对所有受影响订单执行全量空运。应按客户优先级、违约损失和订单毛利分级保障，"
                "优先保障A类关键客户，对B/C类订单采用延期协商、分批交付或较低成本运输组合。"
            ),
            "reasoning": [
                f"A类关键订单数量为 {len(high_priority_orders)}，应优先投入高成本资源保障履约。",
                f"B/C类订单数量为 {len(low_margin_orders)}，不宜默认使用最高成本方案。",
                "全量空运会显著增加应急成本，可能吞噬普通订单毛利。",
            ],
            "risks": [
                "若完全否定空运，A类关键客户可能出现违约风险。",
                "若全量空运，部分低毛利订单可能利润转负。",
                "分级保障需要销售侧及时与客户沟通，否则会带来服务体验风险。",
            ],
            "actions": [
                "先计算A/B/C订单的毛利、罚金和空运成本承受上限。",
                "仅对A类关键客户和高罚金订单启用空运。",
                "对B/C订单采用铁路、陆运或分批交付方案，并准备客户沟通口径。",
            ],
            "scores": {
                "timeliness": 72,
                "cost": 90,
                "risk_reduction": 78,
                "feasibility": 86,
                "service_level": 80,
            },
        }


def generate_all_proposals(context: dict[str, Any]) -> list[Proposal]:
    agents = [
        ProcurementAgent(),
        LogisticsAgent(),
        FinanceAgent(),
    ]
    return [agent.generate_proposal(context) for agent in agents]
