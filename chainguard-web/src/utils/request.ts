// ChainGuard 前端统一网络层（对应 Phase 2 §2.1，规格见 .workspace/tasks/TASK-201）。
// 基于 @umijs/max 自带 request（axios 内核），禁止 axios/redux。
import { request as umiRequest, history } from '@umijs/max';
import { message } from 'antd';
import { markBackendDown } from '../services/dataMode';

// 访问 token 存前端可读 cookie（HttpOnly 由后端 Set-Cookie 预留，refresh token 后端已走 HttpOnly cookie）。
const TOKEN_COOKIE = 'chainguard_token';
const BASE_URL = '/api/v1';
const TIMEOUT = 10000;
const IDEMPOTENT = new Set(['GET', 'HEAD']);
const MAX_RETRY = 2;

export function getToken(): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split('; ')
    .find((item) => item.startsWith(`${TOKEN_COOKIE}=`))
    ?.slice(TOKEN_COOKIE.length + 1);
  return raw ? decodeURIComponent(raw) : undefined;
}

export function setToken(token: string) {
  if (typeof document === 'undefined') return;
  document.cookie = `${TOKEN_COOKIE}=${encodeURIComponent(token)}; Max-Age=${7 * 24 * 3600}; Path=/; SameSite=Lax`;
}

export function clearToken() {
  if (typeof document === 'undefined') return;
  document.cookie = `${TOKEN_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax`;
}

export type ApiError = Error & { code?: string; traceId?: string; httpStatus?: number; isNetwork?: boolean };

type RequestOptions = {
  method?: string;
  data?: unknown;
  params?: Record<string, unknown>;
  headers?: Record<string, string>;
  skipAuth?: boolean;
  // 静默模式：不弹全局 message（用于探针 / 调用方自行处理）
  silent?: boolean;
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function normalizeError(err: any): ApiError {
  const response = err?.response;
  // 有响应但非 2xx → 读后端错误信封 {code,message,traceId}
  if (response) {
    const body = response.data || {};
    const error: ApiError = new Error(body.message || `请求失败（${response.status}）`);
    error.code = body.code;
    error.traceId = body.traceId;
    error.httpStatus = response.status;
    // 开发代理在后端不可达时会返回 502/503/504，而非浏览器层面的无响应错误。
    // 这同样属于后端不可用，应触发显式降级黄条。
    error.isNetwork = [502, 503, 504].includes(response.status);
    return error;
  }
  // 无响应 → 网络错误 / 超时
  const error: ApiError = new Error('服务暂不可用，请稍后重试');
  error.isNetwork = true;
  return error;
}

async function core<T>(url: string, options: RequestOptions, attempt = 0): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  const headers: Record<string, string> = { ...(options.headers || {}) };
  if (!options.skipAuth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  try {
    return await umiRequest<T>(`${BASE_URL}${url}`, {
      method,
      data: options.data,
      params: options.params,
      headers,
      timeout: TIMEOUT,
    });
  } catch (raw: any) {
    const error = normalizeError(raw);

    // 幂等 GET/HEAD 才重试（网络错误或 5xx），指数退避
    const retriable = IDEMPOTENT.has(method) && (error.isNetwork || (error.httpStatus ?? 0) >= 500);
    if (retriable && attempt < MAX_RETRY) {
      await sleep(300 * Math.pow(3, attempt));
      return core<T>(url, options, attempt + 1);
    }

    // 401：清 token 跳登录（不重复弹错）
    if (error.httpStatus === 401) {
      clearToken();
      if (typeof window !== 'undefined' && !history.location.pathname.startsWith('/user')) {
        history.push('/user/login');
      }
      throw error;
    }

    // 网络错误：标记后端不可用，触发降级黄条
    if (error.isNetwork) {
      markBackendDown(error.message);
      if (!options.silent) message.error(error.message);
      throw error;
    }

    if (!options.silent) message.error(error.message);
    throw error;
  }
}

export function apiGet<T = any>(url: string, params?: Record<string, unknown>, options: RequestOptions = {}) {
  return core<T>(url, { ...options, method: 'GET', params });
}
export function apiPost<T = any>(url: string, data?: unknown, options: RequestOptions = {}) {
  return core<T>(url, { ...options, method: 'POST', data });
}
export function apiPatch<T = any>(url: string, data?: unknown, options: RequestOptions = {}) {
  return core<T>(url, { ...options, method: 'PATCH', data });
}
export function apiDelete<T = any>(url: string, options: RequestOptions = {}) {
  return core<T>(url, { ...options, method: 'DELETE' });
}

export const apiRequest = core;
