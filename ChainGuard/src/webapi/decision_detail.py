from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from src.security.masking import mask_payload

MASK_PLACEHOLDER = "***"

# 财务语义词根：字段名(规范化为 snake_case 后)含任一词根即视为财务字段并脱敏。
# 覆盖 cost_impact/costImpact、penalty_cost、cost_multiplier、cost_level、gross_profit、
# net_benefit、penalty_savings、profit_protected、unit_price、amount 等复合字段，
# 而不是逐个样例打补丁。
FINANCIAL_TOKENS = ("cost", "amount", "price", "profit", "benefit", "savings", "penalty")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# 自然语言里内嵌的敏感数字/客户等级：仅按键名脱敏无法覆盖（键是 reasoning/explanation/
# final_strategy 等中性名，值却写着“违约罚金 180000”“总毛利为 632000”“A类关键订单”）。
# 以下正则对每个字符串值递归清洗，与键名脱敏共用同一入口，覆盖所有自然语言、解释、
# 推演(rebuttal/arbitration)和审计字段。
_NUM = r"\d[\d,，\.]*"
# 财务语义词后紧邻的金额/数字（毛利/罚金/利润/成本/收益/节省…）
_FIN_WORD = (
    r"(?:毛利|净利润|利润|罚金|违约金|违约|赔付|货值|营业收入|营收|营业额|应急成本|成本|"
    r"净收益|收益|节省|节约|金额|资金|保费|单价|售价|采购价|报价|价格|货款|敞口|损失)"
)
_MONEY_AFTER = re.compile(_FIN_WORD + r"(?:[^\d\n]{0,8}?)(" + _NUM + r")")
# 带货币后缀/前缀的金额
_MONEY_SUFFIX = re.compile(r"(" + _NUM + r")\s*(?:元|万元|万块|块钱|块|¥|￥|人民币|RMB)")
_MONEY_PREFIX = re.compile(r"(?:¥|￥|人民币|RMB)\s*(" + _NUM + r")")
# 客户等级：A类 / B/C类 / 等级为 A 等
_TIER = re.compile(r"[A-Ea-e](?:\s*/\s*[A-Ea-e])*\s*类")
_TIER_LEVEL = re.compile(r"(等级|级别)(?:[为是:：]\s*)?[A-Ea-e]\b")


def _normalize_key(key: str) -> str:
    """camelCase → snake_case，统一小写；costImpact → cost_impact。"""
    return _CAMEL_BOUNDARY.sub("_", key).replace("-", "_").lower()


def is_financial_key(key: str) -> bool:
    """字段名(规范化后)是否命中财务词根。"""
    normalized = _normalize_key(str(key))
    return any(token in normalized for token in FINANCIAL_TOKENS)


def _scrub_text(text: str, mask_financial: bool, mask_tier: bool) -> str:
    """清洗自然语言字符串里内嵌的敏感数字与客户等级。"""
    if mask_financial:
        text = _MONEY_AFTER.sub(lambda m: m.group(0).replace(m.group(1), MASK_PLACEHOLDER, 1), text)
        text = _MONEY_SUFFIX.sub(lambda m: m.group(0).replace(m.group(1), MASK_PLACEHOLDER, 1), text)
        text = _MONEY_PREFIX.sub(lambda m: m.group(0).replace(m.group(1), MASK_PLACEHOLDER, 1), text)
    if mask_tier:
        text = _TIER.sub("*类", text)
        text = _TIER_LEVEL.sub(lambda m: m.group(1) + MASK_PLACEHOLDER, text)
    return text


def mask_for_requester(payload: dict[str, Any], permissions: tuple[str, ...]) -> dict[str, Any]:
    """One masking path for detail and both exports; no export bypass exists.

    复用既有字段查看权限(field:cost:view / field:profit:view / field:customerLevel:view)，
    不新增权限码。GET decision-detail、JSON 导出、PDF 导出都经过这里，PDF 只消费本函数
    返回的脱敏 payload。除按键名脱敏外，还递归清洗自然语言字段里内嵌的金额/毛利/罚金/
    客户等级具体数字。
    """
    perms = set(permissions)
    superuser = "*" in perms
    can_view_cost = superuser or "field:cost:view" in perms
    can_view_profit = superuser or "field:profit:view" in perms
    can_view_tier = superuser or "field:customerLevel:view" in perms
    result = mask_payload(payload, "admin" if can_view_cost else "viewer")
    mask_financial = not (can_view_cost and can_view_profit)
    mask_tier = not can_view_tier
    if mask_financial or mask_tier:
        _deep_mask(result, mask_financial, mask_tier)
    return result


def _deep_mask(value: Any, mask_financial: bool, mask_tier: bool) -> Any:
    """递归：财务语义字段整体脱敏为 ***；所有字符串叶子再清洗内嵌敏感数字/等级。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if mask_financial and is_financial_key(key):
                value[key] = MASK_PLACEHOLDER
            else:
                value[key] = _deep_mask(item, mask_financial, mask_tier)
        return value
    if isinstance(value, list):
        return [_deep_mask(item, mask_financial, mask_tier) for item in value]
    if isinstance(value, str):
        return _scrub_text(value, mask_financial, mask_tier)
    return value


def render_pdf(payload: dict[str, Any]) -> bytes:
    """业务可读的中文决策报告；payload 必须已经过 mask_for_requester 脱敏。

    使用 platypus 表格/段落/分页，而非 json.dumps 文本墙。中文依赖 reportlab 内置
    CID 字体 STSong-Light（无需外部 ArialUnicode/Symbol）。
    """
    # Keep the API importable in minimal development installations; the image
    # ships reportlab through requirements and PDF export clearly reports a
    # missing optional runtime instead of exposing unmasked fallback data.
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            LongTable,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            TableStyle,
        )
    except ImportError as error:
        raise RuntimeError("PDF 导出依赖未安装") from error

    font = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(font))

    body = ParagraphStyle("body", fontName=font, fontSize=9, leading=13, alignment=TA_LEFT)
    label = ParagraphStyle("label", parent=body, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", fontName=font, fontSize=18, leading=24, spaceAfter=4, textColor=colors.HexColor("#1F2937"))
    h2 = ParagraphStyle("h2", fontName=font, fontSize=12, leading=18, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1D4ED8"))
    meta = ParagraphStyle("meta", parent=body, fontSize=8, textColor=colors.HexColor("#888888"))

    def esc(value: Any) -> str:
        text = "" if value is None else str(value)
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def para(value: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(esc(value) or "-", style)

    content_width = A4[0] - 32 * mm
    grid = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])
    header_grid = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1D4ED8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])

    def kv_table(rows: list[tuple[str, Any]]) -> LongTable:
        data = [[para(k, label), para(v)] for k, v in rows]
        table = LongTable(data, colWidths=[content_width * 0.32, content_width * 0.68])
        table.setStyle(grid)
        table.hAlign = "LEFT"
        return table

    def matrix_table(header: list[str], rows: list[list[Any]], weights: list[float]) -> LongTable:
        data = [[para(h, body) for h in header]] + [[para(cell) for cell in row] for row in rows]
        table = LongTable(data, colWidths=[content_width * w for w in weights], repeatRows=1)
        table.setStyle(header_grid)
        table.hAlign = "LEFT"
        return table

    audit = payload.get("audit_entry") or {}
    arbitration = payload.get("arbitration") or {}
    inventory = payload.get("inventory_risk") or {}
    conflict = payload.get("conflict") or {}
    constraint = payload.get("constraint_analysis") or {}
    game = payload.get("game_analysis") or {}
    proposals = payload.get("proposals") or []
    approvals = payload.get("approval_chain") or []

    # P1-12：PDF 统一中文业务文案，避免 submitted/high/ok 等英文状态与中英文异常空格。
    _STATUS_CN = {"submitted": "已提交", "pending": "待审批", "pending_countersign": "待会签", "approved": "已批准", "rejected": "已驳回", "withdrawn": "已撤回", "timeout_released": "超时放行", "overdue": "已逾期", "ok": "正常", "succeeded": "成功", "failed": "失败", "running": "进行中", "planning": "规划中", "deciding": "决策中", "approving": "审批中", "executing": "执行中", "closed": "已关闭"}
    _LEVEL_CN = {"high": "高", "medium": "中", "low": "低"}
    def cn_status(value: Any) -> str:
        return _STATUS_CN.get(str(value), "" if value is None else str(value))
    def cn_level(value: Any) -> str:
        return _LEVEL_CN.get(str(value), "" if value is None else str(value))

    story: list[Any] = [
        para("ChainGuard 决策报告", h1),
        para(f"报告编号 {payload.get('decision_id', '-')}", meta),
    ]

    story.append(para("一、决策基本信息", h2))
    story.append(kv_table([
        ("决策编号", audit.get("decision_id") or payload.get("decision_id")),
        ("生成时间", audit.get("timestamp")),
        ("触发事件类型", audit.get("event_type")),
        ("事件严重度", cn_level(audit.get("event_severity"))),
        ("库存风险指数", audit.get("inventory_risk_index")),
        ("决策状态", cn_status(audit.get("decision_status"))),
        ("是否需人工审批", "是" if audit.get("human_approval_required") else "否"),
        ("决策成本", audit.get("cost")),
        ("净收益", audit.get("net_benefit")),
        ("违约节省", audit.get("penalty_savings")),
        ("保护利润", audit.get("profit_protected")),
    ]))

    story.append(para("二、最终仲裁结论", h2))
    story.append(kv_table([
        ("最终决策", arbitration.get("final_decision_title")),
        ("综合评分", arbitration.get("final_score")),
    ]))
    if arbitration.get("final_strategy"):
        story.append(Spacer(1, 4))
        story.append(para(arbitration.get("final_strategy")))
    for point in (arbitration.get("execution_plan") or [])[:8]:
        story.append(para(f"· {point}"))

    story.append(para("三、方案摘要", h2))
    if proposals:
        rows = []
        for item in proposals:
            scores = item.get("scores") or {}
            rows.append([
                item.get("agent_name"),
                item.get("proposal_title"),
                item.get("total_score"),
                item.get("total_cost", item.get("cost")),
                scores.get("risk_reduction"),
            ])
        story.append(matrix_table(
            ["Agent", "方案", "综合分", "总成本", "降险分"],
            rows,
            [0.16, 0.42, 0.14, 0.14, 0.14],
        ))
    else:
        story.append(para("暂无方案数据"))

    story.append(para("四、审批链", h2))
    if approvals:
        rows = []
        for item in approvals:
            rows.append([
                item.get("submitter"),
                cn_status(item.get("status")),
                cn_level(item.get("riskLevel")),
                item.get("costImpact"),
                "是" if item.get("countersigned") else "否",
            ])
        story.append(matrix_table(
            ["提交人", "状态", "风险级别", "成本影响", "已会签"],
            rows,
            [0.24, 0.2, 0.18, 0.22, 0.16],
        ))
    else:
        story.append(para("暂无审批记录"))

    story.append(para("五、风险与推演结果", h2))
    story.append(kv_table([
        ("库存预警级别", inventory.get("warning_level")),
        ("库存风险指数", inventory.get("inventory_risk_index")),
        ("冲突类型", conflict.get("conflict_type")),
        ("冲突摘要", conflict.get("conflict_summary")),
        ("可行策略组合数", constraint.get("feasible_count")),
        ("最优系统效用", constraint.get("optimal_system_utility")),
        ("协同增益", game.get("coordination_gain")),
    ]))

    points = arbitration.get("manual_confirmation_points") or []
    if points:
        story.append(para("六、执行确认点", h2))
        for point in points:
            story.append(para(f"· {point}"))

    story.append(para("七、审计记录", h2))
    story.append(kv_table([
        ("审计决策编号", audit.get("decision_id")),
        ("时间戳", audit.get("timestamp")),
        ("状态", cn_status(audit.get("decision_status"))),
        ("错误信息", audit.get("error_message") or "无"),
    ]))

    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="ChainGuard 决策报告",
    )

    def draw_footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(16 * mm, 9 * mm, "ChainGuard 决策报告")
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return stream.getvalue()
