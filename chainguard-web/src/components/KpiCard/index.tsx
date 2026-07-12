import { StatisticCard } from '@ant-design/pro-components';

export default function KpiCard({ title, value, suffix, trend }: { title: string; value: number | string; suffix?: string; trend?: string }) {
  return (
    <StatisticCard
      statistic={{
        title,
        value,
        suffix,
        description: trend
      }}
    />
  );
}
