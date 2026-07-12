export default {
  'GET /api/import/history': (_req: any, res: any) => res.send({ data: [{ id: 'batch-1', type: '供应商', success: 126, failed: 2 }] })
};
