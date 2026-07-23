import { AlertOutlined, ExclamationCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { Tag } from 'antd';
import { RISK_LEVEL_META, type RiskLevel } from '@/constants/status';

const icons = {
  high: <AlertOutlined />,
  medium: <ExclamationCircleOutlined />,
  low: <InfoCircleOutlined />
};

export default function RiskTag({ level }: { level?: RiskLevel }) {
  const current = level || 'low';
  // 防御：后端出现映射外的等级值时降级展示原文，绝不让整页崩溃（评审修复：reading 'color' 白屏）
  const meta = RISK_LEVEL_META[current] || { text: String(current), color: 'default', marker: '', score: '' };
  return (
    <Tag color={meta.color} icon={icons[current]}>
      {meta.text} {meta.marker}
    </Tag>
  );
}
