import { Access, history, useAccess, useParams } from "@umijs/max";
import { PageContainer, ProTable } from "@ant-design/pro-components";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Divider,
  Drawer,
  Flex,
  Grid,
  Result,
  Steps,
  Table,
  Tabs,
  Typography,
} from "antd";
import { DownloadOutlined, EyeOutlined, LinkOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import {
  ApprovalActionBar,
  EmptyGuide,
  RiskTag,
  SensitiveField,
  StatusTag,
  DecisionTrace,
} from "@/components";
import {
  approve,
  countersign,
  getApprovalDetail,
  getApprovals,
  recalcRequest,
  reject,
  submitHighApproval,
  transfer,
  withdrawApproval,
  ratifyApprove,
  ratifyObject,
} from "@/services/approval";
import { exportDecisionDetail } from '@/services/decision';
import { daysLabel, isMissing, riskLabel, MISSING_TEXT } from '@/utils/proposalMetrics';

function ApprovalDetail({
  detail,
  onDone,
}: {
  detail: any;
  onDone: () => void;
}) {
  const access = useAccess();
  const screens = Grid.useBreakpoint();
  const { message } = App.useApp();
  const riskLevel = detail.approval.riskLevel;
  const canApprove =
    riskLevel === "low"
      ? access.canApproveLow
      : riskLevel === "medium"
        ? access.canApproveMedium
        : riskLevel === "high" && access.canApproveHigh;
  // 待会签阶段主审动作只读：批准/驳回/重算/转交仅在待审状态显示；会签人只看到会签+拒签
  const awaitingReview = ["submitted", "pending", "transferred"].includes(detail.approval.status);
  const canCountersignNow =
    !detail.approval.countersigned &&
    access.canCountersign &&
    detail.approval.status === "pending_countersign" &&
    (riskLevel === "high" ||
      (riskLevel === "medium" && detail.approval.costImpact > 50000));
  const timedOut = detail.approval.history?.some((item: any) => item.action === 'countersign_timeout_release');
  const alreadyRatified = detail.approval.history?.some((item: any) => item.action === 'ratify_approve' || item.action === 'ratify_object');
  const capabilities = {
    approve: canApprove && awaitingReview,
    // P2-12：提交/撤回按钮跟随审批单实际状态，动作完成后 onDone 重拉详情即时刷新
    submit: riskLevel === "high" && access.canSubmitHigh && detail.approval.status === "submitted",
    withdraw: riskLevel === "high" && access.canSubmitHigh && ["submitted", "pending"].includes(detail.approval.status),
    countersign: canCountersignNow,
    reviewActions: canApprove && awaitingReview,
    rejectOnly: canCountersignNow,
    ratify: access.canCountersign && detail.approval.status === 'approved' && timedOut && !alreadyRatified,
    // 有执行确认点的单据，批准弹窗强制勾选"已逐项核对"
    requireConfirmPoints: (detail.decisionDetail?.arbitration?.manual_confirmation_points || []).length > 0,
  };
  const { requireConfirmPoints: _flag, ...actionCaps } = capabilities;
  const hasAction = Object.values(actionCaps).some(Boolean);
  const comparison = detail.comparison;
  // P0-2 口径：未知值不得伪装成 0，缺失一律显示"数据缺失"（与方案列表/推演摘要共用 proposalMetrics）
  const missing = isMissing;
  const fmtDays = daysLabel;
  const fmtCustomer = (proposal: any) =>
    missing(proposal.customerImpact)
      ? MISSING_TEXT
      : `${proposal.customerImpact} 个订单，高等级客户 ${missing(proposal.highValueCustomers) ? '未知' : proposal.highValueCustomers} 个`;
  const tableRows = [
    {
      metric: "总成本",
      current: comparison.current.totalCost,
      baseline: comparison.baseline.totalCost,
      alternative: comparison.alternative.totalCost,
    },
    {
      metric: "交期影响",
      current: fmtDays(comparison.current.leadTimeImpact),
      baseline: fmtDays(comparison.baseline.leadTimeImpact),
      alternative: fmtDays(comparison.alternative.leadTimeImpact),
    },
    {
      metric: "剩余风险",
      current: riskLabel(comparison.current.residualRisk),
      baseline: riskLabel(comparison.baseline.residualRisk),
      alternative: riskLabel(comparison.alternative.residualRisk),
    },
  ];
  const handleAction = async (action: string, values?: any) => {
    const id = detail.approval.id;
    if (action === "approve") await approve(id, values);
    if (action === "submit") await submitHighApproval(id);
    if (action === "withdraw") await withdrawApproval(id);
    if (action === "countersign") await countersign(id);
    if (action === "reject") await reject(id, values);
    if (action === "recalc") await recalcRequest(id, values);
    if (action === "transfer") await transfer(id, values);
    if (action === 'ratify_approve') await ratifyApprove(id);
    if (action === 'ratify_object') await ratifyObject(id, values);
    message.success(
      action === "approve" && riskLevel === "high"
        ? "老板已批准，进入待会签：财务会签后生效并生成任务"
        : action === "approve"
          ? "审批通过，执行任务已生成"
          : action === "countersign"
            ? "会签完成，任务已自动拆解"
            : action === 'ratify_approve'
              ? "追认通过已记录，已通知老板与提交人"
              : action === 'ratify_object'
                ? "追认异议已记录，已通知老板与提交人"
                : "审批已处理",
    );
    // P1-8 修复：终批后停留在审批详情刷新状态；只有真正 approved（任务已生成）才在页面上提供任务入口
    onDone();
  };
  const [traceOpen, setTraceOpen] = useState(false);
  return (
    <div style={{ width: "100%", minWidth: 0, maxWidth: "100%", paddingBottom: screens.md ? 0 : 76 }}>
      <Alert
        type={riskLevel === "high" ? "warning" : "info"}
        showIcon
        message={detail.alert}
      />
      {detail.approval.status === "pending_countersign" && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="待会签：财务会签后生效；超过配置时限将自动放行并通知财务追认。" />}
      {timedOut && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="已超时自动放行：任务不会回滚，财务可追认通过或提交异议（必须填写理由）。" />}
      {detail.approval.status === "approved" && (
        <Alert
          style={{ marginTop: 12 }}
          type="success"
          showIcon
          message="审批已生效，执行任务已生成。"
          action={<Button size="small" type="primary" onClick={() => history.push("/task/all")}>查看执行任务</Button>}
        />
      )}
      <Descriptions
        title="决策摘要"
        bordered
        size="small"
        column={screens.md ? 2 : 1}
        style={{ marginTop: 16, maxWidth: "100%", overflowX: "auto" }}
        items={[
          {
            key: "risk",
            label: "风险等级",
            children: <RiskTag level={riskLevel} />,
          },
          {
            key: "cost",
            label: "总成本",
            children: missing(detail.proposal.totalCost) ? (
              <Typography.Text type="secondary">成本数据缺失：引擎未给出可信成本，待人工测算</Typography.Text>
            ) : (
              <SensitiveField
                field="cost"
                value={`¥${detail.proposal.totalCost.toLocaleString()}`}
              />
            ),
          },
          {
            key: "customer",
            label: "客户影响",
            children: fmtCustomer(detail.proposal),
          },
          {
            key: "lead",
            label: "交期影响",
            children: fmtDays(detail.proposal.leadTimeImpact),
          },
          {
            key: "reason",
            label: "系统推荐理由",
            span: screens.md ? 2 : 1,
            children: detail.proposal.reason,
          },
        ]}
      />
      <Button
        type="link"
        icon={<LinkOutlined />}
        onClick={() => setTraceOpen(true)}
      >
        查看完整推演
      </Button>
      <Button type="link" icon={<DownloadOutlined />} onClick={async () => { try { await exportDecisionDetail(detail.approval.incidentId, 'json'); } catch (reason) { message.error(reason instanceof Error ? reason.message : '导出失败，请稍后重试'); } }}>导出报告</Button>
      <Divider>执行确认点</Divider>
      {(detail.decisionDetail?.arbitration?.manual_confirmation_points || []).length ? <Descriptions column={1} size="small" items={detail.decisionDetail.arbitration.manual_confirmation_points.map((item: string, index: number) => ({ key: String(index), label: `确认点 ${index + 1}`, children: item }))} /> : <Typography.Text type="secondary">完整推演生成后将在这里列出执行确认点。</Typography.Text>}
      <Divider>方案对比</Divider>
      <Table
        size="small"
        pagination={false}
        rowKey="metric"
        dataSource={tableRows}
        columns={[
          { title: "指标", dataIndex: "metric" },
          ...["current", "baseline", "alternative"].map((key, index) => ({
            title: ["本方案", "基线不作为", "次优方案"][index],
            dataIndex: key,
            render: (value: any, row: any) => {
              if (row.metric === "总成本") {
                return missing(value)
                  ? <Typography.Text type="secondary">成本数据缺失：该候选未纳入成本测算，待人工确认</Typography.Text>
                  : <SensitiveField field="cost" value={`¥${Number(value).toLocaleString()}`} />;
              }
              if (row.metric === "交期影响" && (value === MISSING_TEXT || value == null)) {
                return <Typography.Text type="secondary">交期数据缺失：待供应商确认到货窗口</Typography.Text>;
              }
              return value;
            },
          })),
        ]}
        scroll={{ x: 520 }}
      />
      <Divider>审批链</Divider>
      <Steps
        direction="vertical"
        // P1-9 修复：approved 时全链完成（current 越过末位即全部 finish）；待会签停在第三步
        current={
          detail.approval.status === "approved"
            ? detail.chain.length
            : detail.approval.status === "pending_countersign"
              ? Math.max(0, detail.chain.length - 1)
              : Math.min(1, Math.max(0, detail.chain.length - 1))
        }
        items={detail.chain.map((title: string) => ({ title }))}
      />
      <Divider />
      <Flex
        justify="space-between"
        align="center"
        gap={16}
        wrap="wrap"
        style={
          screens.md
            ? undefined
            : {
                position: "sticky",
                bottom: 0,
                background: "#fff",
                padding: "12px 0",
                zIndex: 2,
              }
        }
      >
        <Typography.Text type="secondary">
          审批动作将写入审计日志
        </Typography.Text>
        <Access
          accessible={hasAction}
          fallback={
            <Typography.Text type="secondary">
              当前角色仅可查看审批记录
            </Typography.Text>
          }
        >
          <ApprovalActionBar
            capabilities={capabilities}
            onDone={handleAction}
          />
        </Access>
      </Flex>
      <DecisionTrace incidentId={detail.approval.incidentId} open={traceOpen} onClose={() => setTraceOpen(false)} />
    </div>
  );
}

export default function DecisionApproval() {
  const access = useAccess();
  const screens = Grid.useBreakpoint();
  const { id } = useParams<{ id?: string }>();
  const query = new URLSearchParams(location.search);
  const [tab, setTab] = useState(query.get("tab") || "pending");
  const [detail, setDetail] = useState<any>();
  const [error, setError] = useState<string>();
  const actionRef = useRef<any>();
  const loadDetail = async (approvalId: string) => {
    setError(undefined);
    try {
      setDetail(await getApprovalDetail(approvalId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批详情加载失败");
    }
  };
  useEffect(() => {
    if (id) loadDetail(id);
  }, [id]);
  const changeTab = (key: string) => {
    setTab(key);
    history.replace(`/decision/approval?tab=${key}`);
  };
  if (id && screens.xl)
    return (
      <PageContainer
        style={{ width: "100%", minWidth: 0, maxWidth: "100%" }}
        title={`审批详情 ${detail?.approval?.id || ""}`}
        extra={
          <Button
            onClick={() => history.push("/decision/approval?tab=pending")}
          >
            返回审批中心
          </Button>
        }
      >
        {error ? (
          <Result
            status="500"
            title="审批服务暂时不可用"
            subTitle={error}
            extra={
              <Button type="primary" onClick={() => loadDetail(id)}>
                重试
              </Button>
            }
          />
        ) : detail ? (
          <ApprovalDetail detail={detail} onDone={() => loadDetail(id)} />
        ) : (
          <Typography.Text>加载中...</Typography.Text>
        )}
      </PageContainer>
    );
  if (error && !id)
    return (
      <PageContainer title="审批中心" style={{ width: "100%", minWidth: 0, maxWidth: "100%" }}>
        <Result
          status="500"
          title="审批服务暂时不可用"
          subTitle={error}
          extra={
            <Button type="primary" onClick={() => { setError(undefined); actionRef.current?.reload(); }}>
              重试
            </Button>
          }
        />
      </PageContainer>
    );
  return (
    <PageContainer
      title="审批中心"
      subTitle="在同一页面完成判断、对比与审批"
      style={{ width: "100%", minWidth: 0, maxWidth: "100%" }}
    >
      <Tabs
        activeKey={tab}
        onChange={changeTab}
        items={[
          { key: "pending", label: "待我审批" },
          { key: "done", label: "我已审批" },
          { key: "cc", label: "抄送我" },
        ]}
      />
      <div style={{ width: "100%", minWidth: 0, maxWidth: "100%", overflowX: "auto" }}>
      <ProTable<API.Approval>
        actionRef={actionRef}
        rowKey="id"
        search={false}
        locale={{
          emptyText: (
            <EmptyGuide
              title="当前分类暂无审批单"
              description="切换分类可查看其他审批记录。"
            />
          ),
        }}
        params={{ tab }}
        request={async (params) => {
          // params.tab 变化时 ProTable 会自动重新请求，保证切换 tab 后列表刷新
          try {
            setError(undefined);
            return await getApprovals((params as { tab?: string }).tab || "pending");
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : "审批列表加载失败");
            return { data: [], total: 0, success: false };
          }
        }}
        columns={[
          { title: "审批单号", dataIndex: "id", copyable: true, width: 180 },
          { title: "事件", dataIndex: "incidentId", width: 160 },
          {
            title: "风险",
            dataIndex: "riskLevel",
            width: 90,
            render: (_, item) => (
              <RiskTag level={item.riskLevel as "high" | "medium" | "low"} />
            ),
          },
          { title: "方案摘要", dataIndex: "summary", width: 240 },
          {
            title: "成本影响",
            dataIndex: "costImpact",
            width: 130,
            render: (_, item) =>
              item.costImpact === null || item.costImpact === undefined ? (
                "数据缺失"
              ) : (
                <SensitiveField
                  field="cost"
                  value={`¥${item.costImpact.toLocaleString()}`}
                />
              ),
          },
          { title: "提交人", dataIndex: "submitter", width: 130 },
          {
            title: "等待时长",
            dataIndex: "waitingHours",
            width: 110,
            render: (_, item) => (
              <Typography.Text
                type={item.waitingHours > 24 ? "danger" : undefined}
              >
                {item.waitingHours} 小时
              </Typography.Text>
            ),
          },
          {
            title: "操作",
            valueType: "option",
            width: 110,
            render: (_, item) => (
              <Button
                type="link"
                icon={<EyeOutlined />}
                onClick={() =>
                  screens.xl
                    ? history.push(`/decision/approval/${item.id}?tab=${tab}`)
                    : loadDetail(item.id)
                }
              >
                审批详情
              </Button>
            ),
          },
        ]}
        scroll={{ x: 1150 }}
      />
      </div>
      <Drawer
        width="100%"
        // P1-7：长审批单号在 375px 下必须可换行/省略，不得撑破抽屉头部
        title={
          <Typography.Text style={{ maxWidth: "100%", wordBreak: "break-all", whiteSpace: "normal" }}>
            {`审批详情 ${detail?.approval?.id || ""}`}
          </Typography.Text>
        }
        open={!!detail}
        onClose={() => setDetail(undefined)}
        extra={<StatusTag status={detail?.approval?.status || "pending"} />}
        rootStyle={{ maxWidth: "100vw" }}
        styles={{ body: { minWidth: 0, padding: screens.sm ? 24 : 12 } }}
      >
        {detail && (
          <ApprovalDetail
            detail={detail}
            // P2-12/P1-9：动作完成后原地刷新详情与列表，而不是直接关闭抽屉丢状态
            onDone={() => {
              if (detail?.approval?.id) loadDetail(detail.approval.id);
              actionRef.current?.reload();
            }}
          />
        )}
      </Drawer>
    </PageContainer>
  );
}
