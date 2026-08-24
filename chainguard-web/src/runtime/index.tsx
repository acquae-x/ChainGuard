import type { ReactNode } from 'react';
import { createContext, useContext, useMemo } from 'react';
import { Navigate, useLocation, useParams } from 'react-router-dom';
import buildAccess from '../access';

export type InitialState = { currentUser?: API.User; tenant?: API.Tenant; token?: string };
type RuntimeValue = {
  initialState?: InitialState;
  setInitialState: (state?: InitialState) => Promise<void>;
};

const RuntimeContext = createContext<RuntimeValue>({
  initialState: undefined,
  setInitialState: async () => undefined,
});

export function RuntimeProvider({ value, children }: { value: RuntimeValue; children: ReactNode }) {
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}

export function useModel(name: string) {
  if (name !== '@@initialState') throw new Error(`未知运行时模型：${name}`);
  return useContext(RuntimeContext);
}

export function useAccess() {
  const { initialState } = useContext(RuntimeContext);
  return useMemo(() => buildAccess(initialState), [initialState]);
}

export function Access({ accessible, fallback = null, children }: { accessible: boolean; fallback?: ReactNode; children?: ReactNode }) {
  return <>{accessible ? children : fallback}</>;
}

function navigate(path: string, replace = false) {
  if (typeof window === 'undefined') return;
  window.history[replace ? 'replaceState' : 'pushState']({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export const history = {
  get location() {
    if (typeof window === 'undefined') return { pathname: '/', search: '', hash: '' };
    return window.location;
  },
  push: (path: string) => navigate(path),
  replace: (path: string) => navigate(path, true),
  back: () => window.history.back(),
};

export { Navigate, useLocation, useParams };
export type RunTimeLayoutConfig = (...args: any[]) => Record<string, unknown>;
