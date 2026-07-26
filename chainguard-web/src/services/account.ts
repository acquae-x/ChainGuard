// 账户生命周期服务：找回密码、企业邀请码、OIDC SSO、账号锁定。
// 全部只走真实后端 /api/v1，没有 mock 分支——这些流程要么真的可用，要么明确告知不可用。
import { apiGet, apiPost, apiPut, setToken } from '../utils/request';

// ---- 找回密码 ----
export type PasswordResetOutcome = {
  // self_service：重置链接已投递；manual_admin：通道不可用，走管理员兜底
  mode: 'self_service' | 'manual_admin';
  channelConfigured: boolean;
  channel: string;
  deliveryFailed?: boolean;
  message: string;
};

export async function requestPasswordReset(account: string) {
  return apiPost<PasswordResetOutcome>('/auth/password-reset/request', { account }, { skipAuth: true, silent: true });
}

export async function confirmPasswordReset(token: string, newPassword: string) {
  return apiPost<{ ok: boolean; reloginRequired: boolean }>(
    '/auth/password-reset/confirm', { token, newPassword }, { skipAuth: true },
  );
}

export type PasswordResetRequestRow = {
  id: string; userId: string; userName: string; account: string;
  mode: string; channel: string; status: string; expiresAt: string; createdAt: string;
};

export async function getPasswordResetRequests() {
  const res = await apiGet<{ data: PasswordResetRequestRow[] }>('/settings/password-resets');
  return res.data || [];
}

// ---- 企业邀请码 ----
export type Invitation = {
  id: string;
  // 列表只回掩码；明文仅在生成的那一次返回
  codeMasked: string;
  roleCode: string; deptId: string; dataScope: string; note: string;
  status: 'active' | 'revoked' | 'expired' | 'exhausted';
  maxUses: number; usedCount: number; expiresAt: string; createdAt: string;
  redemptions: { userId: string; userName: string; roleCode: string; createdAt: string }[];
};

export async function getInvitations() {
  const res = await apiGet<{ data: Invitation[] }>('/settings/invitations');
  return res.data || [];
}

export async function createInvitation(values: {
  roleCode: string; maxUses?: number; validHours?: number; deptId?: string; dataScope?: string; note?: string;
}) {
  return apiPost<{ invitation: Invitation; code: string }>('/settings/invitations', values);
}

export async function revokeInvitation(id: string) {
  return apiPost<Invitation>(`/settings/invitations/${id}/revoke`);
}

export async function joinByInvitation(values: {
  code: string; name: string; password: string; phone?: string; email?: string;
}): Promise<API.LoginResult> {
  const res = await apiPost<{ token: string; currentUser: API.User; tenant: API.Tenant }>(
    '/auth/join', values, { skipAuth: true },
  );
  setToken(res.token);
  return { token: res.token, currentUser: res.currentUser, tenant: res.tenant };
}

// ---- 账号锁定 ----
export async function unlockUser(userId: string) {
  return apiPost<{ ok: boolean; locked: boolean; failedLoginCount: number }>(`/settings/users/${userId}/unlock`);
}

// ---- OIDC SSO ----
export type SsoDiscovery = { enabled: boolean; tenantId?: string; tenantName?: string; issuer?: string; message?: string };

export async function discoverSso(account?: string) {
  return apiGet<SsoDiscovery>('/auth/sso/discover', account ? { account } : undefined, { skipAuth: true, silent: true });
}

export async function startSsoLogin(params: { tenantId?: string; account?: string }) {
  return apiPost<{ authorizeUrl: string; state: string; tenantId: string }>('/auth/sso/authorize', params, { skipAuth: true, silent: true });
}

export async function completeSsoLogin(state: string, code: string): Promise<API.LoginResult> {
  const res = await apiPost<{ token: string; currentUser: API.User; tenant: API.Tenant }>(
    '/auth/sso/callback', { state, code }, { skipAuth: true, silent: true },
  );
  setToken(res.token);
  return { token: res.token, currentUser: res.currentUser, tenant: res.tenant };
}

export type SsoConfig = {
  configured: boolean; enabled: boolean;
  // 客户端密钥只以布尔位存在，接口永不回显密文或明文
  clientSecretSet: boolean;
  issuer: string; clientId: string; authorizationEndpoint: string; tokenEndpoint: string;
  redirectUri: string; scopes: string; emailClaim: string; subjectClaim: string;
  allowedDomains: string[]; autoProvision: boolean; defaultRoleCode: string; updatedAt: string | null;
};

export async function getSsoConfig() {
  return apiGet<SsoConfig>('/settings/sso');
}

export async function saveSsoConfig(values: Partial<SsoConfig> & { clientSecret?: string }) {
  return apiPut<SsoConfig>('/settings/sso', values);
}
