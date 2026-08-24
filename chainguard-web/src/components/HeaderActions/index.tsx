import { history } from '@/runtime';
import { Button, Divider, Dropdown, Grid, Space, Tag, Typography } from 'antd';
import { EllipsisOutlined, LogoutOutlined, PlusOutlined, QuestionCircleOutlined, SwapOutlined, UserOutlined } from '@ant-design/icons';
import GlobalSearch from '../GlobalSearch';
import NotificationBell from '../NotificationBell';
import { logout, switchDemoRole } from '@/services/user';
import { roleNames } from '@/services/mockData';
import { isApiMode } from '@/services/dataMode';

// 375px 顶栏不得横向溢出。窄屏下只保留菜单折叠、通知、用户三个常驻入口，
// 搜索 / 上报异常 / 租户信息 / 演练 收进「更多」下拉，禁止页面横向滚动。
export default function HeaderActions({ user, tenant }: { user?: API.User; tenant?: API.Tenant }) {
  const screens = Grid.useBreakpoint();
  // 登录页和会话恢复完成前不渲染需要鉴权的顶栏动作，避免通知接口的 401
  // 在开发环境触发错误遮罩，也避免向未登录用户展示空的用户菜单。
  if (!user) return null;
  // The expanded action group is wider than the content column once the
  // desktop sider is present. Collapse it below Ant Design's xl breakpoint so
  // 1099px/tablet-width pages cannot widen the document.
  const compact = !screens.xl;
  const canCreateIncident = user?.permissions?.includes('risk:event:create');
  const showDemo = !isApiMode();

  const onUserMenu = async ({ key }: { key: string }) => {
    if (key === 'profile') history.push('/user/profile');
    if (key === 'logout') { await logout(); history.push('/user/login'); }
    if (key.startsWith('role:')) { await switchDemoRole(key.slice(5) as API.RoleCode); window.location.assign('/dashboard'); }
  };

  const userDropdown = (
    <Dropdown
      trigger={['click']}
      menu={{
        onClick: onUserMenu,
        items: [
          { key: 'profile', icon: <UserOutlined />, label: '个人设置' },
          showDemo && tenant?.demoDataFlag ? {
            key: 'switch-role', icon: <SwapOutlined />, label: '切换角色（仅演示模式）',
            children: (Object.entries(roleNames) as [API.RoleCode, string][]).map(([code, label]) => ({ key: `role:${code}`, label })),
          } : null,
          { type: 'divider' as const },
          { key: 'logout', icon: <LogoutOutlined />, label: '退出' },
        ],
      }}
    >
      <Button type="text" aria-label="用户菜单" icon={<UserOutlined />}>
        <span style={{ maxWidth: compact ? 0 : 120, overflow: 'hidden', textOverflow: 'ellipsis', display: 'inline-block', verticalAlign: 'middle' }}>
          {compact ? '' : (user?.name || '未登录')}
        </span>
      </Button>
    </Dropdown>
  );

  if (!compact) {
    return (
      <Space size={8} align="center" style={{ maxWidth: '100%' }}>
        <GlobalSearch />
        {canCreateIncident ? <Button type="primary" icon={<PlusOutlined />} onClick={() => history.push('/risk/list')}>上报异常</Button> : null}
        <NotificationBell />
        {showDemo ? <Button type="text" icon={<QuestionCircleOutlined />} onClick={() => history.push('/onboarding')}>演练</Button> : null}
        {tenant?.name ? <Tag color="blue">{tenant.name}</Tag> : null}
        {userDropdown}
      </Space>
    );
  }

  // 窄屏：更多入口收纳搜索/上报/租户/演练，保证通知与用户常驻可见。
  const more = (
    <Dropdown
      trigger={['click']}
      popupRender={() => (
        <div style={{ width: 260, maxWidth: '92vw', padding: 12, background: '#fff', boxShadow: '0 4px 16px rgba(0,0,0,0.12)', borderRadius: 8 }}>
          <GlobalSearch />
          <Divider style={{ margin: '10px 0' }} />
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {canCreateIncident ? <Button block type="primary" icon={<PlusOutlined />} onClick={() => history.push('/risk/list')}>上报异常</Button> : null}
            {showDemo ? <Button block icon={<QuestionCircleOutlined />} onClick={() => history.push('/onboarding')}>演练</Button> : null}
            {tenant?.name ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>当前企业：{tenant.name}</Typography.Text> : null}
          </Space>
        </div>
      )}
    >
      <Button type="text" aria-label="更多" icon={<EllipsisOutlined />} />
    </Dropdown>
  );

  return (
    <Space
      data-testid="compact-header-actions"
      size={4}
      align="center"
      style={{
        position: 'fixed',
        top: 8,
        right: 8,
        zIndex: 101,
        maxWidth: 'calc(100vw - 56px)',
      }}
    >
      {more}
      <NotificationBell />
      {userDropdown}
    </Space>
  );
}
