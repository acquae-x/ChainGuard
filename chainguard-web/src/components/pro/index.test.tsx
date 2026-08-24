import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ProTable } from './index';

describe('ProTable', () => {
  it('does not reload when an inline request function is recreated by a parent render', async () => {
    const request = vi.fn().mockResolvedValue({
      data: [{ id: 'import-1', status: 'succeeded' }],
      total: 1,
      success: true,
    });

    function Harness({ label }: { label: string }) {
      return <div data-label={label}>
        <ProTable<{ id: string; status: string }>
          rowKey="id"
          pagination={false}
          request={async (params) => request(params)}
          columns={[{ title: '状态', dataIndex: 'status' }]}
        />
      </div>;
    }

    const view = render(<Harness label="first" />);
    await screen.findByText('succeeded');
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));

    view.rerender(<Harness label="second" />);
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  });
});
