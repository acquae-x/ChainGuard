// ChainGuard 前端统一网络层：原生 fetch + AbortController，无第三方 HTTP 客户端。
import { history } from '@/runtime';
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
  timeoutMs?: number;
  skipAuth?: boolean;
  // 静默模式：不弹全局 message（用于探针 / 调用方自行处理）
  silent?: boolean;
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function normalizeHttpError(status: number, body: any): ApiError {
    const error: ApiError = new Error(body?.message || `请求失败（${status}）`);
    error.code = body.code;
    error.traceId = body.traceId;
    error.httpStatus = status;
    // 开发代理在后端不可达时会返回 502/503/504，而非浏览器层面的无响应错误。
    // 这同样属于后端不可用，应触发显式降级黄条。
    //
    // 但 503 也被后端用于业务级拒绝（如 CG-2802 凭证加密未启用），那种响应带完整的
    // {code,message,traceId} 错误信封。把它也判成网络故障会告诉管理员"后端服务暂不
    // 可用、数据可能为离线演示数据"——后端其实是健康的，真正该做的是去配加密密钥。
    // 因此：带错误码的响应一律按业务错误处理，只有裸的 502/503/504 才算后端不可达。
    error.isNetwork = [502, 503, 504].includes(status) && !body?.code;
    return error;
}

function normalizeNetworkError(err: unknown): ApiError {
  const timedOut = err instanceof DOMException && err.name === 'AbortError';
  const error: ApiError = new Error(timedOut ? '请求超时，请稍后重试' : '服务暂不可用，请稍后重试');
  error.isNetwork = true;
  return error;
}

function buildUrl(url: string, params?: Record<string, unknown>) {
  const target = new URL(`${BASE_URL}${url}`, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) value.forEach((item) => target.searchParams.append(key, String(item)));
    else target.searchParams.set(key, String(value));
  });
  return `${target.pathname}${target.search}`;
}

async function core<T>(url: string, options: RequestOptions, attempt = 0): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  const headers: Record<string, string> = { ...(options.headers || {}) };
  if (!options.skipAuth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? TIMEOUT);
  try {
    const hasBody = options.data !== undefined && method !== 'GET' && method !== 'HEAD';
    const isForm = typeof FormData !== 'undefined' && options.data instanceof FormData;
    if (hasBody && !isForm && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetch(buildUrl(url, options.params), {
      method,
      headers,
      body: hasBody ? (isForm ? options.data as FormData : JSON.stringify(options.data)) : undefined,
      signal: controller.signal,
      credentials: 'same-origin',
    });
    const contentType = response.headers.get('content-type') || '';
    const body = response.status === 204
      ? undefined
      : contentType.includes('application/json')
        ? await response.json()
        : await response.text();
    if (!response.ok) throw normalizeHttpError(response.status, body || {});
    return body as T;
  } catch (raw: unknown) {
    const error = (raw as ApiError)?.httpStatus ? raw as ApiError : normalizeNetworkError(raw);

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
  } finally {
    window.clearTimeout(timeout);
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
export function apiPut<T = any>(url: string, data?: unknown, options: RequestOptions = {}) {
  return core<T>(url, { ...options, method: 'PUT', data });
}
export function apiDelete<T = any>(url: string, options: RequestOptions = {}) {
  return core<T>(url, { ...options, method: 'DELETE' });
}

export const apiRequest = core;
