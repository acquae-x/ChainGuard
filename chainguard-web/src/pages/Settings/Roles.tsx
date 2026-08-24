import { PageContainer, ProTable } from '@/components/pro';
import { Alert, Button, Drawer, Form, Input, Select, Tag, Tree, message } from 'antd';
import { LockOutlined, PlusOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { getRoles, saveRole } from '@/services/settings';

const permissionTree = [
  { title: '风险与事件', key: 'risk', children: [{ title: '查看风险', key: 'risk:view' }, { title: '创建事件', key: 'risk:event:create' }] },
  { title: '决策与审批', key: 'decision', children: [{ title: '查看方案', key: 'decision:view' }, { title: '修改方案', key: 'decision:modify' }, { title: '高风险审批', key: 'approval:high' }] },
  { title: '数据与字段', key: 'data', children: [{ title: '管理主数据', key: 'data:manage' }, { title: '导入', key: 'data:import' }, { title: '查看成本', key: 'field:cost:view' }] },
  { title: '系统', key: 'settings', children: [{ title: '用户管理', key: 'user:manage' }, { title: '审计查看', key: 'audit:view' }] }
];

export default function Roles() {
  const [roles, setRoles] = useState<API.Role[]>([]);
  const [editing, setEditing] = useState<API.Role>();
  const load = async () => { const data = await getRoles(); setRoles(data); return { data, total: data.length, success: true }; };
  return (
    <PageContainer title="角色权限" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing({ id: '', tenantId: 'tenant-demo', code: 'buyer', name: '', builtin: false, permissions: [] })}>新建自定义角色</Button>}>
      <Alert type="info" showIcon message="内置 9 角色保持权限基线，可复制后创建企业自定义角色。" style={{ marginBottom: 16 }} />
      <ProTable<API.Role> rowKey="id" search={false} request={load} columns={[
        { title: '角色', dataIndex: 'name' }, { title: '角色代码', dataIndex: 'code', render: (_, row) => <Tag>{row.code}</Tag> },
        { title: '类型', dataIndex: 'builtin', render: (_, row) => row.builtin ? <Tag icon={<LockOutlined />}>内置</Tag> : <Tag color="blue">自定义</Tag> },
        { title: '权限数', render: (_, row) => row.permissions.length },
        { title: '操作', valueType: 'option', render: (_, row) => [<Button key="view" type="link" onClick={() => setEditing(row)}>{row.builtin ? '查看' : '编辑'}</Button>, <Button key="copy" type="link" onClick={() => setEditing({ ...row, id: '', name: `${row.name}副本`, builtin: false })}>复制</Button>] }
      ]} />
      <Drawer width={520} title={editing?.builtin ? '查看内置角色' : editing?.id ? '编辑角色' : '新建角色'} open={!!editing} onClose={() => setEditing(undefined)}>
        {editing && <Form layout="vertical" initialValues={editing} onFinish={async (values) => { await saveRole(values); message.success('角色权限已保存并记录审计'); setEditing(undefined); }}>
          <Form.Item name="name" label="角色名称" rules={[{ required: true }]}><Input disabled={editing.builtin} /></Form.Item>
          <Form.Item name="dataScope" label="默认数据范围" initialValue="custom"><Select disabled={editing.builtin} options={[{ label: '全企业', value: 'all' }, { label: '本部门', value: 'dept' }, { label: '自定义', value: 'custom' }]} /></Form.Item>
          <Form.Item name="permissions" label="能力权限"><Tree checkable defaultExpandAll disabled={editing.builtin} defaultCheckedKeys={editing.permissions} treeData={permissionTree} /></Form.Item>
          {!editing.builtin && <Button block type="primary" htmlType="submit">保存角色</Button>}
        </Form>}
      </Drawer>
    </PageContainer>
  );
}
