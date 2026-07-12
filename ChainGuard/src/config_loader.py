from pathlib import Path
from typing import Any
from warnings import warn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("\"'")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_section: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"YAML 第 {line_number} 行格式不正确：{raw_line}")

        indent = len(line) - len(line.lstrip(" "))
        key, value = line.strip().split(":", 1)

        if indent == 0:
            if value.strip():
                parsed[key] = _parse_scalar(value)
                current_section = None
            else:
                parsed[key] = {}
                current_section = key
        elif indent == 2 and current_section:
            section = parsed.setdefault(current_section, {})
            if not isinstance(section, dict):
                raise ValueError(f"YAML 第 {line_number} 行无法挂载到非对象节点：{raw_line}")
            section[key] = _parse_scalar(value)
        else:
            raise ValueError(f"YAML 第 {line_number} 行缩进不受支持：{raw_line}")

    return parsed


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")

    text = config_path.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_simple_yaml(text)

    loaded = yaml.safe_load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"配置文件必须是 YAML 对象：{config_path}")
    return loaded


def load_risk_weights() -> dict[str, Any]:
    return load_yaml_config(CONFIG_DIR / "risk_weights.yaml")


def load_thresholds() -> dict[str, Any]:
    return load_yaml_config(CONFIG_DIR / "thresholds.yaml")


def validate_weights_sum(weights: dict[str, float]) -> bool:
    total = sum(float(value) for value in weights.values())
    is_valid = abs(total - 1.0) < 0.0001
    if not is_valid:
        warn(f"权重和为 {total:.4f}，不等于 1；请检查配置。", stacklevel=2)
    return is_valid
