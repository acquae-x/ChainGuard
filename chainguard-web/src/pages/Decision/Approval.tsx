import { Access, history, useAccess, useParams } from "@umijs/max";
import { PageContainer, ProTable } from "@ant-design/pro-components";
import {
  Alert,
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
  message,
} from "antd";
import { EyeOutlined, LinkOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import {
  ApprovalActionBar,
  EmptyGuide,
  RiskTag,
  SensitiveField,
  StatusTag,
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
} from "@/services/approval";

function ApprovalDetail({
  detail,
  onDone,
}: {
  detail: any;
  onDone: () => void;
}) {
  const access = useAccess();
  const screens = Grid.useBreakpoint();
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
  const capabilities = {
    approve: canApprove && awaitingReview,
    submit: riskLevel === "high" && access.canSubmitHigh,
    withdraw: riskLevel === "high" && access.canSubmitHigh,
    countersign: canCountersignNow,
    reviewActions: canApprove && awaitingReview,
    rejectOnly: canCountersignNow,
  };
  const hasAction = Object.values(capabilities).some(Boolean);
  const comparison = detail.comparison;
  const tableRows = [
    {
      metric: "总成本",
      current: comparison.current.totalCost,
      baseline: comparison.baseline.totalCost,
      alternative: comparison.alternative.totalCost,
    },
    {
      metric: "交期影响",
      current: `${comparison.current.leadTimeImpact} 天`,
      baseline: `${comparison.baseline.leadTimeImpact} 天`,
      alternative: `${comparison.alternative.leadTimeImpact} 天`,
    },
    {
      metric: "剩余风险",
      current: comparison.current.residualRisk,
      baseline: comparison.baseline.residualRisk,
      alternative: comparison.alternative.residualRisk,
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
    message.success(
      action === "approve" && riskLevel === "high" ? "老板已批准，等待财务会签后生成任务" : action === "countersign" ? "会签完成，任务已自动拆解" : "审批已处理",
    );
    onDone();
    if (action === "approve") history.push("/task/all");
  };
  return (
    <>
      <Alert
        type={riskLevel === "high" ? "warning" : "info"}
        showIcon
        message={detail.alert}
      />
      {detail.approval.status === "pending_countersign" && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="待会签：财务会签后生效；超过配置时限将自动放行并通知财务追认。" />}
      <Descriptions
        title="决策摘要"
        bordered
        size="small"
        column={screens.md ? 2 : 1}
        style={{ marginTop: 16 }}
        items={[
          {
            key: "risk",
            label: "风险等级",
            children: <RiskTag level={riskLevel} />,
          },
          {
            key: "cost",
            label: "总成本",
            children: (
              <SensitiveField
                field="cost"
                value={`¥${detail.proposal.totalCost.toLocaleString()}`}
              />
            ),
          },
          {
            key: "customer",
            label: "客户影响",
            children: `${detail.proposal.customerImpact} 个订单，高等级客户 ${detail.proposal.highValueCustomers} 个`,
          },
          {
            key: "lead",
            label: "交期影响",
            children: `${detail.proposal.leadTimeImpact} 天`,
          },
          {
            key: "reason",
            label: "系统推荐理由",
            span: 2,
            children: detail.proposal.reason,
          },
        ]}
      />
      <Button
        type="link"
        icon={<LinkOutlined />}
        onClick={() =>
          history.push(
            `/decision/generate/${detail.approval.incidentId}?readonly=1`,
          )
        }
      >
        查看完整推演
      </Button>
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
            render: (value: any, row: any) =>
              row.metric === "总成本" ? (
                <SensitiveField
                  field="cost"
                  value={`¥${Number(value).toLocaleString()}`}
                />
              ) : (
                value
              ),
          })),
        ]}
        scroll={{ x: 520 }}
      />
      <Divider>审批链</Divider>
      <Steps
        direction="vertical"
        current={
          detail.approval.status === "approved"
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
    </>
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
      <PageContainer title="审批中心">
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
    <PageContainer title="审批中心" subTitle="在同一页面完成判断、对比与审批">
      <Tabs
        activeKey={tab}
        onChange={changeTab}
        items={[
          { key: "pending", label: "待我审批" },
          { key: "done", label: "我已审批" },
          { key: "cc", label: "抄送我" },
        ]}
      />
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
          { title: "审批单号", dataIndex: "id", copyable: true },
          { title: "事件", dataIndex: "incidentId" },
          {
            title: "风险",
            dataIndex: "riskLevel",
            render: (_, item) => (
              <RiskTag level={item.riskLevel as "high" | "medium" | "low"} />
            ),
          },
          { title: "方案摘要", dataIndex: "summary" },
          {
            title: "成本影响",
            dataIndex: "costImpact",
            render: (_, item) => (
              <SensitiveField
                field="cost"
                value={`¥${item.costImpact.toLocaleString()}`}
              />
            ),
          },
          { title: "提交人", dataIndex: "submitter" },
          {
            title: "等待时长",
            dataIndex: "waitingHours",
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
      />
      <Drawer
        width="100%"
        title={`审批详情 ${detail?.approval?.id || ""}`}
        open={!!detail}
        onClose={() => setDetail(undefined)}
        extra={<StatusTag status={detail?.approval?.status || "pending"} />}
      >
        {detail && (
          <ApprovalDetail
            detail={detail}
            onDone={() => {
              setDetail(undefined);
            }}
          />
        )}
      </Drawer>
    </PageContainer>
  );
}
