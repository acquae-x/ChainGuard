import { LockOutlined } from '@ant-design/icons';
import { Tooltip, Typography } from 'antd';
import { useModel } from '@/runtime';
import type { ReactNode } from 'react';
import type { SensitiveFieldCode } from '@/constants/status';

export default function SensitiveField({ field, value }: { field: SensitiveFieldCode | string; value: ReactNode }) {
  const { initialState } = useModel('@@initialState');
  const permissions = initialState?.currentUser?.permissions || [];
  const visible = permissions.includes(`field:${field}:view`);

  if (visible) {
    return <>{value}</>;
  }

  return (
    <Tooltip title="无权限查看，请联系管理员">
      <Typography.Text type="secondary">
        <LockOutlined /> ***
      </Typography.Text>
    </Tooltip>
  );
}
