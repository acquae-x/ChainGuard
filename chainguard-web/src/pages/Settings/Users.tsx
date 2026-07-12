import { history } from '@umijs/max';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import { Button, Drawer, Form, Input, Select, Space, Tag, message } from 'antd';
import { CopyOutlined, PlusOutlined, UserAddOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { ROLE_LABELS } from '@/constants/status';
import { createUser, getDepartments, getUsers } from '@/services/settings';

export default function Users() {
  const [open, setOpen] = useState(false);
  const [departments, setDepartments] = useState<API.Department[]>([]);
  const show = async () => { setDepartments(await getDepartments()); setOpen(true); };
  return (
    <PageContainer title="用户管理" extra={<Space><Button icon={<CopyOutlined />} onClick={() => { message.success('邀请链接已生成，进入成员加入页'); history.push('/user/join?code=CGDEMO01'); }}>生成邀请链接</Button><Button type="primary" icon={<UserAddOutlined />} onClick={show}>添加用户</Button></Space>}>
      <ProTable<API.User>
        rowKey="id"
        request={getUsers}
        columns={[
          { title: '姓名', dataIndex: 'name' }, { title: '手机号', dataIndex: 'phone' }, { title: '邮箱', dataIndex: 'email' },
          { title: '角色', dataIndex: 'roleCode', valueType: 'select', valueEnum: Object.fromEntries(Object.entries(ROLE_LABELS).map(([key, text]) => [key, { text }])), render: (_, row) => <Tag color="blue">{ROLE_LABELS[row.roleCode]}</Tag> },
          { title: '数据范围', dataIndex: 'dataScope', valueEnum: { all: { text: '全企业' }, dept: { text: '本部门' }, custom: { text: '自定义' } } },
          { title: '状态', dataIndex: 'status', render: (_, row) => <Tag color={row.status === 'active' ? 'green' : 'default'}>{row.status === 'active' ? '启用' : '未启用'}</Tag> },
          { title: '操作', valueType: 'option', render: () => [<Button key="edit" type="link">编辑</Button>, <Button key="disable" type="link" danger>停用</Button>] }
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
