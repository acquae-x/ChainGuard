import { risks } from '../src/services/mockData';

export default {
  'GET /api/risks': (_req: any, res: any) => res.send({ data: risks, total: risks.length, success: true })
};
