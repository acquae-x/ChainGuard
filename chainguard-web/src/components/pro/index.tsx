import type { MutableRefObject, ReactNode } from 'react';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Card, DatePicker, Form, Select, Space, Statistic, Table, Typography } from 'antd';
import type { TableColumnsType, TablePaginationConfig, TableProps } from 'antd';

export type ProColumns<T> = TableColumnsType<T>[number] & {
  valueType?: string;
  copyable?: boolean;
  valueEnum?: Record<string, unknown>;
  search?: boolean;
  [key: string]: unknown;
};

type RequestResult<T> = { data?: T[]; total?: number; success?: boolean };
type ProTableAction = { reload: () => Promise<void> };
type ProTableProps<T extends object> = Omit<TableProps<T>, 'columns'> & {
  columns?: ProColumns<T>[];
  request?: (params: any) => Promise<RequestResult<T>>;
  params?: Record<string, unknown>;
  actionRef?: MutableRefObject<ProTableAction | undefined>;
  search?: unknown;
  options?: unknown;
  headerTitle?: ReactNode;
  tableAlertOptionRender?: () => ReactNode;
};

function LocalProTable<T extends object>(props: ProTableProps<T>, ref: React.ForwardedRef<ProTableAction>) {
  const {
    request,
    params = {},
    actionRef,
    search: _search,
    options: _options,
    headerTitle,
    tableAlertOptionRender,
    dataSource: controlledData,
    pagination: paginationProp,
    columns = [],
    ...tableProps
  } = props;
  const initialPageSize = typeof paginationProp === 'object'
    ? paginationProp.pageSize || paginationProp.defaultPageSize || 10
    : 10;
  const [data, setData] = useState<readonly T[]>(controlledData || []);
  const [loading, setLoading] = useState(false);
  const [current, setCurrent] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [total, setTotal] = useState(controlledData?.length || 0);
  const paramsKey = JSON.stringify(params);
  // Callers commonly pass an inline request adapter. Its identity changes on
  // every render, but that must not turn loading/data state updates into a
  // request loop that also resets Ant Table expansion state.
  const requestRef = useRef(request);
  requestRef.current = request;
  const autoLoadKey = `${current}\u0000${pageSize}\u0000${paramsKey}`;
  const lastAutoLoadKey = useRef<string>();
  const tableColumns = useMemo(() => columns.map((column) => {
    const compatible = column as ProColumns<T> & { renderText?: (value: unknown, row: T, index: number) => ReactNode };
    if (!compatible.render && compatible.renderText) {
      return { ...compatible, render: compatible.renderText };
    }
    return compatible;
  }) as TableColumnsType<T>, [columns]);

  const load = useCallback(async () => {
    const activeRequest = requestRef.current;
    if (!activeRequest) return;
    setLoading(true);
    try {
      const result = await activeRequest({ current, pageSize, ...params });
      setData(result.data || []);
      setTotal(result.total ?? result.data?.length ?? 0);
    } finally {
      setLoading(false);
    }
  }, [current, pageSize, paramsKey]);

  useEffect(() => {
    if (!requestRef.current || lastAutoLoadKey.current === autoLoadKey) return;
    // React Strict Mode deliberately runs mount effects twice in development.
    // Deduplicate that replay so a slower second response cannot replace table
    // data after the user has already expanded a row.
    lastAutoLoadKey.current = autoLoadKey;
    void load();
  }, [load, autoLoadKey, Boolean(request)]);
  useEffect(() => {
    if (controlledData) {
      setData(controlledData);
      setTotal(controlledData.length);
    }
  }, [controlledData]);

  const action = useMemo<ProTableAction>(() => ({ reload: load }), [load]);
  useImperativeHandle(ref, () => action, [action]);
  useEffect(() => {
    if (actionRef) actionRef.current = action;
    return () => { if (actionRef) actionRef.current = undefined; };
  }, [actionRef, action]);

  const pagination: false | TablePaginationConfig = paginationProp === false ? false : {
    ...(typeof paginationProp === 'object' ? paginationProp : {}),
    showTotal: typeof paginationProp === 'object' && paginationProp.showTotal
      ? paginationProp.showTotal
      : (value) => `总共 ${value} 条`,
    current,
    pageSize,
    total,
    onChange: (next, nextSize) => {
      setCurrent(nextSize !== pageSize ? 1 : next);
      setPageSize(nextSize);
      if (typeof paginationProp === 'object') paginationProp.onChange?.(next, nextSize);
    },
  };

  return <Space direction="vertical" size="middle" style={{ width: '100%', minWidth: 0 }}>
    {headerTitle ? <Typography.Title level={5} style={{ margin: 0 }}>{headerTitle}</Typography.Title> : null}
    {tableAlertOptionRender?.()}
    <Table<T>
      {...tableProps}
      columns={tableColumns}
      dataSource={data as T[]}
      loading={loading || tableProps.loading}
      pagination={pagination}
    />
  </Space>;
}

export const ProTable = forwardRef(LocalProTable) as <T extends object>(
  props: ProTableProps<T> & { ref?: React.ForwardedRef<ProTableAction> },
) => React.ReactElement;

export function PageContainer({ title, subTitle, extra, children, style }: {
  title?: ReactNode;
  subTitle?: ReactNode;
  extra?: ReactNode;
  children?: ReactNode;
  style?: React.CSSProperties;
}) {
  return <section style={{ width: '100%', minWidth: 0, ...style }}>
    {(title || subTitle || extra) && <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
      <div>
        {title ? <Typography.Title level={3} style={{ margin: 0 }}>{title}</Typography.Title> : null}
        {subTitle ? <Typography.Text type="secondary">{subTitle}</Typography.Text> : null}
      </div>
      {extra}
    </div>}
    {children}
  </section>;
}

export function StatisticCard({ statistic }: { statistic: { title?: ReactNode; value?: ReactNode; suffix?: ReactNode; description?: ReactNode } }) {
  return <Card><Statistic title={statistic.title} value={statistic.value as string | number} suffix={statistic.suffix} />{statistic.description ? <Typography.Text type="secondary">{statistic.description}</Typography.Text> : null}</Card>;
}

export function LightFilter<T extends object>({ children, initialValues, onValuesChange }: {
  children?: ReactNode;
  initialValues?: Partial<T>;
  onValuesChange?: (changed: Partial<T>, values: T) => void;
}) {
  return <Form layout="inline" initialValues={initialValues} onValuesChange={onValuesChange as never} style={{ rowGap: 8 }}>{children}</Form>;
}

export function ProFormSelect(props: { name: string; label?: ReactNode; options?: Array<{ value: string; label: ReactNode }>; [key: string]: unknown }) {
  const { name, label, options, ...selectProps } = props;
  return <Form.Item name={name} label={label}><Select allowClear options={options} style={{ minWidth: 120 }} {...selectProps} /></Form.Item>;
}

export function ProFormDateRangePicker(props: { name: string; label?: ReactNode; [key: string]: unknown }) {
  const { name, label, ...pickerProps } = props;
  return <Form.Item name={name} label={label}><DatePicker.RangePicker {...pickerProps} /></Form.Item>;
}
