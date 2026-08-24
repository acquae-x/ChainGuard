import { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import {
  AlertOutlined, BarChartOutlined, BookOutlined, BranchesOutlined, CarryOutOutlined,
  DashboardOutlined, DatabaseOutlined, FireOutlined, SettingOutlined,
} from '@ant-design/icons';
import { App as AntApp, ConfigProvider, Layout, Menu, Spin, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { MenuProps } from 'antd';
import { RuntimeProvider, history, useAccess, useModel } from './runtime';
import type { InitialState } from './runtime';
import { currentUser } from './services/user';
import theme from './theme';
import HeaderActions from './components/HeaderActions';
import { DegradeBanner } from './components';
import './styles.css';

import Login from './pages/User/Login';
import Register from './pages/User/Register';
import Join from './pages/User/Join';
import Reset from './pages/User/Reset';
import SsoCallback from './pages/User/SsoCallback';
import Profile from './pages/User/Profile';
import Onboarding from './pages/Onboarding';
import Dashboard from './pages/Dashboard';
import RiskOverview from './pages/Risk/Overview';
import RiskList from './pages/Risk/List';
import RiskRules from './pages/Risk/Rules';
import IncidentList from './pages/Incident/List';
import IncidentMine from './pages/Incident/Mine';
import IncidentDetail from './pages/Incident/Detail';
import DecisionGenerate from './pages/Decision/Generate';
import DecisionList from './pages/Decision/List';
import DecisionApproval from './pages/Decision/Approval';
import TaskMine from './pages/Task/Mine';
import TaskAll from './pages/Task/All';
import TaskOverdue from './pages/Task/Overdue';
import DataMaterial from './pages/Data/Material';
import DataSupplier from './pages/Data/Supplier';
import DataCustomer from './pages/Data/Customer';
import DataOrder from './pages/Data/Order';
import DataInventory from './pages/Data/Inventory';
import DataImport from './pages/Data/Import';
import CaseList from './pages/Case/List';
import CaseExperience from './pages/Case/Experience';
import ReportIndex from './pages/Report';
import ReportExecutive from './pages/Report/Executive';
import ReportOperation from './pages/Report/Operation';
import ReportResponse from './pages/Report/Response';
import SettingsTenant from './pages/Settings/Tenant';
import SettingsUsers from './pages/Settings/Users';
import SettingsRoles from './pages/Settings/Roles';
import SettingsScopes from './pages/Settings/Scopes';
import SettingsApproval from './pages/Settings/Approval';
import SettingsThresholds from './pages/Settings/Thresholds';
import SettingsFields from './pages/Settings/Fields';
import SettingsAudit from './pages/Settings/Audit';
import SettingsIntegration from './pages/Settings/Integration';
import Forbidden from './pages/Result/403';
import ServerError from './pages/Result/500';
import NotFound from './pages/Result/404';

type AccessKey = keyof ReturnType<typeof useAccess>;

function RequireAccess({ name, children }: { name: AccessKey; children: React.ReactNode }) {
  const access = useAccess();
  return access[name] ? <>{children}</> : <Navigate to="/403" replace />;
}

function SessionGuard() {
  const { initialState } = useModel('@@initialState');
  const location = useLocation();
  if (!initialState?.currentUser) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/user/login?redirect=${redirect}`} replace />;
  }
  if (initialState.currentUser.mustChangePassword && location.pathname !== '/user/profile') {
    return <Navigate to="/user/profile" replace />;
  }
  return <Outlet />;
}

function AppShell() {
  const { initialState } = useModel('@@initialState');
  const access = useAccess();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const items = useMemo<MenuProps['items']>(() => [
    access.canDashboard && { key: '/dashboard', icon: <DashboardOutlined />, label: '工作台' },
    access.canRisk && { key: 'risk', icon: <AlertOutlined />, label: '风险监控', children: [
      { key: '/risk/overview', label: '风险总览' }, { key: '/risk/list', label: '风险列表' }, { key: '/risk/rules', label: '监控规则' },
    ] },
    access.canIncident && { key: 'incident', icon: <FireOutlined />, label: '应急事件', children: [
      { key: '/incident/list', label: '事件列表' }, { key: '/incident/mine', label: '我发起的' },
    ] },
    access.canDecision && { key: 'decision', icon: <BranchesOutlined />, label: '决策方案', children: [
      { key: '/decision/list', label: '方案列表' }, ...(access.canApproval ? [{ key: '/decision/approval', label: '审批中心' }] : []),
    ] },
    access.canTask && { key: 'task', icon: <CarryOutOutlined />, label: '任务执行', children: [
      { key: '/task/mine', label: '我的任务' }, { key: '/task/all', label: '全部任务' }, { key: '/task/overdue', label: '超时看板' },
    ] },
    access.canData && { key: 'data', icon: <DatabaseOutlined />, label: '数据管理', children: [
      access.canDataMaterial && { key: '/data/material', label: '物料' },
      access.canDataSupplier && { key: '/data/supplier', label: '供应商' },
      access.canDataCustomer && { key: '/data/customer', label: '客户' },
      access.canDataOrder && { key: '/data/order', label: '订单' },
      access.canDataInventory && { key: '/data/inventory', label: '库存' },
      access.canImport && { key: '/data/import', label: '数据导入' },
    ].filter(Boolean) },
    access.canCase && { key: 'case', icon: <BookOutlined />, label: '历史案例', children: [
      { key: '/case/list', label: '案例库' }, { key: '/case/experience', label: '经验卡片' },
    ] },
    access.canReport && { key: 'report', icon: <BarChartOutlined />, label: '报表看板', children: [
      access.canReportExecutive && { key: '/report/executive', label: '经营看板' },
      access.canReportOperation && { key: '/report/operation', label: '运营看板' },
      access.canReportResponse && { key: '/report/response', label: '应急效果' },
    ].filter(Boolean) },
    access.canSettings && { key: 'settings', icon: <SettingOutlined />, label: '系统设置', children: [
      access.canSettingsAdmin && { key: '/settings/tenant', label: '企业信息' },
      access.canSettingsAdmin && { key: '/settings/users', label: '用户管理' },
      access.canSettingsAdmin && { key: '/settings/roles', label: '角色权限' },
      access.canSettingsAdmin && { key: '/settings/scopes', label: '数据权限' },
      access.canApprovalConfig && { key: '/settings/approval', label: '审批流' },
      access.canApprovalConfig && { key: '/settings/thresholds', label: '风险阈值' },
      access.canSettingsAdmin && { key: '/settings/fields', label: '自定义字段' },
      access.canAudit && { key: '/settings/audit', label: '审计日志' },
      access.canSettingsAdmin && { key: '/settings/onboarding', label: '初始化向导重入' },
      access.canSettingsAdmin && { key: '/settings/integration', label: '集成' },
    ].filter(Boolean) },
  ].filter(Boolean) as MenuProps['items'], [access]);

  const section = location.pathname.split('/')[1];
  return <Layout className="app-layout">
    <Layout.Sider
      theme="light"
      collapsible
      collapsed={collapsed}
      onCollapse={setCollapsed}
      breakpoint="lg"
      width={232}
      className="app-sider"
    >
      <div className="app-brand">{collapsed ? 'CG' : 'ChainGuard'}</div>
      <Menu mode="inline" items={items} selectedKeys={[location.pathname]} defaultOpenKeys={[section]} onClick={({ key }) => history.push(key)} />
    </Layout.Sider>
    <Layout>
      <Layout.Header className="app-header">
        <Typography.Text strong className="app-header-title">供应链中断应急决策</Typography.Text>
        <HeaderActions user={initialState?.currentUser} tenant={initialState?.tenant} />
      </Layout.Header>
      <DegradeBanner />
      <Layout.Content className="app-content"><Outlet /></Layout.Content>
    </Layout>
  </Layout>;
}

function ApplicationRoutes() {
  return <Routes>
    <Route path="/user/login" element={<Login />} />
    <Route path="/user/register" element={<Register />} />
    <Route path="/user/join" element={<Join />} />
    <Route path="/user/reset" element={<Reset />} />
    <Route path="/user/sso-callback" element={<SsoCallback />} />
    <Route path="/user/profile" element={<Profile />} />
    <Route element={<SessionGuard />}>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/dashboard" element={<RequireAccess name="canDashboard"><Dashboard /></RequireAccess>} />
        <Route path="/risk" element={<Navigate to="/risk/overview" replace />} />
        <Route path="/risk/overview" element={<RequireAccess name="canRisk"><RiskOverview /></RequireAccess>} />
        <Route path="/risk/list" element={<RequireAccess name="canRisk"><RiskList /></RequireAccess>} />
        <Route path="/risk/rules" element={<RequireAccess name="canRisk"><RiskRules /></RequireAccess>} />
        <Route path="/incident" element={<Navigate to="/incident/list" replace />} />
        <Route path="/incident/list" element={<RequireAccess name="canIncident"><IncidentList /></RequireAccess>} />
        <Route path="/incident/mine" element={<RequireAccess name="canIncident"><IncidentMine /></RequireAccess>} />
        <Route path="/incident/:id" element={<RequireAccess name="canIncident"><IncidentDetail /></RequireAccess>} />
        <Route path="/decision" element={<Navigate to="/decision/list" replace />} />
        <Route path="/decision/list" element={<RequireAccess name="canDecision"><DecisionList /></RequireAccess>} />
        <Route path="/decision/generate/:incidentId" element={<RequireAccess name="canDecision"><DecisionGenerate /></RequireAccess>} />
        <Route path="/decision/approval" element={<RequireAccess name="canApproval"><DecisionApproval /></RequireAccess>} />
        <Route path="/decision/approval/:id" element={<RequireAccess name="canApproval"><DecisionApproval /></RequireAccess>} />
        <Route path="/task" element={<Navigate to="/task/mine" replace />} />
        <Route path="/task/mine" element={<RequireAccess name="canTask"><TaskMine /></RequireAccess>} />
        <Route path="/task/all" element={<RequireAccess name="canTask"><TaskAll /></RequireAccess>} />
        <Route path="/task/overdue" element={<RequireAccess name="canTask"><TaskOverdue /></RequireAccess>} />
        <Route path="/data" element={<Navigate to="/data/material" replace />} />
        <Route path="/data/material" element={<RequireAccess name="canDataMaterial"><DataMaterial /></RequireAccess>} />
        <Route path="/data/supplier" element={<RequireAccess name="canDataSupplier"><DataSupplier /></RequireAccess>} />
        <Route path="/data/customer" element={<RequireAccess name="canDataCustomer"><DataCustomer /></RequireAccess>} />
        <Route path="/data/order" element={<RequireAccess name="canDataOrder"><DataOrder /></RequireAccess>} />
        <Route path="/data/inventory" element={<RequireAccess name="canDataInventory"><DataInventory /></RequireAccess>} />
        <Route path="/data/import" element={<RequireAccess name="canImport"><DataImport /></RequireAccess>} />
        <Route path="/case" element={<Navigate to="/case/list" replace />} />
        <Route path="/case/list" element={<RequireAccess name="canCase"><CaseList /></RequireAccess>} />
        <Route path="/case/experience" element={<RequireAccess name="canCase"><CaseExperience /></RequireAccess>} />
        <Route path="/report" element={<ReportIndex />} />
        <Route path="/report/executive" element={<RequireAccess name="canReportExecutive"><ReportExecutive /></RequireAccess>} />
        <Route path="/report/operation" element={<RequireAccess name="canReportOperation"><ReportOperation /></RequireAccess>} />
        <Route path="/report/response" element={<RequireAccess name="canReportResponse"><ReportResponse /></RequireAccess>} />
        <Route path="/settings" element={<Navigate to="/settings/tenant" replace />} />
        <Route path="/settings/tenant" element={<RequireAccess name="canSettingsAdmin"><SettingsTenant /></RequireAccess>} />
        <Route path="/settings/users" element={<RequireAccess name="canSettingsAdmin"><SettingsUsers /></RequireAccess>} />
        <Route path="/settings/roles" element={<RequireAccess name="canSettingsAdmin"><SettingsRoles /></RequireAccess>} />
        <Route path="/settings/scopes" element={<RequireAccess name="canSettingsAdmin"><SettingsScopes /></RequireAccess>} />
        <Route path="/settings/approval" element={<RequireAccess name="canApprovalConfig"><SettingsApproval /></RequireAccess>} />
        <Route path="/settings/thresholds" element={<RequireAccess name="canApprovalConfig"><SettingsThresholds /></RequireAccess>} />
        <Route path="/settings/fields" element={<RequireAccess name="canSettingsAdmin"><SettingsFields /></RequireAccess>} />
        <Route path="/settings/audit" element={<RequireAccess name="canAudit"><SettingsAudit /></RequireAccess>} />
        <Route path="/settings/onboarding" element={<RequireAccess name="canSettingsAdmin"><Onboarding /></RequireAccess>} />
        <Route path="/settings/integration" element={<RequireAccess name="canSettingsAdmin"><SettingsIntegration /></RequireAccess>} />
        <Route path="/403" element={<Forbidden />} />
        <Route path="/500" element={<ServerError />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Route>
  </Routes>;
}

function Root() {
  const [initialState, setState] = useState<InitialState>();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    currentUser().then(setState).finally(() => setReady(true));
  }, []);
  const setInitialState = async (state?: InitialState) => { setState(state); };
  if (!ready) return <div className="app-loading"><Spin size="large"><span aria-label="正在加载 ChainGuard" /></Spin></div>;
  return <RuntimeProvider value={{ initialState, setInitialState }}><ApplicationRoutes /></RuntimeProvider>;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider theme={theme} locale={zhCN}>
      <AntApp>
        <BrowserRouter><Root /></BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
