import { defineConfig } from '@umijs/max';
import routes from './routes';

export default defineConfig({
  antd: {},
  access: {},
  model: {},
  initialState: {},
  request: {},
  // Umi 4.6 的分块构建需要隔离 helper，避免异步 chunk 与 umi.js 发生 helper 命名冲突。
  esbuildMinifyIIFE: true,
  // 双数据源开关：api（真实后端，默认）| mock（内置演示数据）。见 Phase 2 §2.2
  define: {
    'process.env.DATA_MODE': process.env.DATA_MODE || 'api',
  },
  layout: {
    title: 'ChainGuard',
    locale: false
  },
  routes,
  npmClient: 'npm',
  proxy: {
    '/api': {
      target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
      changeOrigin: true
    }
  }
});
