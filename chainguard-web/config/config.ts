import { defineConfig } from '@umijs/max';
import routes from './routes';

export default defineConfig({
  antd: {},
  access: {},
  model: {},
  initialState: {},
  request: {},
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
      target: 'http://127.0.0.1:8000',
      changeOrigin: true
    }
  }
});
