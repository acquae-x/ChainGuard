import json
from pathlib import Path

import streamlit as st

from src.confirmation import (
    build_confirmation_items,
    evaluate_gate,
    record_confirmation,
)
from src.data_source import DataSource, demo_source, enterprise_source
from src.learning import (
    load_experience_cards,
    save_experience_card,
)
from src.orchestrator import DecisionOrchestrator
from src.parameter_calibration import explain_simulation_limitations
from src.scenario_loader import ScenarioLoader
from src.scoring import detect_low_score, rank_proposals
from src.security.view_roles import mask_rows_for_view, role_for_view
from src.sensitivity import run_sensitivity
from src.supply_monitor import scan_supply_chain


def render_intake_review(
    records: list[dict],
    history_counts: dict[str, int],
    *,
    fallback_self_count: bool = False,
    data_source: DataSource | None = None,
) -> bool:
    from src.intake_review import (
        OCCASIONAL_THRESHOLD,
        ROUTINE_THRESHOLD,
        build_history_counts,
        calibrate_intake_thresholds,
        review_batch,
    )
    from src.signature_history import update_history

    if fallback_self_count and not history_counts:
        history_counts = build_history_counts(records)
    routine_threshold, occasional_threshold = calibrate_intake_thresholds(history_counts)
    source = (
        "default"
        if (
            routine_threshold == ROUTINE_THRESHOLD
            and occasional_threshold == OCCASIONAL_THRESHOLD
        )
        else "calibrated"
    )
    report = review_batch(
        records,
        history_counts,
        routine_threshold=routine_threshold,
        occasional_threshold=occasional_threshold,
    )

    st.markdown("**规则复核（rule-based）**")
    cols = st.columns(2)
    cols[0].metric("常规自动通过", report.auto_passed)
    cols[1].metric("需人工确认", report.needs_confirmation)
    st.caption(
        f"阈值来源：{source}（常规≥{routine_threshold}次 / 偶发={occasional_threshold}次）"
    )

    history_cols = st.columns(3)
    history_cols[0].metric("Accumulated signatures", len(history_counts))
    history_cols[1].metric("Batch novel", report.novel_count)
    history_cols[2].metric("Batch routine", report.routine_count)
    st.caption(f"Tenant history currently contains {len(history_counts)} signatures.")

    novel_rows = [
        {
            "signature": assessment.signature,
            "confirmation_points": "；".join(assessment.confirmation_points),
        }
        for assessment in report.assessments
        if assessment.familiarity == "novel"
    ]
    if novel_rows:
        st.dataframe(novel_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("本批无首次出现记录。")
    if data_source is None:
        return False

    if report.needs_confirmation == 0:
        update_history(data_source, records)
        st.success("All signatures are routine; this batch has been added to cumulative history.")
        return True

    st.warning("This batch contains novel or low-frequency signatures. Confirm before adding it to cumulative history.")
    confirmed = True
    for index, assessment in enumerate(report.assessments):
        if not assessment.requires_confirmation:
            continue
        checked = st.checkbox(
            f"{assessment.familiarity} - {assessment.signature}",
            key=f"intake_history_confirm_{data_source.tenant_id}_{index}_{assessment.signature}",
        )
        for point in assessment.confirmation_points:
            st.caption(point)
        confirmed = confirmed and checked

    if st.button(
        "Confirm and update history",
        disabled=not confirmed,
        key=f"intake_history_update_{data_source.tenant_id}",
    ):
        update_history(data_source, records)
        st.success("Confirmed and added to cumulative signature history.")
        return True

    return False


def _available_enterprise_tenants() -> list[str]:
    base = Path(demo_source().scenario_db_path)
    tenants: list[str] = []
    for path in sorted(base.parent.glob(f"{base.stem}.*{base.suffix}")):
        tenant_id = path.name[len(base.stem) + 1 : -len(base.suffix)]
        if not tenant_id:
            continue
        try:
            loader = ScenarioLoader(path)
            scenarios = loader.list_scenarios(limit=1)
            if scenarios:
                loader.load_context(scenarios[0]["event_id"])
                tenants.append(tenant_id)
        except Exception:
            continue
    return tenants


def render_sidebar() -> tuple[str, str | None, DataSource]:
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
        data_source = demo_source()
        if scenario_mode == "企业真实场景":
            try:
                _tenants = _available_enterprise_tenants()
                if not _tenants:
                    st.warning("暂无可用企业租户，请先导入并通过校验。")
                else:
                    _selected_tenant = st.selectbox(
                        "选择租户",
                        _tenants,
                        key="enterprise_tenant_select",
                    )
                    data_source = enterprise_source(_selected_tenant)
                    _loader_for_list = ScenarioLoader(data_source.scenario_db_path)
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

        with st.expander("📥 企业数据导入"):
            tid = st.text_input("租户 ID（字母数字/_/-）")
            server_dir = st.text_input(
                "服务器端目录路径（大数据推荐，留空则使用上传文件）",
                key="enterprise_server_dir",
            )
            files = st.file_uploader(
                "上传企业 CSV（materials/inventory/suppliers/...）",
                type=["csv"],
                accept_multiple_files=True,
            )
            preflight_key = f"enterprise_preflight_{tid}_{server_dir}_{len(files or [])}"

            def _preflight_paths_from_upload(tmp_dir: str):
                import pathlib

                paths = []
                for f in files or []:
                    path = pathlib.Path(tmp_dir, f.name)
                    path.write_bytes(f.getbuffer())
                    paths.append(path)
                return paths

            if st.button("先做容量预检", use_container_width=True) and tid and (
                server_dir or files
            ):
                import tempfile
                from pathlib import Path

                from src.import_preflight import run_preflight
                from src.data_source import tenant_scenario_db_path

                try:
                    tenant = enterprise_source(tid, require_exists=False).tenant_id
                    db_path = tenant_scenario_db_path(tenant)
                    if server_dir:
                        csv_paths = sorted(Path(server_dir).glob("*.csv"))
                        report = run_preflight(csv_paths, db_path)
                    else:
                        with tempfile.TemporaryDirectory() as tmp:
                            report = run_preflight(
                                _preflight_paths_from_upload(tmp),
                                db_path,
                            )
                    st.session_state[preflight_key] = report
                except Exception as _e:
                    st.error(f"容量预检失败：{_e}")

            preflight_report = st.session_state.get(preflight_key)
            import_disabled = False
            if preflight_report is not None:
                _verdict_cn = {
                    "OK": "✅ 通过",
                    "REVIEW": "⚠ 需评估",
                    "INSUFFICIENT_DISK": "❌ 磁盘不足",
                }.get(preflight_report.verdict, preflight_report.verdict)
                st.markdown(f"**容量预检结论：{_verdict_cn}**")
                for _msg in preflight_report.messages:
                    st.write(f"- {_msg}")
                if preflight_report.verdict == "INSUFFICIENT_DISK":
                    st.error("磁盘空间不足，导入已禁用。")
                    import_disabled = True
                elif preflight_report.verdict == "REVIEW":
                    st.warning("数据量较大，建议评估 PostgreSQL 后再导入。")
                else:
                    st.success("容量预检通过。")

            if st.button(
                "导入并校验",
                disabled=import_disabled,
                use_container_width=True,
            ) and tid and (server_dir or files):
                import csv
                import pathlib
                import tempfile

                from src.enterprise_ingest import import_tenant_from_dir
                from src.import_preflight import estimate_incoming

                try:
                    progress_bar = st.progress(0, text="准备导入...")
                    table_progress: dict[str, int] = {}
                    review_records = None

                    def _progress(table_name: str, rows: int) -> None:
                        table_progress[table_name] = rows
                        total_done = sum(table_progress.values())
                        fallback_estimate = st.session_state.get(
                            preflight_key + "_estimated_rows",
                            0,
                        )
                        total_est = max(
                            int(
                                getattr(
                                    st.session_state.get(preflight_key),
                                    "estimated_rows",
                                    fallback_estimate,
                                )
                            ),
                            total_done,
                            1,
                        )
                        progress_bar.progress(
                            min(total_done / total_est, 1.0),
                            text=f"正在导入 {table_name}：{total_done:,}/{total_est:,} 行",
                        )

                    if server_dir:
                        csv_paths = sorted(pathlib.Path(server_dir).glob("*.csv"))
                        if preflight_report is None:
                            total_est = estimate_incoming(csv_paths)[1]
                            st.session_state[preflight_key + "_estimated_rows"] = total_est
                        res = import_tenant_from_dir(
                            tid,
                            server_dir,
                            progress=_progress,
                            run_preflight_check=preflight_report is None,
                        )
                        review_csv_path = pathlib.Path(server_dir) / "disruption_events.csv"
                        if review_csv_path.exists():
                            with review_csv_path.open(
                                encoding="utf-8-sig",
                                newline="",
                            ) as _f:
                                review_records = list(csv.DictReader(_f))
                    else:
                        with tempfile.TemporaryDirectory() as tmp:
                            for f in files or []:
                                pathlib.Path(tmp, f.name).write_bytes(f.getbuffer())
                            if preflight_report is None:
                                csv_paths = sorted(pathlib.Path(tmp).glob("*.csv"))
                                total_est = estimate_incoming(csv_paths)[1]
                                st.session_state[preflight_key + "_estimated_rows"] = total_est
                            res = import_tenant_from_dir(
                                tid,
                                tmp,
                                progress=_progress,
                                run_preflight_check=preflight_report is None,
                            )
                            review_csv_path = pathlib.Path(tmp) / "disruption_events.csv"
                            if review_csv_path.exists():
                                with review_csv_path.open(
                                    encoding="utf-8-sig",
                                    newline="",
                                ) as _f:
                                    review_records = list(csv.DictReader(_f))
                    progress_bar.progress(1.0, text="导入完成，正在展示结果")
                    st.dataframe(
                        res.table_results,
                        hide_index=True,
                        use_container_width=True,
                    )
                    if res.smoke_ok:
                        st.success(f"✅ 导入成功（{res.ok_tables} 表）：{res.smoke_message}")
                        try:
                            if review_records is None:
                                st.session_state.pop("enterprise_import_review_pending", None)
                                st.caption("本批无事件数据，跳过复核。")
                            else:
                                target_ds = enterprise_source(res.tenant_id)
                                st.session_state["enterprise_import_review_pending"] = {
                                    "tenant_id": target_ds.tenant_id,
                                    "records": review_records,
                                }
                        except Exception as _e:
                            st.caption(f"导入复核展示失败，已跳过：{_e}")
                    else:
                        st.error(f"❌ {res.smoke_message}（该租户未激活，请检查 CSV）")
                except Exception as _e:
                    st.error(f"导入失败：{_e}")

            pending_review = st.session_state.get("enterprise_import_review_pending")
            if pending_review:
                try:
                    from src.signature_history import load_history

                    target_ds = enterprise_source(pending_review["tenant_id"])
                    history = load_history(target_ds)
                    updated = render_intake_review(
                        pending_review["records"],
                        history,
                        data_source=target_ds,
                    )
                    if updated:
                        st.session_state.pop("enterprise_import_review_pending", None)
                except Exception as _e:
                    st.caption(f"Intake review display skipped: {_e}")

    return scenario_mode, enterprise_event_id, data_source


def render_header() -> None:
    st.title("ChainGuard 供应链应急响应系统")
    st.subheader("库存监控 × 多源感知 × 辩论仲裁 × 经验自学习")
    st.info("当前为系统演示版本，使用模拟数据和专家经验参数。")


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


def render_step_9_experience_references(
    experience_references: dict,
    *,
    data_source: DataSource | None = None,
    view: str = "供应链经理",
) -> None:
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

    references = mask_rows_for_view(experience_references.get("references") or [], view)
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
        import sqlite3
        from pathlib import Path as _Path

        from src.config_loader import load_risk_weights
        from src.parameter_calibration import calibrate_inventory_risk_weights

        _records = []
        _load_error = None
        if data_source is None or data_source.kind == "demo":
            _csv_path = (
                _Path(__file__).resolve().parent
                / "demo_assets/enterprise/csv/historical_decisions.csv"
            )
            try:
                with open(_csv_path, encoding="utf-8-sig") as _f:
                    _records = list(_csv.DictReader(_f))
            except Exception as _e:
                _load_error = str(_e)
        else:
            try:
                _conn = sqlite3.connect(data_source.scenario_db_path)
                try:
                    _cur = _conn.execute("SELECT * FROM historical_decisions")
                    _cols = [d[0] for d in _cur.description]
                    _records = [dict(zip(_cols, row)) for row in _cur.fetchall()]
                finally:
                    _conn.close()
            except Exception as _e:
                _load_error = str(_e)

        if _load_error:
            st.warning(f"参数校准对比加载失败：{_load_error}")
        elif not _records:
            st.info("该租户暂无历史决策，参数校准沿用专家默认值。")
        else:
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

            # 触发阈值 + 预警支撑时长：同样从历史结果数据驱动校准（I40/I09），人工放行后应用。
            from src.config_loader import load_thresholds
            from src.parameter_calibration import (
                calibrate_thresholds,
                calibrate_trigger_threshold,
            )

            _expert_thr = load_thresholds()["inventory_warning"]
            _weights_clean = {k: _calibrated.get(k, 0) for k in _expert}
            _trig = calibrate_trigger_threshold(_records, _weights_clean)
            _cal_thr = calibrate_thresholds(_records)["inventory_warning"]
            _thr_rows = [
                {
                    "阈值参数": "库存风险触发阈值",
                    "专家默认值": _expert_thr["inventory_risk_trigger"],
                    "数据驱动校准值": _trig["value"],
                    "方法 / 样本": f"{_trig['_method']} · n={_trig['_sample_size']}",
                },
                {
                    "阈值参数": "黄色预警支撑时长 (h)",
                    "专家默认值": _expert_thr["yellow_support_hours"],
                    "数据驱动校准值": _cal_thr["yellow_support_hours"],
                    "方法 / 样本": "P25 失败延误时长",
                },
                {
                    "阈值参数": "红色预警支撑时长 (h)",
                    "专家默认值": _expert_thr["red_support_hours"],
                    "数据驱动校准值": _cal_thr["red_support_hours"],
                    "方法 / 样本": "P10 失败延误时长",
                },
            ]
            st.markdown("**触发 / 预警阈值校准对比（专家默认 vs 数据驱动）**")
            st.dataframe(_thr_rows, use_container_width=True, hide_index=True)
            st.caption(
                "风险权重、触发阈值、预警时长均由历史结果数据驱动校准（建议值），经人工放行后"
                "写入配置——保留「AI 建议、人把关」护栏，不自动覆盖 YAML。"
            )
            st.caption(
                "说明：决策评分权重 / 博弈收益权重是模型结构系数，辩论触发差距、低分阈值是运营"
                "策略阈值——二者无历史结果可作校准基准，故保持配置默认值，不做伪数据驱动。"
            )


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


def render_confirmation_gate(
    arbitration: dict,
    audit_entry: dict,
    *,
    view_role: str = "供应链经理",
) -> None:
    import hashlib

    decision_id = (audit_entry or {}).get("decision_id", "unknown")
    items = build_confirmation_items(arbitration.get("manual_confirmation_points", []))
    if not items:
        st.info("本决策无需人工确认点，可直接执行。")
        return

    # 控件 key 必须在 rerun 间稳定：decision_id 每次 run_demo/run_scenario 都会重新生成，
    # 若用它做 key，用户每勾一项就因 key 变化被清空，闸门永远锁死。改用确认点内容派生的
    # 稳定 gate_id（同一组确认点 → 同一 key，跨 rerun 保留勾选；换场景 → 不同 key）。
    gate_id = hashlib.md5(
        "|".join(item.point for item in items).encode("utf-8")
    ).hexdigest()[:10]

    st.header("执行确认闸门")
    confirmed_flags: dict[str, bool] = {}
    for i, item in enumerate(items):
        confirmed_flags[item.point] = st.checkbox(
            f"[{item.role}] {item.point}",
            key=f"confirm_{gate_id}_{i}",
        )
        st.caption(item.risk_if_skipped)

    override = st.checkbox(
        "带理由强制放行",
        key=f"confirm_override_{gate_id}",
    )
    reason = st.text_input(
        "强制放行理由",
        key=f"confirm_override_reason_{gate_id}",
    )
    gate = evaluate_gate(
        items,
        confirmed_flags,
        override=override,
        override_reason=reason,
    )

    if not gate.can_execute:
        st.warning(f"还有 {len(gate.blocked_points)} 项待确认，执行已锁定。")

    if st.button(
        "⬇️ 下发执行",
        disabled=not gate.can_execute,
        key=f"confirm_execute_{gate_id}",
    ):
        try:
            record_confirmation(
                decision_id,
                items,
                confirmed_flags,
                confirmed_by=view_role,
                override=override,
                override_reason=reason,
            )
            st.success("已下发执行并留痕。")
        except Exception as exc:
            st.caption(f"确认日志写入失败：{exc}")


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


def render_security_panel(role: str, data_source) -> None:
    from src.security.posture import (
        masking_preview,
        sample_sensitive_record,
        security_posture,
    )

    with st.expander("🔐 数据安全"):
        st.caption(f"当前视角角色：`{role}`（演示映射，不代表真实登录鉴权）")
        posture = security_posture(role, data_source)
        preview = masking_preview(sample_sensitive_record(), role)

        status_icon = "✅" if posture.encryption_active else "⚠️"
        cols = st.columns(3)
        cols[0].metric("加密状态", f"{status_icon} {'已启用' if posture.encryption_active else '未启用'}")
        cols[1].metric("租户隔离", "✅ 企业隔离" if posture.tenant_isolated else "演示数据")
        cols[2].metric("当前租户", posture.tenant_id)
        st.caption(posture.encryption_note)
        st.caption(f"场景库：{Path(posture.scenario_db_path).name}")

        st.markdown("**当前角色权限**")
        if posture.permissions:
            st.write(" ".join(f"`{permission}`" for permission in posture.permissions))
        else:
            st.caption("该角色暂无权限。")

        st.markdown("**脱敏规则**")
        if posture.masking_rules:
            rule_rows = [
                {"字段": field, "规则": rule}
                for field, rule in sorted(posture.masking_rules.items())
            ]
            st.dataframe(rule_rows, hide_index=True, use_container_width=True)
        else:
            st.caption("admin 角色不脱敏。")

        before_col, after_col = st.columns(2)
        with before_col:
            st.markdown("**脱敏前**")
            st.json(preview["before"])
        with after_col:
            st.markdown("**脱敏后**")
            st.json(preview["after"])


def render_automation_panel(data_source) -> None:
    """读取 data_source.audit_log_path 的审计记录，展示自动化率与升级规则。"""
    from src.audit import AuditLog, DEFAULT_AUDIT_PATH, RISK_APPROVAL_THRESHOLD
    from src.automation_stats import summarize_automation

    import pandas as pd

    audit_log_path = (
        data_source.audit_log_path if data_source is not None else DEFAULT_AUDIT_PATH
    )
    entries = [entry.to_dict() for entry in AuditLog(audit_log_path).load()]
    summary = summarize_automation(entries)

    st.subheader("人机分工")
    cols = st.columns(3)
    cols[0].metric("自动化率", f"{summary.automation_rate:.1%}")
    cols[1].metric("自动放行条数", summary.auto_approved)
    cols[2].metric("升级人工条数", summary.escalated)
    st.caption(
        f"升级人工规则：风险指数 > {RISK_APPROVAL_THRESHOLD:.0f} / 辩论未收敛 / "
        "约束无可行解，命中任一即需人工确认。"
    )

    if summary.total == 0:
        st.info("暂无决策记录，运行一次决策后展示人机分工统计。")
        return

    if summary.escalated > 0:
        if summary.escalation_reasons:
            reason_rows = [
                {"升级原因": reason, "命中次数": count}
                for reason, count in sorted(
                    summary.escalation_reasons.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ]
            st.bar_chart(
                pd.DataFrame(reason_rows),
                x="升级原因",
                y="命中次数",
            )
        else:
            st.caption("升级记录未命中可复原的规则原因。")


def render_drift_panel(data_source) -> None:
    from src.drift_monitor import (
        CRITICAL_DROP,
        WARN_DROP,
        calibrate_drift_thresholds,
        compute_drift,
        load_historical_decisions,
        run_recalibration_cycle,
    )
    from src.model_registry import ModelRegistry
    from src.drift_history import (
        append_snapshot,
        load_snapshots,
        register_baseline,
        trend_series,
    )

    with st.expander("🩺 系统健康 / 漂移体检"):
        db_path = getattr(data_source, "scenario_db_path", "")
        if not db_path:
            st.info("暂无场景库，无法读取历史决策样本。")
            return

        records = load_historical_decisions(db_path)
        registry = ModelRegistry()
        stable = registry.get_stable()
        baseline = None
        if stable is not None and "success_rate" in stable.metrics:
            baseline = float(stable.metrics["success_rate"])

        warn_drop, critical_drop = calibrate_drift_thresholds(registry)
        threshold_source = (
            "calibrated"
            if (warn_drop, critical_drop) != (WARN_DROP, CRITICAL_DROP)
            else "default"
        )
        report = compute_drift(
            records,
            baseline_success_rate=baseline,
            warn_drop=warn_drop,
            critical_drop=critical_drop,
        )

        if report.sample_size == 0:
            st.info("暂无可用于漂移体检的真实结果样本，当前仅保留安全默认状态。")

        cols = st.columns(3)
        cols[0].metric("当前成功率", f"{report.success_rate:.1%}")
        cols[1].metric("样本量", report.sample_size)
        cols[2].metric("相对基线变化", f"-{report.success_rate_drop:.1%}")

        if report.severity == "critical":
            st.error("漂移等级：critical，建议复核回滚或人工确认后处理。")
        elif report.severity == "warn":
            st.warning("漂移等级：warn，建议生成带人工放行的重校准建议。")
        else:
            st.success("漂移等级：ok，当前未检测到需要告警的漂移。")

        st.caption(
            "告警阈值来源："
            f"{'数据校准' if threshold_source == 'calibrated' else '默认'}"
            f"（warn≥{warn_drop:.1%} / critical≥{critical_drop:.1%}）"
        )
        for finding in report.findings:
            st.write(f"- {finding}")
        st.write(f"建议动作：`{report.recommended_action}`")

        if st.button("生成重校准建议", key="drift_recalibration_button"):
            result = run_recalibration_cycle(
                records,
                registry=registry,
                baseline_success_rate=baseline,
            )
            st.caption("以下仅为带人工放行的重校准建议，不会自动应用到配置。")
            st.metric("是否建议提升为稳定版本", "是" if result["should_promote"] else "否")
            st.json(
                {
                    "suggestions": result["suggestions"],
                    "registered_version": result["registered_version"],
                    "drift_thresholds": result["drift_thresholds"],
                    "alert_sent": result["alert_sent"],
                }
            )

        st.divider()
        st.markdown("**达标基线 + 漂移趋势**")
        if baseline is None:
            st.caption("尚未注册基线，漂移恒为 ok；注册当前成功率后才能判断三个月后是否仍达标。")

        base_col, snap_col = st.columns(2)
        with base_col:
            if st.button("📌 注册当前成功率为基线", key="drift_register_baseline"):
                info = register_baseline(report.success_rate)
                st.success(
                    f"已注册基线：成功率 {info['success_rate']:.1%}"
                    f"（版本 {info['version_id'][:8]}，已提升为 stable）"
                )
        with snap_col:
            if st.button("🩺 记录本次体检", key="drift_record_snapshot"):
                append_snapshot(data_source, report)
                st.success("已记录本次体检快照。")

        series = trend_series(load_snapshots(data_source))
        if len(series) >= 2:
            st.line_chart(
                {
                    "成功率": [point["success_rate"] for point in series],
                    "相对基线下降": [point["success_rate_drop"] for point in series],
                }
            )
            st.caption(f"已记录 {len(series)} 次体检；趋势反映系统随时间是否仍达标。")
        else:
            st.caption("快照不足，至少 2 次体检后展示趋势。")

        st.caption(
            "基线由人工注册；趋势反映系统随时间是否仍达标；重校准建议需人工放行。"
            "可用 `python scripts/run_recalibration.py --db <租户库> --baseline <r>` "
            "配 /schedule routine 或系统计划任务周期触发（本任务不实现常驻进程）。"
        )


def render_value_dashboard(result, data_source=None, *, view: str = "管理者") -> None:
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
    render_automation_panel(data_source)
    render_drift_panel(data_source)
    render_security_panel(role_for_view(view), data_source)


def render_decision_process(
    result,
    low_score_threshold,
    *,
    data_source=None,
    view: str = "供应链经理",
) -> None:
    # 4 个决策阶段 + 高级分析做成分页，默认只展示当前阶段，避免单页过长。
    phase_tabs = st.tabs(
        [
            "① 发现问题",
            "② 生成方案",
            "③ 辩论定夺",
            "④ 确认与留痕",
            "🔬 高级分析",
        ]
    )

    with phase_tabs[0]:
        render_step_1(result.context["inventory"], result.inventory_risk)
        render_step_2(result.context)

    with phase_tabs[1]:
        render_step_3(result.proposals, low_score_threshold)
        render_step_4(result.proposals, result.conflict, low_score_threshold)

    with phase_tabs[2]:
        render_step_5(result.rebuttal)
        render_step_6(
            result.arbitration, result.proposals, result.conflict, result.rebuttal
        )
        render_step_8_constraint_debate(
            result.constraint_analysis, result.debate_result
        )

    with phase_tabs[3]:
        render_confirmation_gate(result.arbitration, result.audit_entry, view_role=view)
        render_step_7(result.experience_card)
        render_step_9_experience_references(
            result.experience_references,
            data_source=data_source,
            view=view,
        )
        render_step_10_explanation(result.explanation)
        render_step_11_audit(result.audit_entry)

    with phase_tabs[4]:
        render_sensitivity(
            run_sensitivity(
                "current_stock",
                [720, 1440, 2160, 3600, 5400, 7200],
                baseline_context=result.context,
            )
        )
        st.divider()
        render_model_comparison()


def render_monitor_overview(data_source, *, view: str = "管理者") -> None:
    try:
        report = scan_supply_chain(data_source)
        if report.overall_health == "at_risk":
            st.error("全链路健康：存在需立即决策的供应链节点")
        elif report.overall_health == "attention":
            st.warning("全链路健康：存在预警节点，建议关注行动队列")
        else:
            st.success("全链路健康：当前系统状态稳定")

        metric_cols = st.columns(4)
        metric_cols[0].metric("扫描节点数", report.scanned)
        metric_cols[1].metric("需决策", report.counts["action_required"])
        metric_cols[2].metric("预警", report.counts["warning"])
        metric_cols[3].metric("观察", report.counts["watch"])
        if report.calibrated_thresholds:
            _w, _wn, _ac = report.calibrated_thresholds
            st.caption(
                f"分级阈值由本次扫描风险分布数据驱动校准："
                f"观察≥{_w:.1f} / 预警≥{_wn:.1f} / 需决策≥{_ac:.1f}"
            )

        if report.action_queue:
            # 同样 mask-then-relabel：管理者(admin)看明文供应商，一线视角则会脱敏。
            raw = [
                {
                    "event_id": node.event_id,
                    "event_type": node.event_type,
                    "material": node.affected_material,
                    "supplier_name": node.affected_supplier,
                    "risk": round(node.risk_index, 2),
                    "action": node.recommended_action,
                }
                for node in report.action_queue
            ]
            rows = [
                {
                    "事件": r["event_id"],
                    "类型": r["event_type"],
                    "物料": r["material"],
                    "供应商": r["supplier_name"],
                    "风险": r["risk"],
                    "建议动作": r["action"],
                }
                for r in mask_rows_for_view(raw, view)
            ]
            st.dataframe(
                rows,
                hide_index=True,
                use_container_width=True,
            )
            st.markdown("**行动队列**")
            for node in report.action_queue:
                detail_col, action_col = st.columns([4, 1])
                with detail_col:
                    st.caption(
                        f"{node.event_id} · {node.event_type} · "
                        f"{node.affected_material} · 风险 {node.risk_index:.2f}"
                    )
                with action_col:
                    if st.button(
                        f"进入决策：{node.event_id}",
                        key=f"goto_{node.event_id}",
                        use_container_width=True,
                    ):
                        st.session_state["cg_selected_event_id"] = node.event_id
                        st.rerun()
        else:
            st.info("全链路暂无预警节点，系统状态稳定。")

        if report.skipped:
            st.caption(f"监控扫描已跳过 {report.skipped} 个无法加载的节点。")
    except Exception as error:
        st.caption(f"监控总览暂不可用：{error}")


def _resolve_selected_event(session_state: dict, default_event_id: str | None) -> str | None:
    """从 session_state 取行动队列选中的 event_id；无则回退 default_event_id。
    纯函数：读 dict，不碰 Streamlit。"""
    return session_state.get("cg_selected_event_id") or default_event_id


def render_node_detail(data_source, *, view: str = "一线从业者") -> None:
    """一线视角：展示 scan_supply_chain(...).all_nodes 的节点级状态明细表。"""
    try:
        report = scan_supply_chain(data_source)
        if not report.all_nodes:
            st.info("暂无可监控的节点。")
            return

        # 先用敏感字段名（supplier_name）建行 → 按视角脱敏 → 再改回中文列名展示。
        # 这样脱敏在“供应商”列上真正生效：一线看到 ***，管理者看到明文。
        raw_rows = [
            {
                "event_id": node.event_id,
                "event_type": node.event_type,
                "material": node.affected_material,
                "supplier_name": node.affected_supplier,
                "risk": round(node.risk_index, 2),
                "status": node.status,
                "action": node.recommended_action,
            }
            for node in report.all_nodes
        ]
        masked = mask_rows_for_view(raw_rows, view)
        display_rows = [
            {
                "事件": r["event_id"],
                "类型": r["event_type"],
                "物料": r["material"],
                "供应商": r["supplier_name"],
                "风险": r["risk"],
                "状态": r["status"],
                "建议动作": r["action"],
            }
            for r in masked
        ]
        st.dataframe(display_rows, hide_index=True, use_container_width=True)
        if mask_rows_for_view([{"supplier_name": "x"}], view)[0]["supplier_name"] == "***":
            st.caption("🔒 当前为一线视角：供应商等敏感字段已脱敏（***）。管理者视角可见明文。")
    except Exception as error:
        st.caption(f"节点明细暂不可用：{error}")


def render_data_intake(data_source, *, view: str = "一线从业者") -> None:
    """Frontline multi-format intake, extraction report, preview, and import."""
    import csv
    import tempfile
    from dataclasses import asdict

    from src.ingestion_agent import ingest_files
    from src.streaming_import import stream_import_csv

    st.markdown("**数据接入 Agent（多格式 + OCR 级联）**")
    uploads = st.file_uploader(
        "上传 CSV / Excel / PDF / 图片",
        accept_multiple_files=True,
        type=["csv", "xlsx", "pdf", "png", "jpg", "jpeg"],
        key="frontline_data_intake_uploads",
    )
    if not uploads:
        st.caption("上传后先落地原始文件，再统一抽取、预览和落库。")
        return

    if not st.button("处理上传文件", use_container_width=True):
        return

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths: list[Path] = []
            for upload in uploads:
                path = Path(tmp_dir) / Path(upload.name).name
                path.write_bytes(upload.getbuffer())
                paths.append(path)

            result = ingest_files(paths)
            report_rows = [asdict(extraction) for extraction in result.extractions]
            if report_rows:
                st.dataframe(report_rows, hide_index=True, use_container_width=True)
            else:
                st.info("本次未抽取到文件。")

            st.caption(
                f"成功 {result.ok_count} 个文件，需人工录入/复核 {result.needs_manual_count} 个文件。"
            )
            for extraction in result.extractions:
                if extraction.needs_manual:
                    note = extraction.note or "未识别"
                    st.warning(f"{extraction.file_name} 需人工录入/复核：{note}")

            if not result.normalized:
                st.info("暂无可预览或落库的归一化行。")
                return

            st.markdown("**归一化预览**")
            for table_name, rows in result.normalized.items():
                st.caption(f"{table_name}: {len(rows)} rows")
                st.dataframe(
                    mask_rows_for_view(rows, view),
                    hide_index=True,
                    use_container_width=True,
                )

            if getattr(data_source, "kind", "") != "enterprise":
                st.info("演示数据源仅预览，不落库，避免污染演示数据。")
                return

            db_path = getattr(data_source, "scenario_db_path", "")
            if not db_path:
                st.warning("当前租户数据库路径不可用，已跳过落库。")
                return

            import_rows = []
            for table_name, rows in result.normalized.items():
                temp_csv = Path(tmp_dir) / f"{table_name}.csv"
                _write_normalized_csv(temp_csv, rows)
                persisted = stream_import_csv(temp_csv, table_name, db_path)
                import_rows.append(
                    {
                        "table_name": table_name,
                        "extracted_rows": len(rows),
                        "persisted_rows": persisted,
                    }
                )
            st.success("归一化结果已统一落入当前企业租户库。")
            st.dataframe(import_rows, hide_index=True, use_container_width=True)
    except Exception as error:
        st.error(f"数据接入失败：{error}")


def _write_normalized_csv(csv_path: Path, rows: list[dict]) -> None:
    headers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                headers.append(key)
                seen.add(key)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def render_data_intake_placeholder(data_source) -> None:
    """Compatibility wrapper for older UI routing tests."""
    render_data_intake(data_source)


def main() -> None:
    st.set_page_config(page_title="ChainGuard 演示模式", page_icon="CG", layout="wide")
    scenario_mode, enterprise_event_id, data_source = render_sidebar()
    render_header()
    selected_event_id = _resolve_selected_event(
        dict(st.session_state),
        enterprise_event_id,
    )
    scenario_db_available = Path(getattr(data_source, "scenario_db_path", "")).exists()
    st.info(f"📡 当前数据源：{data_source.label} · 租户 {data_source.tenant_id}")

    try:
        if selected_event_id and scenario_db_available:
            orchestrator = DecisionOrchestrator()
            result = orchestrator.run_scenario(
                selected_event_id,
                ScenarioLoader(data_source.scenario_db_path),
                data_source=data_source,
            )
        elif scenario_mode == "企业真实场景":
            if enterprise_event_id is None:
                st.warning("请先在左侧选择一个企业事件。")
                st.stop()
            orchestrator = DecisionOrchestrator()
            result = orchestrator.run_scenario(
                enterprise_event_id,
                ScenarioLoader(data_source.scenario_db_path),
                data_source=data_source,
            )
        else:
            # 原有演示场景逻辑保持不变
            orchestrator = DecisionOrchestrator()
            result = orchestrator.run_demo(data_source=data_source)
    except (FileNotFoundError, ValueError) as error:
        st.error(str(error))
        st.stop()

    low_score_threshold = result.thresholds["learning"]["low_score_threshold"]
    tab_mgr, tab_manager, tab_frontline = st.tabs(
        ["🏢 管理者", "📋 供应链经理", "🛠 一线从业者"]
    )

    with tab_mgr:
        render_monitor_overview(data_source, view="管理者")
        st.divider()
        render_value_dashboard(result, data_source=data_source, view="管理者")
    with tab_manager:
        render_decision_process(
            result,
            low_score_threshold,
            data_source=data_source,
            view="供应链经理",
        )
    with tab_frontline:
        render_node_detail(data_source, view="一线从业者")
        st.divider()
        render_data_intake(data_source, view="一线从业者")

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
