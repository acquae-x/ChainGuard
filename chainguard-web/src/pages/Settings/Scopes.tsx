import { PageContainer, ProTable } from '@/components/pro';
import { Alert, Button, Select, Space, Tag, message } from 'antd';
import { useEffect, useState } from 'react';
import { getDataScopes, saveDataScopes, type DataScopeView } from '@/services/settings';

const SCOPE_OPTIONS = [
  { label: '全企业', value: 'all' },
  { label: '本部门', value: 'dept' },
  { label: '本人负责', value: 'own' },
  { label: '自定义', value: 'custom' },
];

// 配置持久化到 /settings/data-scopes，行级过滤由后端 data_scope.py 执行。
// 警告条仍保留：只要后端 enforced=false 就必须显示，绝不写死成"已生效"——
// 这样万一未来过滤被关掉，界面会自己说实话，而不是继续骗人。
export default function Scopes() {
  const [view, setView] = useState<DataScopeView | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    getDataScopes()
      .then((data) => {
        setView(data);
        setDraft(Object.fromEntries(data.roles.map((row) => [row.code, row.scope])));
      })
      .catch((error) => message.error(error?.message || '读取数据范围失败'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const dirty = !!view && view.roles.some((row) => draft[row.code] !== row.scope);

  const onSave = async () => {
    setSaving(true);
    try {
      const saved = await saveDataScopes(draft);
      setView(saved);
      setDraft(Object.fromEntries(saved.roles.map((row) => [row.code, row.scope])));
      message.success(`数据范围已保存（版本 v${saved.version}）`);
    } catch (error: any) {
      message.error(error?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageContainer
      title="数据权限"
      subTitle="能力权限决定能做什么，数据范围决定能看哪些记录"
      extra={
        <Space>
          {view?.configured && <Tag color="blue">v{view.version}</Tag>}
          <Button onClick={load} disabled={saving}>
            重新载入
          </Button>
          <Button type="primary" onClick={onSave} loading={saving} disabled={!dirty}>
            保存
          </Button>
        </Space>
      }
    >
      {view && !view.enforced && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="数据范围配置尚未在查询层生效"
          description="当前配置会被保存并用于后续行级隔离，但后端查询暂未按该范围过滤记录。请勿据此认为数据已被隔离。"
        />
      )}
      {view?.enforced && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="数据范围已在查询层生效"
          description="「本部门」含其所有子部门；本人负责的记录始终可见；尚无负责人与部门的记录（如系统自动重算出的风险）对全员可见，直到被认领。"
        />
      )}
      <ProTable
        search={false}
        options={false}
        pagination={false}
        loading={loading}
        rowKey="code"
        dataSource={view?.roles ?? []}
        columns={[
          { title: '角色', dataIndex: 'name' },
          { title: '代码', dataIndex: 'code', render: (_, row) => <Tag>{row.code}</Tag> },
          { title: '用户数', dataIndex: 'userCount' },
          {
            title: '数据范围',
            dataIndex: 'scope',
            render: (_, row) => (
              <Select
                value={draft[row.code]}
                style={{ width: 160 }}
                options={SCOPE_OPTIONS}
                onChange={(value) => setDraft((prev) => ({ ...prev, [row.code]: value }))}
              />
            ),
          },
          { title: '字段权限', render: () => '按角色字段白名单控制' },
        ]}
      />
    </PageContainer>
  );
}
