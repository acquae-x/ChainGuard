import { CheckCircleTwoTone, LoadingOutlined } from '@ant-design/icons';
import { Card, Space, Steps, Typography } from 'antd';
import { useEffect, useState } from 'react';

const agents = ['采购 Agent', '物流 Agent', '财务 Agent', '销售 Agent', '生产 Agent'];

export default function AgentProgress({ running, onFinish }: { running: boolean; onFinish?: () => void }) {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (!running) return;
    setCurrent(0);
    const timer = window.setInterval(() => {
      setCurrent((value) => {
        if (value >= agents.length) {
          window.clearInterval(timer);
          onFinish?.();
          return value;
        }
        return value + 1;
      });
    }, 520);
    return () => window.clearInterval(timer);
  }, [running]);

  return (
    <Card size="small" title="多 Agent 推演过程">
      <Steps
        current={Math.min(current, agents.length - 1)}
        items={agents.map((title, index) => ({
          title,
          description: index < current ? '已完成约束校验与收益评估' : index === current && running ? '正在推演' : '等待中',
          icon: index < current ? <CheckCircleTwoTone twoToneColor="#389E0D" /> : index === current && running ? <LoadingOutlined /> : undefined
        }))}
      />
      <Space direction="vertical" style={{ marginTop: 16 }}>
        <Typography.Text type="secondary">系统正在汇总采购、物流、财务、销售、生产视角，完成后将生成可对比方案。</Typography.Text>
      </Space>
    </Card>
  );
}
