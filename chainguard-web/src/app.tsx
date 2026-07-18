import { history } from '@umijs/max';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { App } from 'antd';
import theme from './theme';
import { currentUser } from './services/user';
import { DegradeBanner } from './components';
import HeaderActions from './components/HeaderActions';

export async function getInitialState(): Promise<{ currentUser?: API.User; tenant?: API.Tenant; token?: string }> {
  const result = await currentUser();
  return result || {};
}

export const layout: RunTimeLayoutConfig = ({ initialState }) => {
  const user = initialState?.currentUser;
  const tenant = initialState?.tenant;
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
      if (user?.mustChangePassword && history.location.pathname !== '/user/profile') history.push('/user/profile');
    },
    // P1-3：顶栏操作区整体交给响应式 HeaderActions，窄屏收纳到「更多」，禁止横向溢出。
    actionsRender: () => [<HeaderActions key="actions" user={user} tenant={tenant} />],
    // P1-14：全局挂载 antd App，提供 message/Modal/notification 上下文，页面改用 App.useApp() 后不再触发静态方法警告。
    childrenRender: (children) => (
      <App component={false}>
        <DegradeBanner />
        {children}
      </App>
    ),
  };
};

export const antd = { theme };
