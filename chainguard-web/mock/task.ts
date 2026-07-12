import { tasks } from '../src/services/mockData';

export default {
  'GET /api/tasks': (_req: any, res: any) => res.send({ data: tasks })
};
