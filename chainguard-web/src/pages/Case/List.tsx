import { PageContainer } from '@ant-design/pro-components';
import { Card, Col, Empty, Input, Row, Space, Spin, Tag, Typography } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import { SensitiveField } from '@/components';
import { getExperienceCards } from '@/services/decision';

// 案例库与「经验卡片」页共用 /experiences 数据源：那页是表格视图，这页是卡片浏览视图。
// 此前本页是 3 条写死的假案例 + 无效搜索框，与后端真实经验库脱节。
export default function CaseList() {
  const [cards, setCards] = useState<API.ExperienceCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState('');

  useEffect(() => {
    getExperienceCards()
      .then(setCards)
      .finally(() => setLoading(false));
  }, []);

  // 经验卡有两种来源形态：决策闭环沉淀的带 retrievalCard（scenario/recommendedPattern/triggerConditions），
  // 早期/演示卡只有 title + content{trigger,action}。两种都要能正常展示，不能退化成只显示 id。
  const normalize = (item: API.ExperienceCard) => {
    const content = (item as any).content || {};
    const tags = item.triggerConditions?.length ? item.triggerConditions : [content.trigger].filter(Boolean);
    return {
      heading: item.scenario || (item as any).title || item.id,
      action: item.recommendedPattern || content.action || '',
      tags: tags as string[],
      summary: item.outcome?.summary || '',
    };
  };

  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    if (!needle) return cards;
    return cards.filter((item) => {
      const view = normalize(item);
      return [item.id, view.heading, view.action, ...view.tags]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle));
    });
  }, [cards, keyword]);

  return (
    <PageContainer title="案例库" subTitle="沉淀已完成事件的方案、审批意见与执行复盘">
      <Input
        prefix={<SearchOutlined />}
        placeholder="搜索事件类型、物料、供应商或经验编号"
        style={{ maxWidth: 520, marginBottom: 16 }}
        value={keyword}
        allowClear
        onChange={(event) => setKeyword(event.target.value)}
      />
      <Spin spinning={loading}>
        {filtered.length === 0 ? (
          <Empty description={keyword ? '没有匹配的案例' : '暂无本租户案例，完成一次决策复盘后会自动沉淀'} />
        ) : (
          <Row gutter={[16, 16]}>
            {filtered.map((item) => {
              const view = normalize(item);
              return (
                <Col xs={24} md={12} xl={8} key={item.id}>
                  <Card hoverable title={view.heading} extra={<Tag>{item.id}</Tag>}>
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Space wrap>
                        {view.tags.map((tag) => (
                          <Tag color="blue" key={tag}>
                            {tag}
                          </Tag>
                        ))}
                      </Space>
                      {view.summary && (
                        <Typography.Paragraph>
                          <SensitiveField field="cost" value={view.summary} />
                        </Typography.Paragraph>
                      )}
                      {view.action && (
                        <Typography.Text type="secondary">推荐动作：{view.action}</Typography.Text>
                      )}
                      {!view.summary && !view.action && (
                        <Typography.Text type="secondary">暂无复盘结论</Typography.Text>
                      )}
                    </Space>
                  </Card>
                </Col>
              );
            })}
          </Row>
        )}
      </Spin>
    </PageContainer>
  );
}
