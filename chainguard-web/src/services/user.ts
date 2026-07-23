// 认证服务（对应 Phase 2 §2.3，规格见 .workspace/tasks/TASK-203）。
// api 模式对接真实 /auth/*；mock 模式保留原演示逻辑。签名保持不变，页面层零改动。
import { tenant, users } from './mockData';
import { isApiMode, DATA_MODE } from './dataMode';
import { apiGet, apiPost, clearToken, getToken, setToken } from '../utils/request';

const DEMO_PASSWORD = 'Demo@1234';

type LoginParams = {
  account: string;
  password?: string;
  code?: string;
};

// ---- mock（演示）会话：token = demo-token-<role> ----
function createMockSession(user: API.User, currentTenant = tenant): API.LoginResult {
  const token = `demo-token-${user.roleCode}`;
  setToken(token);
  return { token, currentUser: user, tenant: currentTenant };
}

function resolveMockUser(account?: string) {
  const key = account?.trim().toLowerCase();
  return users.find((item) => item.phone === key || item.email?.toLowerCase() === key);
}

// ---- 登录：api 模式走真实后端，mock 模式走演示账号 ----
export async function login(params: LoginParams): Promise<API.LoginResult> {
  // 短信验证码登录后端未提供，统一走演示逻辑（sms 端点为 P3 预留）
  const smsLogin = params.code !== undefined;

  if (isApiMode() && !smsLogin) {
    const res = await apiPost<{ token: string; currentUser: API.User; tenant: API.Tenant }>(
      '/auth/login',
      { account: params.account, password: params.password },
      { skipAuth: true },
    );
    setToken(res.token);
    return { token: res.token, currentUser: res.currentUser, tenant: res.tenant };
  }

  // mock / 短信：演示账号校验
  const user = resolveMockUser(params.account);
  if (!user) throw new Error('账号不存在');
  if (smsLogin) {
    if (params.code !== '123456') throw new Error('验证码错误');
  } else if (params.password !== DEMO_PASSWORD) {
    throw new Error('密码错误');
  }
  return createMockSession(user);
}

// ---- 当前登录态：api 模式调 /auth/me，mock 模式解析 demo token ----
export async function currentUser(): Promise<API.LoginResult | undefined> {
  const token = getToken();
  if (!token) return undefined;

  if (isApiMode() && !token.startsWith('demo-token-')) {
    try {
      const res = await apiGet<{ currentUser: API.User; tenant: API.Tenant }>('/auth/me', undefined, { silent: true });
      return { token, currentUser: res.currentUser, tenant: res.tenant };
    } catch {
      return undefined;
    }
  }

  const roleCode = token.startsWith('demo-token-')
    ? (token.slice('demo-token-'.length) as API.RoleCode)
    : undefined;
  const user = users.find((item) => item.roleCode === roleCode);
  return user ? { token, currentUser: user, tenant } : undefined;
}

// ---- 演示角色一键切换（仅演示租户，不走后端）----
export async function switchDemoRole(roleCode: API.RoleCode): Promise<API.LoginResult> {
  if (!tenant.demoDataFlag) throw new Error('仅演示模式可切换角色');
  const user = users.find((item) => item.roleCode === roleCode);
  if (!user) throw new Error('演示角色不存在');
  return createMockSession(user);
}

export async function logout() {
  if (isApiMode()) {
    try {
      await apiPost('/auth/logout', undefined, { silent: true });
    } catch {
      // 忽略登出接口错误，前端仍清 token
    }
  }
  clearToken();
}

export async function changePassword(values: { oldPassword: string; newPassword: string }) {
  return apiPost('/auth/change-password', values);
}

// ---- 以下为演示/向导用途，后端 Phase 1 未提供对应端点，保留 mock（见 ADR §4 缺口-C）----
export async function sendSmsCode(phone: string) {
  return { phone, code: '123456' };
}

export async function verifySmsCode(phone: string, code: string) {
  return { phone, ok: code === '123456' };
}

export async function registerTenant(values: any): Promise<API.LoginResult> {
  if (isApiMode()) {
    const res = await apiPost<{ token: string; currentUser: API.User; tenant: API.Tenant }>('/auth/register', values, { skipAuth: true });
    setToken(res.token);
    return { token: res.token, currentUser: res.currentUser, tenant: res.tenant };
  }
  return createMockSession(users[0], { ...tenant, name: values.companyName || tenant.name, status: 'initializing' });
}

// 邀请码加入与 SSO 已在 5B「账户完善」落到真实后端，见 services/account.ts；
// 这里不再保留会造成"假成功"的 mock 实现。

export { DATA_MODE };
