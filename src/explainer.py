import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExplanationResult:
    arbitration_summary: str
    debate_narrative: str
    constraint_narrative: str
    llm_used: bool
    model_name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionExplainer:
    def __init__(
        self,
        endpoint: str = "http://localhost:11434/api/generate",
        model: str = "qwen2.5:latest",
        timeout: int = 15,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    def explain(self, result: dict[str, Any]) -> ExplanationResult:
        try:
            template = self._template_result(result)
            llm_text = self._call_llm(self._build_prompt(result))
            parsed = self._parse_llm_response(llm_text)
            if not any(parsed.values()):
                return template
            return ExplanationResult(
                arbitration_summary=parsed.get("arbitration_summary") or template.arbitration_summary,
                debate_narrative=parsed.get("debate_narrative") or template.debate_narrative,
                constraint_narrative=parsed.get("constraint_narrative") or template.constraint_narrative,
                llm_used=True,
                model_name=self.model,
            )
        except Exception:
            return self._template_result(result)

    def _call_llm(self, prompt: str) -> str:
        self._ensure_local_endpoint_available()
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise
        return str(data.get("response", ""))

    def _ensure_local_endpoint_available(self) -> None:
        parsed = urllib.parse.urlparse(self.endpoint)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((parsed.hostname, port), timeout=0.2):
                return
        except OSError as error:
            raise urllib.error.URLError(error) from error

    def _build_prompt(self, result: dict[str, Any]) -> str:
        values = self._extract_values(result)
        return (
            "你是供应链应急决策系统的解释专家。请用中文简洁解释以下已确定的决策分析结果。\n"
            "重要提示：以下所有数值均为系统确定性计算结果，你只需要解释，不得修改或重新推断数字。\n"
            f"推荐方案：{values['top_action']}（综合评分 {values['top_score']:.2f}）\n"
            f"多智能体辩论：共 {values['total_rounds']} 轮，{values['updated_count']} 个 Agent 接受策略更新，"
            f"系统效用 {values['system_utility_before']:.2f} -> {values['system_utility_after']:.2f}\n"
            f"约束求解：{values['feasible_count']} 个可行组合，最优系统效用 {values['optimal_system_utility']:.2f}\n\n"
            "请按以下格式回复，每项 1-2 句：\n"
            "仲裁：<解释>\n"
            "辩论：<解释>\n"
            "约束：<解释>\n"
        )

    @classmethod
    def _template_result(cls, result: dict[str, Any]) -> ExplanationResult:
        values = cls._extract_values(result)
        return ExplanationResult(
            arbitration_summary=(
                f"规则仲裁推荐方案「{values['top_action']}」，综合评分 {values['top_score']:.2f}，"
                "该结论来自已计算的供应覆盖、交期、成本和风险评分。"
            ),
            debate_narrative=(
                f"多智能体辩论共进行 {values['total_rounds']} 轮，"
                f"{values['updated_count']} 个 Agent 接受策略更新，"
                f"系统效用从 {values['system_utility_before']:.2f} 提升至 {values['system_utility_after']:.2f}。"
            ),
            constraint_narrative=(
                f"约束求解器评估出 {values['feasible_count']} 个满足硬约束的策略组合，"
                f"最优组合的系统效用为 {values['optimal_system_utility']:.2f}。"
            ),
            llm_used=False,
            model_name="template",
        )

    @staticmethod
    def _extract_values(result: dict[str, Any]) -> dict[str, Any]:
        proposals = result.get("proposals") or []
        top_proposal = max(
            proposals,
            key=lambda proposal: float(proposal.get("total_score") or 0.0),
            default={},
        )
        debate_result = result.get("debate_result") or {}
        constraint_analysis = result.get("constraint_analysis") or {}
        strategies_updated = debate_result.get("strategies_updated") or []
        return {
            "top_action": str(
                top_proposal.get("action")
                or top_proposal.get("proposal_title")
                or top_proposal.get("proposal")
                or "未知方案"
            ),
            "top_score": float(top_proposal.get("total_score") or 0.0),
            "total_rounds": int(debate_result.get("total_rounds") or 0),
            "updated_count": len(strategies_updated),
            "system_utility_before": float(debate_result.get("system_utility_before") or 0.0),
            "system_utility_after": float(debate_result.get("system_utility_after") or 0.0),
            "feasible_count": int(constraint_analysis.get("feasible_count") or 0),
            "optimal_system_utility": float(
                constraint_analysis.get("optimal_system_utility") or 0.0
            ),
        }

    @staticmethod
    def _parse_llm_response(text: str) -> dict[str, str]:
        parsed = {
            "arbitration_summary": "",
            "debate_narrative": "",
            "constraint_narrative": "",
        }
        label_map = {
            "仲裁": "arbitration_summary",
            "辩论": "debate_narrative",
            "约束": "constraint_narrative",
        }
        current_key = ""
        chunks: dict[str, list[str]] = {key: [] for key in parsed}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            matched_key = ""
            matched_body = ""
            for label, key in label_map.items():
                prefix = f"{label}："
                alternate_prefix = f"{label}:"
                if line.startswith(prefix):
                    matched_key = key
                    matched_body = line[len(prefix) :].strip()
                    break
                if line.startswith(alternate_prefix):
                    matched_key = key
                    matched_body = line[len(alternate_prefix) :].strip()
                    break
            if matched_key:
                current_key = matched_key
                if matched_body:
                    chunks[current_key].append(matched_body)
            elif current_key:
                chunks[current_key].append(line)
        return {
            key: " ".join(parts).strip()
            for key, parts in chunks.items()
        }
