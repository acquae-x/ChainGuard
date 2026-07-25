"""双轨阈值的安全属性测试。

所有期望值都在注释里从第一性原理算出（均值、总体标准差、mean+kσ），
不是把实现跑一遍再把输出抄进断言——否则实现错了测试跟着错。

两个必须成立的属性（也是纯相对阈值单独使用时的两个失效模式）：
1. 全线健康不虚报：一批都安全时，批内最高的那个不能被判成高危。
2. 全线告急不静默：一批都危险时，相对轨会把高危节点当成"普通"，
   因此绝对轨必须存在——本文件锁死这个前提，防止有人日后删掉绝对轨。
"""

from src.threshold_calibration import (
    ACTION_THRESHOLD,
    RELATIVE_ESCALATION_FLOOR,
    WARNING_THRESHOLD,
    WATCH_THRESHOLD,
    calibrate_monitor_thresholds,
    classify_status,
    is_calibrated,
    relative_status,
)

EXPERT = (WATCH_THRESHOLD, WARNING_THRESHOLD, ACTION_THRESHOLD)


def test_all_healthy_batch_does_not_escalate_top_node():
    """全线健康不虚报——绝对地板拦住"批内最差"。

    values = [10,12,14,16,18,20,22,24]，n=8
    mean = 136/8 = 17
    偏差 ±7,±5,±3,±1 → 平方和 2*(49+25+9+1) = 168 → 方差 168/8 = 21
    pstdev = sqrt(21) = 4.5826
    warning 线 = 17 + 1.5*4.5826 = 23.874
    最高节点 24 ≥ 23.874 → 纯 z-score 判定为 warning（这就是虚报）
    但 24 < 地板 35 → relative_status 必须返回 normal。
    """
    values = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0]
    thresholds = calibrate_monitor_thresholds(values)

    # 先证明"如果没有地板会怎样"：纯 z-score 确实会把 24 判成 warning。
    assert classify_status(24.0, thresholds=thresholds)[0] == "warning"

    # 加上地板后不升级——这正是虚报被挡住的地方。
    assert relative_status(24.0, thresholds) == "normal"
    assert 24.0 < RELATIVE_ESCALATION_FLOOR


def test_system_wide_crisis_makes_relative_track_go_silent():
    """全线告急时相对轨会静默——所以绝对轨不可删。

    values = [88..95] 步长 1，n=8
    mean = 732/8 = 91.5
    偏差 ±3.5,±2.5,±1.5,±0.5 → 平方和 2*(12.25+6.25+2.25+0.25) = 42 → 方差 42/8 = 5.25
    pstdev = sqrt(5.25) = 2.2913
    watch = 91.5 + 0.5*2.2913 = 92.65
    warning = 91.5 + 1.5*2.2913 = 94.94
    风险 94 的节点（绝对意义上极度危险）落在 watch 与 warning 之间
    → 相对轨只给 watch，不升级。若系统只有相对轨，这就是告警静默。
    """
    values = [88.0, 89.0, 90.0, 91.0, 92.0, 93.0, 94.0, 95.0]
    thresholds = calibrate_monitor_thresholds(values)

    assert relative_status(94.0, thresholds) == "watch"
    # watch 不在升级表里（node_health._HEALTH_BY_RELATIVE 只认 warning/action_required），
    # 即相对轨对这个 94 分节点不产生任何升级。绝对轨必须兜底。
    assert relative_status(94.0, thresholds) not in ("warning", "action_required")


def test_floor_does_not_block_legitimate_escalation():
    """地板只挡低分虚报，不挡真正的高分离群。

    values = [20,25,30,35,40,45,50,55]，n=8
    mean = 300/8 = 37.5
    偏差 ±17.5,±12.5,±7.5,±2.5 → 平方和 2*(306.25+156.25+56.25+6.25) = 1050
    方差 = 1050/8 = 131.25 → pstdev = 11.456
    warning = 37.5 + 1.5*11.456 = 54.68
    节点 55 ≥ 54.68 且 55 ≥ 地板 35 → 必须升级为 warning。
    """
    values = [20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0]
    thresholds = calibrate_monitor_thresholds(values)

    assert relative_status(55.0, thresholds) == "warning"


def test_insufficient_samples_fall_back_to_expert():
    """样本 < 8 时不做数据驱动推导——小样本的均值和方差不可信。"""
    thresholds = calibrate_monitor_thresholds([10.0, 90.0, 50.0])

    assert thresholds == EXPERT
    assert is_calibrated(thresholds) is False


def test_zero_dispersion_falls_back_to_expert():
    """整批同分时 σ=0，mean+kσ 三档会重合成一个点，无法分档 → 回退专家常量。"""
    thresholds = calibrate_monitor_thresholds([40.0] * 12)

    assert thresholds == EXPERT
    assert is_calibrated(thresholds) is False


def test_calibrated_thresholds_are_flagged_as_calibrated():
    """有效样本推导出的阈值必须被标成 calibrated，供 UI 区分来源。"""
    values = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0]
    thresholds = calibrate_monitor_thresholds(values)

    assert thresholds != EXPERT
    assert is_calibrated(thresholds) is True


def test_relative_status_without_thresholds_never_escalates():
    """没有校准结果时（如物料数为 0）相对轨保持沉默，不得凭空升级。"""
    assert relative_status(99.0, None) == "normal"
