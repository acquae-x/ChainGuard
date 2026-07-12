import { approvals, proposals } from '../src/services/mockData';

export default {
  'GET /api/proposals': (_req: any, res: any) => res.send({ data: proposals }),
  'GET /api/approvals': (_req: any, res: any) => res.send({ data: approvals })
};
