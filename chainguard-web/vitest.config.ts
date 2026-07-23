import react from '@vitejs/plugin-react';
import { resolve } from 'path';

// 独立于 umi(webpack) 的组件测试管线：只跑 src/**/*.test.tsx（jsdom），不碰 e2e/。
// 导出 Vite/Vitest 都支持的普通配置对象，避免 Vitest 内置 Vite 5 与项目 Vite 4 的插件类型交叉。
export default {
  plugins: [react()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
};
