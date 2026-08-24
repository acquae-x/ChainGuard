import { history } from '@/runtime';
import { Result, Button, Space } from 'antd';
export default () => <Result status="500" title="服务暂时不可用" subTitle="请求未完成，可稍后重试或返回工作台。" extra={<Space><Button onClick={() => location.reload()}>重试</Button><Button type="primary" onClick={() => history.push('/dashboard')}>返回工作台</Button></Space>} />;
