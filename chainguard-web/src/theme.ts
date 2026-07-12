import type { ThemeConfig } from 'antd';

export const palette = {
  primary: '#1B4F9C',
  error: '#CF1322',
  warning: '#D46B08',
  success: '#389E0D',
  info: '#0958D9',
  bgLayout: '#F5F6F8',
  chart: ['#3E6FA8', '#668C7E', '#9B7E46', '#7D6A9E', '#5E7C8A', '#8A7A65']
};

const theme: ThemeConfig = {
  token: {
    colorPrimary: palette.primary,
    colorError: palette.error,
    colorWarning: palette.warning,
    colorSuccess: palette.success,
    colorInfo: palette.info,
    colorBgLayout: palette.bgLayout,
    borderRadius: 6,
    wireframe: false
  },
  components: {
    Layout: { bodyBg: palette.bgLayout, headerBg: '#fff', siderBg: '#fff' },
    Card: { borderRadiusLG: 6 },
    Button: { borderRadius: 6 },
    Table: { headerBg: '#FAFAFA', rowHoverBg: '#F7FAFF' }
  }
};

export default theme;
