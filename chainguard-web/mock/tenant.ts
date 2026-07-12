import { tenant } from '../src/services/mockData';

export default {
  'GET /api/tenant': (_req: any, res: any) => res.send(tenant)
};
