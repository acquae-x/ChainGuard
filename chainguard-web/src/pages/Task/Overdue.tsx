import { useAccess } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Button, Card, Empty, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import { BellOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import { getTasks, urge } from '@/services/task';

const fmt = (v?: string) => { if (!v) return '-'; const d = new Date(v); return Number.isNaN(d.getTime()) ? v : d.toLocaleString('zh-CN'); };
const nameOf = (t: API.Task) => t.assigneeName || t.assignee || '未分配';

export default function TaskOverdue() {
  const access = useAccess();
  const [rows, setRows] = useState<API.Task[]>([]);
  // P1-6：由真实逾期任务聚合，不再硬编码 [3,1,2]。无 task:manage 时后端已按数据范围
  // 只返回本人任务，故明细即"我的逾期任务"，且不出现空"操作"列。
  const load = async () => {
    const r = await getTasks('overdue');
    const data = (r.data || []) as API.Task[];
    setRows(data);
    return { data, success: true, total: data.length };
  };
  useEffect(() => { load(); }, []);

  const agg = useMemo(() => {
    const map = new Map<string, number>();
    rows.forEach((t) => { const n = nameOf(t); map.set(n, (map.get(n) || 0) + 1); });
    return Array.from(map.entries());
  }, [rows]);

  const columns: ProColumns<API.Task>[] = [
    { title: '任务', dataIndex: 'title' },
    { title: '负责人', dataIndex: 'assigneeName', render: (_, r) => nameOf(r) },
    { title: '截止时间', dataIndex: 'dueAt', render: (_, r) => fmt(r.dueAt) },
    ...(access.canTaskManage
      ? [{
          title: '操作', valueType: 'option',
          render: (_: unknown, row: API.Task) => (
            <Button danger type="link" icon={<BellOutlined />} onClick={async () => { await urge(row.id); message.success('已发送站内信催办'); }}>催办</Button>
          ),
        } as ProColumns<API.Task>]
      : []),
  ];

  return (
    <PageContainer title="超时看板">
      <Card title="按负责人聚合" style={{ marginBottom: 16 }}>
        {agg.length ? (
          <ReactECharts
            style={{ height: 260 }}
            option={{
              tooltip: {},
              grid: { left: 8, right: 16, bottom: 8, containLabel: true },
              xAxis: { type: 'category', data: agg.map((x) => x[0]) },
              yAxis: { type: 'value', minInterval: 1 },
              series: [{ type: 'bar', barMaxWidth: 48, data: agg.map((x) => x[1]), itemStyle: { color: '#CF1322' } }],
            }}
          />
        ) : (
          <Empty description="当前无逾期任务" />
        )}
        <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
          共 {rows.length} 项逾期任务{agg.length ? `，涉及 ${agg.length} 名负责人` : ''}。
        </div>
      </Card>
      <ProTable<API.Task>
        headerTitle={access.canTaskManage ? '逾期明细（全部负责人）' : '我的逾期任务'}
        rowKey="id"
        search={false}
        pagination={false}
        request={load}
        columns={columns}
      />
    </PageContainer>
  );
}
