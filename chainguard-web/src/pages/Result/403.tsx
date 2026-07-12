import { history } from '@umijs/max';
import { Result, Button } from 'antd';
export default () => <Result status="403" title="403" subTitle="当前角色无权访问此页面。" extra={<Button type="primary" onClick={() => history.push('/dashboard')}>返回工作台</Button>} />;
