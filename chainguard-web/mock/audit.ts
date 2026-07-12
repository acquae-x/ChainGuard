import { auditLogs } from '../src/services/mockData';

export default {
  'GET /api/audit': (_req: any, res: any) => res.send({ data: auditLogs })
};
