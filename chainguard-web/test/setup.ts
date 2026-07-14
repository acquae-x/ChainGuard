import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// antd 组件在 jsdom 下用到 matchMedia，polyfill 之。
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// antd Table/ResizeObserver 依赖，jsdom 无实现。
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof window.ResizeObserver;
}

afterEach(() => cleanup());
