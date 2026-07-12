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
  const meta = RISK_LEVEL_META[current];
  return (
    <Tag color={meta.color} icon={icons[current]}>
      {meta.text} {meta.marker}
    </Tag>
  );
}
