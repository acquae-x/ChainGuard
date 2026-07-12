import { PageContainer } from '@ant-design/pro-components';
import { Card, Col, Input, Row, Space, Tag, Typography } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { SensitiveField } from '@/components';

const cases = [
  { id: 'EXP-019', title: '核心芯片供应商停产 72 小时应急', tags: ['供应中断', '电子制造'], result: '避免损失 73.2 万元，交付延误控制在 2 天。' },
  { id: 'EXP-014', title: '华东暴雨导致干线中断改道', tags: ['物流中断', '极端天气'], result: '通过公铁联运将延误从 4 天降至 1 天。' },
  { id: 'EXP-008', title: '高等级客户临时插单产能协调', tags: ['需求波动', '产能'], result: '保住 A 级客户订单且未影响原承诺。' }
];

export default function CaseList() {
  return <PageContainer title="案例库" subTitle="沉淀已完成事件的方案、审批意见与执行复盘"><Input prefix={<SearchOutlined />} placeholder="搜索事件类型、物料、供应商或经验编号" style={{ maxWidth: 520, marginBottom: 16 }} /><Row gutter={[16, 16]}>{cases.map((item) => <Col xs={24} md={12} xl={8} key={item.id}><Card hoverable title={item.title} extra={<Tag>{item.id}</Tag>}><Space direction="vertical"><Space>{item.tags.map((tag) => <Tag color="blue" key={tag}>{tag}</Tag>)}</Space><Typography.Paragraph>{item.id === 'EXP-019' ? <SensitiveField field="cost" value={item.result} /> : item.result}</Typography.Paragraph><Typography.Link>查看完整复盘</Typography.Link></Space></Card></Col>)}</Row></PageContainer>;
}
