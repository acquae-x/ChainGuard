"""阈值校准:绝对专家阈值与相对离群阈值的纯函数实现。

本模块**不依赖**任何数据源、场景加载器或决策编排——只接受一组风险值,返回阈值。
这样租户侧 API(node_health)可以复用它,而不把演示管道耦合进来。

两条判定轨道:

- **绝对轨**:config/thresholds.yaml 的专家阈值(库存支撑红线/黄线),由引擎自身
  产出 warning_level。它保证"真危险一定报"——不受本批分布影响。
- **相对轨**:本模块的 ``calibrate_monitor_thresholds``,从本批风险分布推导
  均值 + k·标准差,识别"相对本批明显离群"的节点。

相对轨单独使用是**危险**的,因为 z-score 是相对量:全线告急时均值被抬高,真正的
高危节点反而落回均值附近而不报警;全线健康时又会把批内最高的安全节点判成高危。
因此本模块给相对轨设了绝对地板 ``RELATIVE_ESCALATION_FLOOR``——低于观察线的节点
无论多离群都不升级,并且调用方必须取两轨的**较严者**(见 node_health)。
"""

import statistics

# 专家回退阈值(样本不足/无离散度时使用),同时也是相对轨的绝对地板来源。
WATCH_THRESHOLD: float = 35.0
WARNING_THRESHOLD: float = 55.0
ACTION_THRESHOLD: float = 70.0

# 数据驱动校准所需的最小节点数;低于此用回退常量。
MIN_CALIBRATION_NODES: int = 8

# z-score 离群系数:均值 + k·标准差。识别"相对最高风险"的节点而非依赖绝对硬阈值。
_WATCH_K: float = 0.5
_WARNING_K: float = 1.5
_ACTION_K: float = 2.5

# 相对轨的绝对地板:风险指数低于观察线时,"相对最差"不具备行动意义。
# 没有这道地板,一批全健康节点里分数最高的那个会被判成高危(虚报)。
RELATIVE_ESCALATION_FLOOR: float = WATCH_THRESHOLD


def calibrate_monitor_thresholds(
    risk_values: list[float],
) -> tuple[float, float, float]:
    """从一批风险分布数据驱动地推导 (watch, warning, action) 阈值。

    方法:均值 + k·标准差(z-score 离群)。样本不足(< MIN_CALIBRATION_NODES)
    或分布无离散度 → 回退专家常量。
    """
    values = [float(v) for v in risk_values if v is not None]
    if len(values) < MIN_CALIBRATION_NODES:
        return WATCH_THRESHOLD, WARNING_THRESHOLD, ACTION_THRESHOLD
    mean = statistics.mean(values)
    sd = statistics.pstdev(values)
    if sd <= 1e-6:
        return WATCH_THRESHOLD, WARNING_THRESHOLD, ACTION_THRESHOLD
    return (mean + _WATCH_K * sd, mean + _WARNING_K * sd, mean + _ACTION_K * sd)


def is_calibrated(thresholds: tuple[float, float, float]) -> bool:
    """该组阈值是数据推导出来的,还是回退到了专家常量。"""
    return thresholds != (WATCH_THRESHOLD, WARNING_THRESHOLD, ACTION_THRESHOLD)


def classify_status(
    risk_index: float,
    *,
    thresholds: tuple[float, float, float] | None = None,
) -> tuple[str, str]:
    """把风险值映射为监控状态。

    thresholds=(watch, warning, action);缺省时用专家回退常量(保持纯函数默认行为)。
    """
    watch, warning, action = thresholds or (
        WATCH_THRESHOLD,
        WARNING_THRESHOLD,
        ACTION_THRESHOLD,
    )
    if risk_index >= action:
        return "action_required", "立即进入决策流程"
    if risk_index >= warning:
        return "warning", "准备预案，关注节点"
    if risk_index >= watch:
        return "watch", "持续观察"
    return "normal", "无需干预"


def relative_status(
    risk_index: float,
    thresholds: tuple[float, float, float] | None,
    *,
    floor: float = RELATIVE_ESCALATION_FLOOR,
) -> str:
    """相对轨判定,带绝对地板。

    低于 ``floor`` 一律返回 "normal"——批内最差不等于值得行动。
    """
    if thresholds is None or float(risk_index) < floor:
        return "normal"
    status, _ = classify_status(float(risk_index), thresholds=thresholds)
    return status
