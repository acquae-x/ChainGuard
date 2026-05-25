import streamlit as st

from src.agents import generate_all_proposals
from src.arbitrator import arbitrate
from src.config_loader import load_risk_weights, load_thresholds
from src.conflict_detector import detect_conflict
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.inventory_monitor import calculate_inventory_risk
from src.learning import (
    generate_experience_card,
    load_experience_cards,
    save_experience_card,
)
from src.parameter_calibration import explain_simulation_limitations
from src.scoring import attach_total_scores, detect_low_score, rank_proposals


DEMO_CASE_NAME = "台风导致宁波港停运"


def find_proposal(proposals: list[dict], keyword: str) -> dict:
    for proposal in proposals:
        if keyword in proposal["agent_name"]:
            return proposal
    raise ValueError(f"未找到 {keyword} 对应的 Agent 方案。")


def render_sidebar() -> None:
    st.sidebar.header("演示控制台")
    st.sidebar.selectbox("演示案例选择", [DEMO_CASE_NAME], index=0)

    st.sidebar.markdown("### 参数说明")
    st.sidebar.info(
        "当前使用模拟参数和专家经验权重。真实落地时，可接入企业 ERP/WMS/TMS "
        "历史数据，对库存风险权重、预警阈值和评分规则进行校准。"
    )

    if st.sidebar.button("运行完整应急决策流程", type="primary", use_container_width=True):
        st.session_state["workflow_has_run"] = True

    if st.session_state.get("workflow_has_run", True):
        st.sidebar.success("完整流程已就绪，可按 Step 1-7 演示。")


def render_header() -> None:
    st.title("ChainGuard 供应链应急响应系统")
    st.subheader("库存监控 × 多源感知 × 辩论仲裁 × 经验自学习")
    st.info("当前为初赛 MVP 演示版，使用模拟数据和专家经验参数。")


def render_step_1(inventory: dict, inventory_risk: dict) -> None:
    st.header("Step 1 库存监控与风险预警")

    cols = st.columns(3)
    cols[0].metric("库存可支撑小时数", f"{inventory_risk['support_hours']:.0f} 小时")
    cols[1].metric("安全库存缺口率", f"{inventory_risk['safety_stock_gap_rate']:.1%}")
    cols[2].metric("库存风险指数", f"{inventory_risk['inventory_risk_index']:.1f}")

    detail_cols = st.columns(4)
    detail_cols[0].metric("当前库存", f"{inventory['current_stock']:,}")
    detail_cols[1].metric("小时消耗", f"{inventory['hourly_consumption']:,}")
    detail_cols[2].metric("在途延误", f"{inventory_risk['transit_delay_hours']:.0f} 小时")
    detail_cols[3].metric("关键订单覆盖率", f"{inventory_risk['critical_order_coverage_rate']:.0%}")

    if inventory_risk["should_trigger_response"]:
        st.error(
            f"{inventory_risk['warning_level']}：库存风险指数 "
            f"{inventory_risk['inventory_risk_index']:.1f} 已超过触发阈值，建议启动应急决策。"
        )
    else:
        st.success("库存风险尚未触发应急决策。")

    with st.expander("查看风险解释", expanded=True):
        for item in inventory_risk["explanation"]:
            st.write(f"- {item}")


def render_step_2(context: dict) -> None:
    st.header("Step 2 态势事件卡片")

    event = context["events"][0]
    inventory = context["inventory"]
    suppliers = context["suppliers"]
    supplier_a = next(item for item in suppliers if item["supplier_id"] == "SUP-A")

    cols = st.columns(3)
    with cols[0]:
        st.container(border=True).markdown(
            f"**台风事件**\n\n{event['description']}\n\n外部风险分：**{event['external_risk_score']}**"
        )
    with cols[1]:
        st.container(border=True).markdown(
            f"**港口停运**\n\n受影响路线：{event['affected_route']}\n\n当前位置：**{event['location']}**"
        )
    with cols[2]:
        st.container(border=True).markdown(
            f"**A供应商延误**\n\n供应商状态：{supplier_a['status']}\n\n预计延误：**{supplier_a['delay_hours']} 小时**"
        )

    st.caption(
        f"监控物料：{inventory['material_name']}（{inventory['material_id']}），"
        f"当前库存 {inventory['current_stock']}，关键订单需求 {inventory['critical_order_demand']}。"
    )


def render_step_3(proposals: list[dict], low_score_threshold: float) -> None:
    st.header("Step 3 多 Agent 决策提案")

    score_labels = {
        "timeliness": "时效",
        "cost": "成本",
        "risk_reduction": "降险",
        "feasibility": "可行",
        "service_level": "服务",
    }

    columns = st.columns(3)
    for column, proposal in zip(columns, proposals, strict=True):
        with column:
            with st.container(border=True):
                st.markdown(f"### {proposal['agent_name']}")
                st.caption(proposal["role"])
                st.markdown(f"**{proposal['proposal_title']}**")
                st.metric("总分", f"{proposal['total_score']:.1f}")
                if detect_low_score(proposal, low_score_threshold):
                    st.warning("需要复盘")

                st.write(proposal["proposal"])

                st.markdown("**理由**")
                for item in proposal["reasoning"]:
                    st.write(f"- {item}")

                st.markdown("**风险**")
                for item in proposal["risks"]:
                    st.write(f"- {item}")

                st.markdown("**行动**")
                for item in proposal["actions"]:
                    st.write(f"- {item}")

                st.markdown("**评分**")
                for key, label in score_labels.items():
                    st.write(f"- {label}: {proposal['scores'][key]}")


def render_step_4(proposals: list[dict], conflict: dict, low_score_threshold: float) -> None:
    st.header("Step 4 方案评分与冲突检测")

    ranked = rank_proposals(proposals)
    highest = ranked[0]
    lowest = ranked[-1]

    score_rows = []
    for index, proposal in enumerate(ranked, start=1):
        score_rows.append(
            {
                "排名": index,
                "Agent": proposal["agent_name"],
                "方案": proposal["proposal_title"],
                "总分": proposal["total_score"],
                "标注": "最高分" if proposal is highest else "最低分" if proposal is lowest else "",
                "复盘状态": "需要复盘" if detect_low_score(proposal, low_score_threshold) else "通过",
            }
        )
    st.dataframe(score_rows, use_container_width=True, hide_index=True)

    cols = st.columns(3)
    cols[0].metric("最高分方案", highest["agent_name"], f"{highest['total_score']:.1f}")
    cols[1].metric("最低分方案", lowest["agent_name"], f"{lowest['total_score']:.1f}")
    cols[2].metric("分差", f"{conflict['score_gap']:.1f}")

    if conflict["has_conflict"]:
        st.warning(f"触发辩论仲裁：{conflict['conflict_summary']}")
    else:
        st.success("未触发辩论仲裁。")

    with st.expander("冲突检测原因", expanded=True):
        for reason in conflict["reasons"]:
            st.write(f"- {reason}")


def render_step_5(rebuttal: dict) -> None:
    st.header("Step 5 辩论过程")

    cols = st.columns(2)
    cols[0].metric("反驳方", rebuttal["debater"])
    cols[1].metric("被反驳方", rebuttal["target"])

    with st.container(border=True):
        st.markdown("**反驳点**")
        for point in rebuttal["rebuttal_points"]:
            st.write(f"- {point}")

        st.markdown("**折中建议**")
        st.write(rebuttal["suggested_revision"])

        st.markdown("**接受的业务取舍**")
        st.write(rebuttal["accepted_tradeoff"])


def render_step_6(arbitration: dict) -> None:
    st.header("Step 6 仲裁决策")

    with st.container(border=True):
        st.markdown(f"### {arbitration['final_decision_title']}")
        st.metric("最终评分", f"{arbitration['final_score']:.1f}")
        st.write(arbitration["final_strategy"])

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**采纳意见**")
        for item in arbitration["adopted_opinions"]:
            st.write(f"- {item}")
    with cols[1]:
        st.markdown("**拒绝意见**")
        for item in arbitration["rejected_opinions"]:
            st.write(f"- {item}")

    st.markdown("**执行清单**")
    for index, item in enumerate(arbitration["execution_plan"], start=1):
        st.write(f"{index}. {item}")

    st.markdown("**人工确认点**")
    for item in arbitration["manual_confirmation_points"]:
        st.write(f"- {item}")

    st.markdown("**预期效果**")
    st.dataframe(
        [
            {"维度": "行动后库存支撑", "预期": arbitration["expected_effect"]["support_hours_after_action"]},
            {"维度": "交付风险", "预期": arbitration["expected_effect"]["delivery_risk"]},
            {"维度": "成本风险", "预期": arbitration["expected_effect"]["cost_risk"]},
            {"维度": "客户影响", "预期": arbitration["expected_effect"]["customer_impact"]},
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_step_7(card: dict) -> None:
    st.header("Step 7 自学习经验卡片")

    with st.container(border=True):
        st.markdown(f"### {card['recommended_pattern']}")
        st.caption(f"case_id: {card['case_id']}")
        st.write(f"**场景：** {card['scenario']}")

        st.markdown("**触发条件**")
        for item in card["trigger_conditions"]:
            st.write(f"- {item}")

        st.write(f"**失败原因：** {card['failed_reason']}")
        st.write(f"**改进策略：** {card['improvement_strategy']}")
        st.write(f"**参数说明：** {card['parameter_note']}")
        st.write(f"**标签：** {'，'.join(card['tags'])}")

    if st.button("保存经验卡片", use_container_width=True):
        result = save_experience_card(card)
        st.success(f"经验卡片已保存到 {result['path']}，当前共 {result['saved_count']} 张。")

    saved_cards = load_experience_cards()
    st.markdown("**已保存经验列表**")
    if saved_cards:
        st.dataframe(
            [
                {
                    "case_id": item["case_id"],
                    "scenario": item["scenario"],
                    "recommended_pattern": item["recommended_pattern"],
                    "tags": "，".join(item["tags"]),
                }
                for item in saved_cards
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("尚未保存经验卡片。")


def main() -> None:
    st.set_page_config(page_title="ChainGuard 演示模式", page_icon="CG", layout="wide")
    render_sidebar()
    render_header()

    try:
        risk_weights = load_risk_weights()
        thresholds = load_thresholds()
        context = load_demo_context()
        inventory_risk = calculate_inventory_risk(context["inventory"], risk_weights, thresholds)
        proposals = attach_total_scores(
            generate_all_proposals(context),
            risk_weights["decision_score_weights"],
        )
        low_score_threshold = thresholds["learning"]["low_score_threshold"]
        conflict = detect_conflict(proposals, thresholds)
        rebuttal = generate_rebuttal(
            find_proposal(proposals, "物流"),
            find_proposal(proposals, "财务"),
            context,
        )
        arbitration = arbitrate(proposals, conflict, rebuttal, context)
        experience_card = generate_experience_card(context, proposals, arbitration)
    except (FileNotFoundError, ValueError) as error:
        st.error(str(error))
        st.stop()

    render_step_1(context["inventory"], inventory_risk)
    render_step_2(context)
    render_step_3(proposals, low_score_threshold)
    render_step_4(proposals, conflict, low_score_threshold)
    render_step_5(rebuttal)
    render_step_6(arbitration)
    render_step_7(experience_card)

    st.divider()
    st.warning(explain_simulation_limitations())


if __name__ == "__main__":
    main()
