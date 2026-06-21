import json

import streamlit as st

from src.learning import (
    load_experience_cards,
    save_experience_card,
)
from src.orchestrator import DecisionOrchestrator
from src.parameter_calibration import explain_simulation_limitations
from src.scenario_loader import ScenarioLoader
from src.scoring import detect_low_score, rank_proposals
from src.sensitivity import run_sensitivity


def render_sidebar() -> tuple[str, str | None]:
    with st.sidebar:
        st.header("演示控制台")

        st.markdown("### 参数说明")
        st.info(
            "当前使用模拟参数和专家经验权重。真实落地时，可接入企业 ERP/WMS/TMS "
            "历史数据，对库存风险权重、预警阈值和评分规则进行校准。"
        )

        if st.button("运行完整应急决策流程", type="primary", use_container_width=True):
            st.session_state["workflow_has_run"] = True

        if st.session_state.get("workflow_has_run", True):
            st.success("完整流程已就绪，可按 Step 1-11 演示。")

        st.divider()
        st.subheader("场景模式")
        scenario_mode = st.radio(
            "选择运行场景",
            ["演示场景（台风-宁波港）", "企业真实场景"],
            index=0,
            key="scenario_mode",
            label_visibility="collapsed",
        )

        enterprise_event_id = None
        if scenario_mode == "企业真实场景":
            from src.scenario_loader import ScenarioLoader

            try:
                _loader_for_list = ScenarioLoader()
                _event_list = _loader_for_list.list_scenarios(limit=50)
                _event_options = {
                    f"{e['event_id']} · {e['event_title']} [{e['severity']}]": e["event_id"]
                    for e in _event_list
                }
                _selected_label = st.selectbox(
                    "选择事件",
                    list(_event_options.keys()),
                    key="enterprise_event_select",
                )
                enterprise_event_id = _event_options.get(_selected_label)
            except Exception as _e:
                st.error(f"企业数据库加载失败：{_e}")
                enterprise_event_id = None

    return scenario_mode, enterprise_event_id


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
    affected_supplier_id = event.get("affected_supplier")
    affected_supplier = next(
        (
            item
            for item in suppliers
            if item.get("supplier_id") == affected_supplier_id
        ),
        None,
    )

    cols = st.columns(3)
    with cols[0]:
        st.container(border=True).markdown(
            f"**{event['title']}**\n\n{event['description']}\n\n"
            f"外部风险分：**{event['external_risk_score']}**"
        )
    with cols[1]:
        st.container(border=True).markdown(
            f"**事件影响范围**\n\n受影响路线：{event['affected_route']}\n\n"
            f"当前位置：**{event['location']}**"
        )
    with cols[2]:
        if affected_supplier:
            st.container(border=True).markdown(
                f"**受影响供应商**\n\n{affected_supplier['supplier_name']}\n\n"
                f"供应商状态：{affected_supplier['status']}\n\n"
                f"预计延误：**{affected_supplier['delay_hours']} 小时**"
            )
        elif affected_supplier_id:
            st.container(border=True).markdown(
                f"**受影响供应商**\n\n{affected_supplier_id}\n\n"
                "该供应商未列入当前物料的合格供应商清单。\n\n"
                f"预计延误：**{event.get('estimated_delay_hours', 0)} 小时**"
            )
        else:
            st.container(border=True).markdown(
                "**受影响供应商**\n\n当前物料没有合格供应商记录。"
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


def render_step_6(
    arbitration: dict,
    proposals: list[dict],
    conflict: dict,
    rebuttal: dict,
) -> None:
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
    _effect = arbitration.get("expected_effect", {})
    st.dataframe(
        [
            {"维度": "供应连续性", "预期": _effect.get("supply_continuity", "—")},
            {"维度": "交付风险", "预期": _effect.get("delivery_risk", "—")},
            {"维度": "成本风险", "预期": _effect.get("cost_risk", "—")},
            {"维度": "客户影响", "预期": _effect.get("customer_impact", "—")},
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("仲裁推导过程", expanded=False):
        st.markdown("**Step 1 · 评分排名**")
        ranked = sorted(
            proposals,
            key=lambda p: float(p.get("total_score", 0)),
            reverse=True,
        )
        st.dataframe(
            [
                {
                    "排名": i + 1,
                    "Agent": p.get("agent_name", ""),
                    "总分": round(float(p.get("total_score", 0)), 2),
                }
                for i, p in enumerate(ranked)
            ],
            use_container_width=True,
            hide_index=True,
        )
        best_score = float(ranked[0].get("total_score", 0)) if ranked else 0.0

        st.markdown("**Step 2 · 冲突检测**")
        has_conflict = bool(conflict.get("has_conflict", False))
        score_gap = float(conflict.get("score_gap", 0))
        conflict_penalty = 2 if has_conflict else 0
        col_a, col_b = st.columns(2)
        col_a.metric("最高最低分差距", f"{score_gap:.1f} 分")
        col_b.metric("冲突惩罚", f"-{conflict_penalty}", delta_color="off")
        if has_conflict:
            st.warning(f"检测到方案冲突（差距 {score_gap:.1f} 分），扣 {conflict_penalty} 分。")
        else:
            st.success("未检测到方案冲突，无扣分。")

        st.markdown("**Step 3 · 辩论反驳**")
        has_rebuttal = bool(rebuttal.get("suggested_revision"))
        rebuttal_bonus = 4 if has_rebuttal else 0
        col_c, col_d = st.columns(2)
        col_c.metric("反驳建议", "已提出" if has_rebuttal else "未触发")
        col_d.metric("反驳加分", f"+{rebuttal_bonus}", delta_color="off")

        st.markdown("**Step 4 · 分数推导**")
        final_score = float(arbitration.get("final_score", 0))
        st.code(
            f"final_score = {best_score:.2f}（最高分）"
            f" + {rebuttal_bonus}（反驳）"
            f" - {conflict_penalty}（冲突）"
            f" = {final_score:.1f}",
            language=None,
        )
        computed = min(100.0, best_score + rebuttal_bonus - conflict_penalty)
        if abs(computed - final_score) > 0.15:
            st.warning(
                f"注意：推导值 {computed:.1f} 与实际 final_score {final_score:.1f} 有偏差，请检查数据。"
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


def render_step_8_constraint_debate(
    constraint_analysis: dict,
    debate_result: dict,
) -> None:
    st.header("Step 8 约束驾驶舱与多轮辩论")

    utility_before = debate_result.get(
        "system_utility_before",
        constraint_analysis.get("individual_system_utility", 0),
    )
    utility_after = debate_result.get("system_utility_after", 0)
    cols = st.columns(4)
    cols[0].metric("可行组合数", constraint_analysis.get("feasible_count", 0))
    cols[1].metric(
        "最优系统效用",
        f"{float(constraint_analysis.get('optimal_system_utility', 0)):.2f}",
    )
    cols[2].metric("辩论轮次", debate_result.get("total_rounds", 0))
    cols[3].metric(
        "系统效用变化",
        f"{float(utility_before):.2f} -> {float(utility_after):.2f}",
    )

    if constraint_analysis.get("feasible", False):
        st.success("约束求解器找到可行组合。")
    else:
        st.error("未找到完全可行组合，需要人工复核约束冲突。")

    ind_util = float(constraint_analysis.get("individual_system_utility", 0))
    opt_util = float(constraint_analysis.get("optimal_system_utility", 0))
    delta = opt_util - ind_util
    delta_pct = (delta / ind_util * 100) if ind_util > 0 else 0.0

    st.markdown("**博弈效用对比：自私选择 vs 社会最优**")
    cmp_cols = st.columns(3)
    cmp_cols[0].metric(
        "各 Agent 独立最优（自私选择）",
        f"{ind_util:.2f}",
        help="每个 Agent 各自选择最大化 own_utility 的策略，忽略协同效应",
    )
    cmp_cols[1].metric(
        "约束社会最优（ConstraintSolver）",
        f"{opt_util:.2f}",
        delta=f"+{delta:.2f}" if delta > 0 else f"{delta:.2f}",
        help="27 个组合中 system_utility 之和最大的可行方案",
    )
    cmp_cols[2].metric(
        "协调收益",
        f"{delta_pct:.1f}%",
        help="社会最优比自私选择高出的系统效用百分比",
    )
    if delta > 0:
        st.caption(
            f"ConstraintSolver 协调三个 Agent 的策略，使系统总效用提升了 "
            f"{delta:.2f} 点（+{delta_pct:.1f}%），这是各 Agent 自私选择无法达到的结果。"
        )
    elif delta == 0:
        st.caption("当前场景下，自私选择与约束社会最优策略组合一致。")

    optimal_combo = constraint_analysis.get("optimal_combo") or {}
    if optimal_combo:
        st.markdown("**最优策略组合**")
        st.dataframe(
            [
                {"agent": agent, "strategy": strategy}
                for agent, strategy in optimal_combo.items()
            ],
            use_container_width=True,
            hide_index=True,
        )

    recommended_changes = constraint_analysis.get("recommended_changes") or []
    if recommended_changes:
        with st.expander("推荐调整", expanded=True):
            for item in recommended_changes:
                st.write(f"- {item}")

    violations = constraint_analysis.get("constraint_violations") or []
    if violations:
        with st.expander("约束冲突", expanded=True):
            for item in violations:
                st.write(f"- {item}")

    rounds = debate_result.get("rounds") or []
    if rounds:
        rows = []
        for item in rounds:
            evidence = item.get("evidence") or {}
            rows.append(
                {
                    "round": item.get("round_number"),
                    "target_agent": item.get("target_agent"),
                    "action": item.get("action"),
                    "current_strategy": evidence.get("current_strategy"),
                    "recommended_strategy": evidence.get("recommended_strategy"),
                    "system_delta": evidence.get("system_utility_delta"),
                    "own_delta": item.get("own_utility_delta"),
                }
            )
        st.markdown("**辩论轮次明细**")
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("当前策略组合无需追加辩论轮次。")
    all_combos = (
        constraint_analysis.get("all_combos", [])
        if isinstance(constraint_analysis, dict)
        else getattr(constraint_analysis, "all_combos", [])
    )
    if all_combos:
        with st.expander("📊 Pareto 前沿：27 个策略组合分布", expanded=False):
            import altair as alt
            import pandas as pd

            df = pd.DataFrame(all_combos)

            def _point_type(row):
                if row["is_optimal"]:
                    return "最优选中"
                return "可行" if row["feasible"] else "不可行"

            df["类型"] = df.apply(_point_type, axis=1)
            color_scale = alt.Scale(
                domain=["最优选中", "可行", "不可行"],
                range=["#FF4B4B", "#00CC44", "#AAAAAA"],
            )
            size_scale = alt.Scale(
                domain=["最优选中", "可行", "不可行"],
                range=[200, 60, 40],
            )
            base = alt.Chart(df).encode(
                x=alt.X("cost_multiplier:Q", title="成本倍数（采购+物流）"),
                y=alt.Y("system_utility:Q", title="系统效用"),
                color=alt.Color("类型:N", scale=color_scale),
                size=alt.Size("类型:N", scale=size_scale, legend=None),
                tooltip=[
                    "label:N",
                    "cost_multiplier:Q",
                    "system_utility:Q",
                    "类型:N",
                ],
            )
            scatter = base.mark_point(filled=True, opacity=0.85)
            feasible_df = df[df["feasible"]].sort_values("cost_multiplier")
            pareto_rows = []
            max_utility = float("-inf")
            for _, row in feasible_df.iterrows():
                if row["system_utility"] > max_utility:
                    pareto_rows.append(row)
                    max_utility = row["system_utility"]
            if len(pareto_rows) > 1:
                pareto_df = pd.DataFrame(pareto_rows)
                pareto_line = (
                    alt.Chart(pareto_df)
                    .mark_line(color="#00CC44", strokeDash=[4, 2], strokeWidth=1.5)
                    .encode(x="cost_multiplier:Q", y="system_utility:Q")
                )
                chart = (scatter + pareto_line).properties(
                    width=480,
                    height=320,
                    title="27 个策略组合：成本 vs 系统效用（绿虚线 = Pareto 前沿）",
                )
            else:
                chart = scatter.properties(
                    width=480,
                    height=320,
                    title="27 个策略组合：成本 vs 系统效用",
                )

            st.altair_chart(chart, use_container_width=True)
            optimal_row = df[df["is_optimal"]]
            if not optimal_row.empty:
                row = optimal_row.iloc[0]
                st.caption(
                    f"选中组合：{row['label']} · "
                    f"成本倍数 {row['cost_multiplier']:.2f} · "
                    f"系统效用 {row['system_utility']:.2f}"
                )


def render_step_9_experience_references(experience_references: dict) -> None:
    st.header("Step 9 历史经验引用")

    cols = st.columns(3)
    cols[0].metric("引用案例数", experience_references.get("reference_count", 0))
    cols[1].metric(
        "置信度修正",
        f"{float(experience_references.get('confidence_adjustment', 0)):.1f}",
    )
    cols[2].metric("检索模式", "TF-IDF")

    risk_hints = experience_references.get("risk_hints") or []
    if risk_hints:
        st.markdown("**经验风险提示**")
        for item in risk_hints:
            st.write(f"- {item}")

    references = experience_references.get("references") or []
    if references:
        st.dataframe(
            [
                {
                    "case_id": item.get("case_id"),
                    "scenario": item.get("scenario"),
                    "recommended_pattern": item.get("recommended_pattern"),
                    "similarity_score": item.get("similarity_score"),
                }
                for item in references
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("未检索到相似历史案例，当前决策按规则与实时态势独立生成。")

    # 参数校准对比：I09 数据驱动权重 vs 专家默认值
    with st.expander("参数校准对比（数据驱动 vs 专家默认）", expanded=False):
        import csv as _csv
        from pathlib import Path as _Path

        from src.config_loader import load_risk_weights
        from src.parameter_calibration import calibrate_inventory_risk_weights

        _csv_path = (
            _Path(__file__).resolve().parent
            / "demo_assets/enterprise/csv/historical_decisions.csv"
        )
        try:
            with open(_csv_path, encoding="utf-8-sig") as _f:
                _records = list(_csv.DictReader(_f))
            _expert = load_risk_weights()["inventory_risk_weights"]
            _calibrated = calibrate_inventory_risk_weights(_records)
            _comparison = [
                {
                    "权重维度": k,
                    "专家默认值": round(_expert.get(k, 0), 4),
                    "数据驱动校准值": round(_calibrated.get(k, 0), 4),
                    "变化量": round(_calibrated.get(k, 0) - _expert.get(k, 0), 4),
                }
                for k in _expert
            ]
            st.dataframe(_comparison, use_container_width=True, hide_index=True)
            import pandas as pd

            _calibration_chart_rows = [
                {
                    "权重维度": k,
                    "来源": "专家默认值",
                    "权重": round(_expert.get(k, 0), 4),
                }
                for k in _expert
            ] + [
                {
                    "权重维度": k,
                    "来源": "数据驱动校准值",
                    "权重": round(_calibrated.get(k, 0), 4),
                }
                for k in _expert
            ]
            st.markdown("**库存风险权重校准对比（专家默认 vs 数据驱动）**")
            st.bar_chart(
                pd.DataFrame(_calibration_chart_rows),
                x="权重维度",
                y="权重",
                color="来源",
                stack=False,
                horizontal=True,
                height=320,
            )
            st.caption(_calibrated.get("_calibration_note"))
            if {k: _calibrated.get(k) for k in _expert} == _expert:
                st.info("当前校准结果与专家默认值一致（通常表示历史数据样本不足）。")
            else:
                _max_delta_key = max(
                    _expert,
                    key=lambda k: abs(_calibrated.get(k, 0) - _expert.get(k, 0)),
                )
                _delta = round(
                    _calibrated.get(_max_delta_key, 0) - _expert.get(_max_delta_key, 0),
                    3,
                )
                st.success(
                    f"数据驱动校准已更新权重，最大偏差：{_max_delta_key} "
                    f"{'↑' if _delta > 0 else '↓'}{abs(_delta):.3f}"
                )
        except Exception as _e:
            st.warning(f"参数校准对比加载失败：{_e}")


def render_step_10_explanation(explanation: dict) -> None:
    st.header("Step 10 可解释决策说明")

    cols = st.columns(2)
    cols[0].metric("LLM 增强", "是" if explanation.get("llm_used") else "否")
    cols[1].metric("解释模型", explanation.get("model_name", "template"))

    st.markdown("**仲裁说明**")
    st.write(explanation.get("arbitration_summary", "暂无仲裁说明。"))
    st.markdown("**辩论说明**")
    st.write(explanation.get("debate_narrative", "暂无辩论说明。"))
    st.markdown("**约束说明**")
    st.write(explanation.get("constraint_narrative", "暂无约束说明。"))


def render_step_11_audit(audit_entry: dict) -> None:
    st.header("Step 11 决策审计记录")

    cols = st.columns(4)
    cols[0].metric("状态", audit_entry.get("decision_status", "unknown"))
    cols[1].metric(
        "库存风险",
        f"{float(audit_entry.get('inventory_risk_index', 0)):.1f}",
    )
    cols[2].metric("可行组合", audit_entry.get("constraint_feasible_count", 0))
    cols[3].metric(
        "辩论收敛",
        "是" if audit_entry.get("debate_converged", False) else "否",
    )

    if audit_entry.get("decision_status") == "error":
        st.error(audit_entry.get("error_message", "审计记录标记为错误。"))
    elif audit_entry.get("human_approval_required"):
        st.warning("该决策需要人工审批后执行。")
    else:
        st.success("审计结果正常，可进入执行确认。")

    with st.expander("查看完整审计 JSON"):
        st.json(audit_entry)


def render_sensitivity(results: list[dict]) -> None:
    st.header("敏感性分析：当前库存对风险指数的影响")
    if not results:
        st.info("暂无敏感性分析结果。")
        return

    st.dataframe(results, use_container_width=True, hide_index=True)
    chart_rows = [
        {
            "current_stock": row["param_value"],
            "inventory_risk_index": row["inventory_risk_index"],
        }
        for row in results
    ]
    st.line_chart(
        chart_rows,
        x="current_stock",
        y="inventory_risk_index",
    )


def build_decision_report(result) -> dict:
    """Extract key fields from DecisionResult into a JSON-serializable dict."""
    arb = result.arbitration or {}
    ca = result.constraint_analysis or {}
    dr = result.debate_result or {}
    ae = result.audit_entry or {}
    inv_ctx = (result.context or {}).get("inventory", {})
    inv_risk = result.inventory_risk or {}

    return {
        "case": {
            "material_name": inv_ctx.get("material_name"),
            "event_type": ae.get("event_type"),
            "inventory_risk_index": inv_risk.get("inventory_risk_index"),
        },
        "arbitration": {
            "final_decision_title": arb.get("final_decision_title"),
            "final_score": arb.get("final_score"),
            "execution_plan": arb.get("execution_plan"),
        },
        "constraint_analysis": {
            "feasible_count": ca.get("feasible_count"),
            "optimal_system_utility": ca.get("optimal_system_utility"),
        },
        "debate_result": {
            "total_rounds": dr.get("total_rounds"),
            "converged": dr.get("converged"),
            "system_utility_before": dr.get("system_utility_before"),
            "system_utility_after": dr.get("system_utility_after"),
        },
        "audit_entry": {
            "decision_id": ae.get("decision_id"),
            "timestamp": ae.get("timestamp"),
            "human_approval_required": ae.get("human_approval_required"),
        },
    }


def render_model_comparison() -> None:
    st.subheader("6 模型对比评测：哪个模型预测结果最准？")
    if st.button("运行 6 模型对比评测"):
        from src.history_pipeline import HistoryPipeline
        from src.model_comparison import compare_models
        from src.training_dataset import split_by_time

        records = HistoryPipeline()._load_valid_records_before_cutoff("2026-12-31")
        split = split_by_time(
            records,
            time_field="created_at",
            train_end="2026-03-15",
            validation_end="2026-04-01",
        )
        if len(split.train) < 10:
            st.warning("历史数据不足，至少需要 10 条已标注记录")
        else:
            report = compare_models(split)

            import pandas as pd

            rows = [
                {
                    "模型": result.model_name,
                    "准确率": round(result.accuracy, 4),
                    "F1-macro": round(result.f1_macro, 4),
                    "训练耗时(ms)": round(result.training_time_ms, 1),
                }
                for result in report.model_results
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            import altair as alt

            chart_rows = [
                {
                    "模型": result.model_name,
                    "指标": metric_name,
                    "分数": metric_value,
                    "显示": "最优模型" if result.model_name == report.best_model_name else metric_name,
                }
                for result in report.model_results
                for metric_name, metric_value in [
                    ("准确率", result.accuracy),
                    ("F1-macro", result.f1_macro),
                ]
            ]
            score_chart = (
                alt.Chart(pd.DataFrame(chart_rows))
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X(
                        "模型:N",
                        title="模型",
                        sort=[result.model_name for result in report.model_results],
                        axis=alt.Axis(labelAngle=-25),
                    ),
                    xOffset=alt.XOffset("指标:N"),
                    y=alt.Y("分数:Q", title="分数", scale=alt.Scale(domain=[0, 1])),
                    color=alt.Color(
                        "显示:N",
                        scale=alt.Scale(
                            domain=["最优模型", "准确率", "F1-macro"],
                            range=["#f59e0b", "#2563eb", "#64748b"],
                        ),
                        legend=alt.Legend(title=None, orient="top"),
                    ),
                    tooltip=[
                        alt.Tooltip("模型:N"),
                        alt.Tooltip("指标:N"),
                        alt.Tooltip("分数:Q", format=".3f"),
                    ],
                )
                .properties(
                    height=320,
                    title=f"6 模型对比：最优模型 {report.best_model_name}",
                )
            )
            st.altair_chart(score_chart, use_container_width=True)

            st.success(
                f"🏆 最优模型：{report.best_model_name} "
                f"(F1-macro = {report.best_f1_macro:.3f}，已注册为稳定版本候选)"
            )

            best_result = next(
                result
                for result in report.model_results
                if result.model_name == report.best_model_name
            )
            if best_result.feature_importance:
                st.subheader("特征重要性（最优模型）")
                st.bar_chart(best_result.feature_importance)

            decision_tree_result = next(
                (result for result in report.model_results if result.decision_tree_text),
                None,
            )
            if decision_tree_result:
                with st.expander("决策树规则（可读文本，max_depth=4）"):
                    st.code(decision_tree_result.decision_tree_text, language="text")


def render_value_dashboard(result) -> None:
    from src.audit import AuditLog
    from src.economic_impact import calculate_economic_impact
    from src.value_dashboard import aggregate_timeline_value

    import pandas as pd

    impact = calculate_economic_impact(result.context)

    st.subheader("本次事件收益")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "💰 本次净节省",
        f"¥{impact.net_benefit:,.0f}",
        f"年化 ¥{impact.annual_benefit_estimate:,.0f}",
    )
    col2.metric(
        "📋 违约损失节省",
        f"¥{impact.penalty_savings:,.0f}",
        f"人工 ¥{impact.manual_penalty:,.0f} → 系统 ¥{impact.system_penalty:,.0f}",
    )
    col3.metric(
        "🛡 利润保护",
        f"¥{impact.profit_protected:,.0f}",
    )

    st.subheader("时间线累计")
    entries = [e.to_dict() for e in AuditLog().load()]
    timeline = aggregate_timeline_value(entries)
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "📈 累计净节省（去重）",
        f"¥{timeline.cumulative_net_benefit:,.0f}",
        f"覆盖 {timeline.event_count} 个事件",
    )
    c2.metric(
        "🕒 最近一次事件节省",
        f"¥{timeline.latest_event_net_benefit:,.0f}",
        timeline.latest_event_key or "—",
    )
    c3.metric(
        "📊 平均每次事件节省",
        f"¥{timeline.average_net_benefit:,.0f}",
    )
    if len(timeline.per_event_series) >= 2:
        st.line_chart(
            pd.DataFrame(timeline.per_event_series),
            x="timestamp",
            y="net_benefit",
        )
    else:
        st.caption("累计数据需多个事件后才显示趋势。")
    st.caption(
        "累计金额按事件去重统计（同一事件多次演示只计一次），自系统启用起累计，为业务情景估算。"
    )

    st.subheader("决策提速与订单覆盖")
    speed_col, _ = st.columns([1, 2])
    speed_col.metric(
        "⏱ 决策提速",
        f"< {impact.system_decision_minutes} 分钟",
        f"人工约 {impact.manual_decision_hours:.0f} 小时",
        delta_color="inverse",
    )

    manual_orders_str = "、".join(impact.manual_covered_orders) or "无"
    system_orders_str = "、".join(impact.system_covered_orders) or "无"
    df = pd.DataFrame(
        {
            "指标": ["已覆盖订单", "订单违约损失（¥）", "潜在利润损失（¥）", "决策耗时"],
            "纯人工响应": [
                f"{manual_orders_str}（{len(impact.manual_covered_orders)}/3）",
                f"{impact.manual_penalty:,.0f}",
                f"{impact.manual_lost_profit:,.0f}",
                f"约 {impact.manual_decision_hours:.0f} 小时",
            ],
            "ChainGuard 系统": [
                f"{system_orders_str}（{len(impact.system_covered_orders)}/3）",
                f"{impact.system_penalty:,.0f}",
                f"{impact.system_lost_profit:,.0f}",
                f"< {impact.system_decision_minutes} 分钟",
            ],
        }
    )
    st.table(df)
    st.caption(f"ℹ️ {impact.note}")


def render_decision_process(result, low_score_threshold) -> None:
    st.subheader("① 发现问题")
    render_step_1(result.context["inventory"], result.inventory_risk)
    render_step_2(result.context)

    st.subheader("② 生成方案")
    render_step_3(result.proposals, low_score_threshold)
    render_step_4(result.proposals, result.conflict, low_score_threshold)

    st.subheader("③ 辩论定夺")
    render_step_5(result.rebuttal)
    render_step_6(result.arbitration, result.proposals, result.conflict, result.rebuttal)
    render_step_8_constraint_debate(result.constraint_analysis, result.debate_result)

    st.subheader("④ 确认与留痕")
    render_step_7(result.experience_card)
    render_step_9_experience_references(result.experience_references)
    render_step_10_explanation(result.explanation)
    render_step_11_audit(result.audit_entry)

    with st.expander("🔬 高级分析（敏感性 / 模型对比）", expanded=False):
        render_sensitivity(
            run_sensitivity(
                "current_stock",
                [720, 1440, 2160, 3600, 5400, 7200],
                baseline_context=result.context,
            )
        )
        st.divider()
        render_model_comparison()


def main() -> None:
    st.set_page_config(page_title="ChainGuard 演示模式", page_icon="CG", layout="wide")
    scenario_mode, enterprise_event_id = render_sidebar()
    render_header()

    try:
        if scenario_mode == "企业真实场景":
            if enterprise_event_id is None:
                st.warning("请先在左侧选择一个企业事件。")
                st.stop()

            orchestrator = DecisionOrchestrator()
            result = orchestrator.run_scenario(enterprise_event_id, ScenarioLoader())
        else:
            # 原有演示场景逻辑保持不变
            orchestrator = DecisionOrchestrator()
            result = orchestrator.run_demo()
    except (FileNotFoundError, ValueError) as error:
        st.error(str(error))
        st.stop()

    low_score_threshold = result.thresholds["learning"]["low_score_threshold"]
    tab_value, tab_process = st.tabs(["💰 决策价值（管理层视角）", "🔎 决策过程（人工决策视角）"])

    with tab_value:
        render_value_dashboard(result)
    with tab_process:
        render_decision_process(result, low_score_threshold)

    st.divider()
    st.warning(explain_simulation_limitations())
    st.divider()
    report_json = json.dumps(build_decision_report(result), ensure_ascii=False, indent=2)
    decision_id = (result.audit_entry or {}).get("decision_id", "unknown")
    st.download_button(
        label="📥 下载决策报告 JSON",
        data=report_json,
        file_name=f"chainguard_decision_{decision_id}.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
