// 降级提示黄条（对应 Phase 2 §2.2）。显式提示演示模式 / 后端不可用，禁止静默降级。
import { Alert } from 'antd';
import { DATA_MODE, useBackendState } from '../../services/dataMode';

export default function DegradeBanner() {
  const { down, reason, dismissed, dismiss } = useBackendState();

  if (DATA_MODE === 'mock') {
    return (
      <Alert
        type="warning"
        banner
        showIcon
        message="当前为演示数据模式（DATA_MODE=mock）：数据来自内置演练数据，非真实后端。"
      />
    );
  }

  if (down && !dismissed) {
    return (
      <Alert
        type="warning"
        banner
        showIcon
        closable
        onClose={dismiss}
        message={`后端服务暂不可用${reason ? `：${reason}` : ''}。部分数据可能为离线演示数据，请稍后重试或联系管理员。`}
      />
    );
  }

  return null;
}
