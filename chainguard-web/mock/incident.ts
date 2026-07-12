import { incident } from '../src/services/mockData';

export default {
  'GET /api/incidents': (_req: any, res: any) => res.send({ data: [incident], total: 1, success: true })
};
