import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import ObjectPeek from './index';

describe('供应商详情关系明细', () => {
  it('用结构化表格显示全部供货关系并标明默认主供', async () => {
    const user = userEvent.setup();
    render(<ObjectPeek type="供应商" name="测试供应商" data={{
      id: 'SUP-1',
      name: '测试供应商',
      relations: [
        { supplierMaterialId: 'SM-1', materialId: 'MAT-1', materialName: '芯片', supplierRank: 1, leadTimeHours: 48, supplierPrice: 10, availableEmergencyQty: 20, qualified: true, isDefault: true },
        { supplierMaterialId: 'SM-2', materialId: 'MAT-2', materialName: '电机', supplierRank: 2, leadTimeHours: 72, supplierPrice: 30, availableEmergencyQty: 5, qualified: false, isDefault: false },
      ],
    }} />);
    await user.click(screen.getByRole('button', { name: /测试供应商/ }));

    const detail = screen.getByRole('region', { name: '供货关系明细' });
    expect(within(detail).getByText('芯片')).toBeInTheDocument();
    expect(within(detail).getByText('电机')).toBeInTheDocument();
    expect(within(detail).getByText('默认主供')).toBeInTheDocument();
    expect(within(detail).getAllByText('可用应急量').length).toBeGreaterThan(0);
    expect(screen.queryByText('[object Object]')).not.toBeInTheDocument();
  });
});
