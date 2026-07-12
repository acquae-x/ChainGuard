export default {
  'GET /api/fields': (_req: any, res: any) => res.send({ data: [{ name: 'qualityScore', label: '质量评分' }] })
};
