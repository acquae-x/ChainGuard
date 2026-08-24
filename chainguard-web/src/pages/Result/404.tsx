import { history } from '@/runtime';
import { Result, Button } from 'antd';
export default () => <Result status="404" title="404" subTitle="页面不存在或已被移动。" extra={<Button type="primary" onClick={() => history.push('/dashboard')}>返回工作台</Button>} />;
