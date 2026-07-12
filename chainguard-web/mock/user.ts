import { login, currentUser } from '../src/services/user';

export default {
  'POST /api/login': async (req: any, res: any) => res.send(await login(req.body || {})),
  'GET /api/currentUser': async (_req: any, res: any) => res.send(await currentUser())
};
