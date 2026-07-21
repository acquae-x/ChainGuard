const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/user',
    layout: false,
    routes: [
      { path: '/user/login', component: '@/pages/User/Login' },
      { path: '/user/register', component: '@/pages/User/Register' },
      { path: '/user/join', component: '@/pages/User/Join' },
      { path: '/user/reset', component: '@/pages/User/Reset' },
      { path: '/user/sso-callback', component: '@/pages/User/SsoCallback' },
      { path: '/user/profile', component: '@/pages/User/Profile' }
    ]
  },
  { path: '/onboarding', component: '@/pages/Onboarding' },
  { path: '/dashboard', name: '工作台', icon: 'DashboardOutlined', component: '@/pages/Dashboard' },
  {
    path: '/risk',
    name: '风险监控',
    icon: 'AlertOutlined',
    access: 'canRisk',
    routes: [
      { path: '/risk', redirect: '/risk/overview' },
      { path: '/risk/overview', name: '风险总览', component: '@/pages/Risk/Overview' },
      { path: '/risk/list', name: '风险列表', component: '@/pages/Risk/List' },
      { path: '/risk/rules', name: '监控规则', component: '@/pages/Risk/Rules' }
    ]
  },
  {
    path: '/incident',
    name: '应急事件',
    icon: 'FireOutlined',
    access: 'canIncident',
    routes: [
      { path: '/incident', redirect: '/incident/list' },
      { path: '/incident/list', name: '事件列表', component: '@/pages/Incident/List' },
      { path: '/incident/mine', name: '我发起的', component: '@/pages/Incident/Mine' },
      { path: '/incident/:id', hideInMenu: true, component: '@/pages/Incident/Detail' }
    ]
  },
  {
    path: '/decision',
    name: '决策方案',
    icon: 'BranchesOutlined',
    access: 'canDecision',
    routes: [
      { path: '/decision', redirect: '/decision/list' },
      { path: '/decision/generate/:incidentId', name: '方案生成', hideInMenu: true, component: '@/pages/Decision/Generate' },
      { path: '/decision/list', name: '方案列表', component: '@/pages/Decision/List' },
        { path: '/decision/approval/:id', hideInMenu: true, component: '@/pages/Decision/Approval' },
        { path: '/decision/approval', name: '审批中心', component: '@/pages/Decision/Approval' }
    ]
  },
  {
    path: '/task',
    name: '任务执行',
    icon: 'CarryOutOutlined',
    access: 'canTask',
    routes: [
      { path: '/task', redirect: '/task/mine' },
      { path: '/task/mine', name: '我的任务', component: '@/pages/Task/Mine' },
      { path: '/task/all', name: '全部任务', component: '@/pages/Task/All' },
      { path: '/task/overdue', name: '超时看板', component: '@/pages/Task/Overdue' }
    ]
  },
  {
    path: '/data',
    name: '数据管理',
    icon: 'DatabaseOutlined',
    access: 'canData',
    routes: [
      { path: '/data', redirect: '/data/material' },
      { path: '/data/material', name: '物料', access: 'canDataMaterial', component: '@/pages/Data/Material' },
      { path: '/data/supplier', name: '供应商', access: 'canDataSupplier', component: '@/pages/Data/Supplier' },
      { path: '/data/customer', name: '客户', access: 'canDataCustomer', component: '@/pages/Data/Customer' },
      { path: '/data/order', name: '订单', access: 'canDataOrder', component: '@/pages/Data/Order' },
      { path: '/data/inventory', name: '库存', access: 'canDataInventory', component: '@/pages/Data/Inventory' },
      { path: '/data/logistics', name: '物流', access: 'canDataLogistics', component: '@/pages/Data/Logistics' },
      { path: '/data/import', name: '数据导入', component: '@/pages/Data/Import' }
    ]
  },
  {
    path: '/case',
    name: '历史案例',
    icon: 'BookOutlined',
    access: 'canCase',
    routes: [
      { path: '/case', redirect: '/case/list' },
      { path: '/case/list', name: '案例库', component: '@/pages/Case/List' },
      { path: '/case/experience', name: '经验卡片', component: '@/pages/Case/Experience' }
    ]
  },
  {
    path: '/report',
    name: '报表看板',
    icon: 'BarChartOutlined',
    access: 'canReport',
    routes: [
      { path: '/report', component: '@/pages/Report/index' },
      { path: '/report/executive', name: '经营看板', access: 'canReportExecutive', component: '@/pages/Report/Executive' },
      { path: '/report/operation', name: '运营看板', access: 'canReportOperation', component: '@/pages/Report/Operation' },
      { path: '/report/response', name: '应急效果', access: 'canReportResponse', component: '@/pages/Report/Response' }
    ]
  },
  {
    path: '/settings',
    name: '系统设置',
    icon: 'SettingOutlined',
    access: 'canSettings',
    routes: [
      { path: '/settings', redirect: '/settings/tenant' },
      { path: '/settings/tenant', name: '企业信息', access: 'canSettingsAdmin', component: '@/pages/Settings/Tenant' },
      { path: '/settings/users', name: '用户管理', access: 'canSettingsAdmin', component: '@/pages/Settings/Users' },
      { path: '/settings/roles', name: '角色权限', access: 'canSettingsAdmin', component: '@/pages/Settings/Roles' },
      { path: '/settings/scopes', name: '数据权限', access: 'canSettingsAdmin', component: '@/pages/Settings/Scopes' },
      { path: '/settings/approval', name: '审批流', access: 'canApprovalConfig', component: '@/pages/Settings/Approval' },
      { path: '/settings/thresholds', name: '风险阈值', access: 'canApprovalConfig', component: '@/pages/Settings/Thresholds' },
      { path: '/settings/fields', name: '自定义字段', access: 'canSettingsAdmin', component: '@/pages/Settings/Fields' },
      { path: '/settings/audit', name: '审计日志', access: 'canAudit', component: '@/pages/Settings/Audit' },
      { path: '/settings/onboarding', name: '初始化向导重入', access: 'canSettingsAdmin', component: '@/pages/Onboarding' },
      { path: '/settings/integration', name: '集成', access: 'canSettingsAdmin', component: '@/pages/Settings/Integration' }
    ]
  },
  { path: '/403', component: '@/pages/Result/403' },
  { path: '/500', component: '@/pages/Result/500' },
  { path: '*', component: '@/pages/Result/404' }
];

export default routes;
