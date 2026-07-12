import { history } from '@umijs/max';
import { Button, Dropdown, Tag, message } from 'antd';
import { LogoutOutlined, PlusOutlined, QuestionCircleOutlined, SwapOutlined, UserOutlined } from '@ant-design/icons';
import type { RunTimeLayoutConfig } from '@umijs/max';
import theme from './theme';
import { currentUser, logout, switchDemoRole } from './services/user';
import { roleNames } from './services/mockData';
import { DegradeBanner, GlobalSearch, NotificationBell } from './components';

export async function getInitialState(): Promise<{ currentUser?: API.User; tenant?: API.Tenant; token?: string }> {
  const result = await currentUser();
  return result || {};
}

export const layout: RunTimeLayoutConfig = ({ initialState }) => {
  const user = initialState?.currentUser;
  const tenant = initialState?.tenant;
  const canCreateIncident = user?.permissions.includes('risk:event:create');
  return {
    title: 'ChainGuard',
    logo: false,
    token: theme.token,
    menu: { locale: false },
    layout: 'mix',
    contentStyle: { minHeight: 'calc(100vh - 56px)' },
    onPageChange: () => {
      if (!user && !history.location.pathname.startsWith('/user')) {
        history.push('/user/login');
      }
    },
    actionsRender: () => [
      <GlobalSearch key="search" />,
      canCreateIncident ? <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => history.push('/risk/list')}>上报异常</Button> : null,
      <NotificationBell key="notice" />,
      <Button key="help" type="text" icon={<QuestionCircleOutlined />} onClick={() => history.push('/onboarding')}>演练</Button>,
      <Tag key="tenant" color="blue">{tenant?.name}</Tag>,
      <Dropdown key="user" trigger={['click']} menu={{
        items: [
          { key: 'profile', icon: <UserOutlined />, label: '个人设置' },
          tenant?.demoDataFlag ? {
            key: 'switch-role',
            icon: <SwapOutlined />,
            label: '切换角色（仅演示模式）',
            children: (Object.entries(roleNames) as [API.RoleCode, string][]).map(([code, label]) => ({ key: `role:${code}`, label }))
          } : null,
          { type: 'divider' },
          { key: 'logout', icon: <LogoutOutlined />, label: '退出' }
        ],
        onClick: async ({ key }) => {
          if (key === 'profile') message.info('个人设置即将开放');
          if (key === 'logout') {
            await logout();
            history.push('/user/login');
          }
          if (key.startsWith('role:')) {
            await switchDemoRole(key.slice(5) as API.RoleCode);
            window.location.assign('/dashboard');
          }
        }
      }}><Button type="text">{user?.name || '未登录'}</Button></Dropdown>
    ],
    // 降级提示黄条：演示数据模式 / 后端不可用（Phase 2 §2.2）
    childrenRender: (children) => (
      <>
        <DegradeBanner />
        {children}
      </>
    ),
  };
};

export const antd = { theme };
