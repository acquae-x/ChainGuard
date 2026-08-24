// 双数据源与降级开关（对应 Phase 2 §2.2）。
// 核心原则：workflowStore mock 完整保留；后端不可用时显式黄条提示，禁止静默降级。
import { create } from 'zustand';

// DATA_MODE 由 Vite define 注入（vite.config.ts）。默认 api。
export const DATA_MODE: 'api' | 'mock' = ((process.env.DATA_MODE as 'api' | 'mock') || 'api');

export function isApiMode() {
  return DATA_MODE === 'api';
}

type DegradeReason = 'demo' | 'backend-down';

type BackendState = {
  down: boolean;
  reason?: string;
  dismissed: boolean;
  markDown: (reason: string) => void;
  reset: () => void;
  dismiss: () => void;
};

// 全局后端可用性状态（zustand，禁止 redux / localStorage 存业务数据）。
export const useBackendState = create<BackendState>((set) => ({
  down: false,
  reason: undefined,
  dismissed: false,
  markDown: (reason: string) => set({ down: true, reason, dismissed: false }),
  reset: () => set({ down: false, reason: undefined, dismissed: false }),
  dismiss: () => set({ dismissed: true }),
}));

// 供 request.ts 在 React 之外调用
export function markBackendDown(reason: string) {
  useBackendState.getState().markDown(reason);
}
export function resetBackend() {
  useBackendState.getState().reset();
}

// 当前应展示的降级类型：mock 模式恒为演示；api 模式仅在探测到后端不可用时提示
export function currentDegrade(): { show: boolean; reason: DegradeReason; text: string } | null {
  if (DATA_MODE === 'mock') {
    return { show: true, reason: 'demo', text: '当前为演示数据模式（DATA_MODE=mock），数据来自内置演练数据，非真实后端。' };
  }
  if (useBackendState.getState().down) {
    return { show: true, reason: 'backend-down', text: '后端服务暂不可用，部分数据可能为离线演示数据，请稍后重试或联系管理员。' };
  }
  return null;
}

// service 层统一二选一辅助器：api 模式跑 apiFn，mock 模式跑 mockFn。
// api 模式下若 apiFn 抛网络错误且提供 fallbackToMock，则回退 mock 展示（此时黄条已由 request.ts 触发，常驻提示）。
export async function pick<T>(apiFn: () => Promise<T>, mockFn: () => Promise<T>, fallbackToMock = false): Promise<T> {
  if (DATA_MODE === 'mock') {
    return mockFn();
  }
  try {
    const result = await apiFn();
    // 调用成功说明后端恢复
    if (useBackendState.getState().down) resetBackend();
    return result;
  } catch (err: any) {
    if (fallbackToMock && err?.isNetwork) {
      return mockFn();
    }
    throw err;
  }
}
