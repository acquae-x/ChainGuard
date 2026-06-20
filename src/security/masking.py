from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


DEFAULT_SENSITIVE_FIELDS = {
    "supplier_name": "mask",
    "customer_name": "mask",
    "vendor_name": "mask",
    "unit_price": "mask",
    "amount": "range",
    "cost": "range",
    "contact": "mask",
}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "security.yaml"


def mask_payload(payload: dict[str, Any], role: str) -> dict[str, Any]:
    data = copy.deepcopy(payload)
    if role == "admin":
        return data
    _mask_recursive(data, _load_rules())
    return data


def _mask_recursive(obj: Any, rules: dict[str, str]) -> None:
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if key in rules:
                obj[key] = _apply_rule(obj[key], rules[key])
            else:
                _mask_recursive(obj[key], rules)
    elif isinstance(obj, list):
        for item in obj:
            _mask_recursive(item, rules)


def _apply_rule(value: Any, rule: str) -> Any:
    if rule == "mask":
        return "***"
    if rule == "range":
        return _range_label(value)
    return value


def _range_label(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "***"
    if number < 10000:
        return "<1万"
    if number < 100000:
        return "1-10万"
    return ">10万"


def _load_rules() -> dict[str, str]:
    rules = dict(DEFAULT_SENSITIVE_FIELDS)
    if not _CONFIG_PATH.exists():
        return rules

    config_rules = _load_yaml_rules(_CONFIG_PATH)
    rules.update(config_rules)
    return rules


def _load_yaml_rules(path: Path) -> dict[str, str]:
    try:
        import yaml  # type: ignore
    except Exception:
        return _load_simple_yaml_rules(path)

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}

    raw_rules = loaded.get("sensitive_fields", loaded)
    if not isinstance(raw_rules, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw_rules.items()
        if str(value) in {"mask", "range"}
    }


def _load_simple_yaml_rules(path: Path) -> dict[str, str]:
    rules: dict[str, str] = {}
    in_sensitive_fields = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rules

    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")):
            key = line.rstrip(":").strip()
            in_sensitive_fields = key == "sensitive_fields"
            if ":" in line and not line.endswith(":"):
                field, value = _split_yaml_pair(line)
                if value in {"mask", "range"}:
                    rules[field] = value
            continue
        if in_sensitive_fields and ":" in line:
            field, value = _split_yaml_pair(line)
            if value in {"mask", "range"}:
                rules[field] = value
    return rules


def _split_yaml_pair(line: str) -> tuple[str, str]:
    key, value = line.split(":", 1)
    return key.strip(), value.strip().strip("\"'")

