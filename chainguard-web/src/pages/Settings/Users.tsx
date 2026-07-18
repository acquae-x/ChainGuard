import { history } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { App, Button, Drawer, Form, Input, Popconfirm, Select, Space, Tag, Typography } from 'antd';
import { CopyOutlined, PlusOutlined, UserAddOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { ROLE_LABELS } from '@/constants/status';
import { createUser, getDepartments, getUsers, resetUserPassword } from '@/services/settings';

export default function Users() {
  // P1-14：用 App.useApp() 取代静态 message/Modal，消除 "Static function can not consume context" 警告。
  const { message, modal } = App.useApp();
  const [open, setOpen] = useState(false);
  const [departments, setDepartments] = useState<API.Department[]>([]);
  const show = async () => { setDepartments(await getDepartments()); setOpen(true); };

  // P1-11：重置密码必须先确认，成功后用 Modal 持久展示一次性临时密码（可复制）。
  const doReset = async (row: API.User) => {
    const result = await resetUserPassword(row.id);
    modal.success({
      title: `已重置 ${row.name} 的密码`,
      content: (
        <div>
          <Typography.Paragraph>一次性临时密码（仅显示一次，请安全转交，该用户首次登录须改密）：</Typography.Paragraph>
          <Typography.Paragraph copyable strong>{result.temporaryPassword}</Typography.Paragraph>
        </div>
      ),
    });
  };

  return (
    <PageContainer title="用户管理" extra={<Space wrap><Button icon={<CopyOutlined />} onClick={() => { message.success('邀请链接已生成，进入成员加入页'); history.push('/user/join?code=CGDEMO01'); }}>生成邀请链接</Button><Button type="primary" icon={<UserAddOutlined />} onClick={show}>添加用户</Button></Space>}>
      <ProTable<API.User>
        rowKey="id"
        request={getUsers}
        scroll={{ x: 980 }}
        columns={[
          { title: '姓名', dataIndex: 'name', width: 110, ellipsis: true },
          { title: '手机号', dataIndex: 'phone', width: 130 },
          { title: '邮箱', dataIndex: 'email', width: 220, ellipsis: true },
          { title: '角色', dataIndex: 'roleCode', width: 130, valueType: 'select', valueEnum: Object.fromEntries(Object.entries(ROLE_LABELS).map(([key, text]) => [key, { text }])), render: (_, row) => <Tag color="blue">{ROLE_LABELS[row.roleCode]}</Tag> },
          { title: '数据范围', dataIndex: 'dataScope', width: 110, valueEnum: { all: { text: '全企业' }, dept: { text: '本部门' }, custom: { text: '自定义' } } },
          { title: '状态', dataIndex: 'status', width: 90, render: (_, row) => <Tag color={row.status === 'active' ? 'green' : 'default'}>{row.status === 'active' ? '启用' : '未启用'}</Tag> },
          {
            title: '操作', valueType: 'option', width: 190, fixed: 'right',
            render: (_, row) => [
              <Button key="edit" type="link">编辑</Button>,
              <Popconfirm key="reset" title="确认重置该用户密码？" description="将生成一次性临时密码，并强制该用户首次登录修改密码。" okText="确认重置" cancelText="取消" onConfirm={() => doReset(row)}>
                <Button type="link">重置密码</Button>
              </Popconfirm>,
              <Button key="disable" type="link" danger>停用</Button>,
            ],
          },
        ]}
      />
      <Drawer title="添加用户" width={460} open={open} onClose={() => setOpen(false)}>
        <Form layout="vertical" onFinish={async (values) => { await createUser(values); message.success('用户已添加并发送邀请'); setOpen(false); }}>
          <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="phone" label="手机号" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="deptId" label="部门" rules={[{ required: true }]}><Select options={departments.map((item) => ({ label: item.name, value: item.id }))} /></Form.Item>
          <Form.Item name="roleCode" label="角色" rules={[{ required: true }]}><Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} /></Form.Item>
          <Button block type="primary" htmlType="submit" icon={<PlusOutlined />}>添加并邀请</Button>
        </Form>
      </Drawer>
    </PageContainer>
  );
}
