// 任务服务（双模式）。api 模式对接 /tasks*，mock 走 workflowStore。
import { currentUser } from './user';
import { appendAudit, workflowStore } from './workflowStore';
import { pick } from './dataMode';
import { apiGet, apiPatch, apiPost } from '../utils/request';

const actor = async () => (await currentUser())?.currentUser;

export async function getTasks(scope?: string) {
  return pick(
    () => apiGet('/tasks', { scope }),
    async () => {
      const tasks = workflowStore.listTasks();
      const data = scope === 'overdue' ? tasks.filter((item) => item.status === 'overdue') : tasks;
      return { data, total: data.length, success: true };
    },
  );
}

export async function updateTaskStatus(id: string, status: string) {
  return pick(
    async () => {
      await apiPatch(`/tasks/${id}`, { status });
      return { ok: true, id, status };
    },
    async () => {
      const task = workflowStore.listTasks().find((item) => item.id === id);
      if (!task) throw new Error('任务不存在');
      task.status = status;
      appendAudit('更新任务', 'task', id, task.title, { status }, await actor());
      return { ok: true, id, status };
    },
  );
}

export async function reassign(id: string, assignee: string) {
  return pick(
    async () => {
      await apiPatch(`/tasks/${id}`, { assignee });
      return { ok: true, id, assignee };
    },
    async () => {
      const task = workflowStore.listTasks().find((item) => item.id === id);
      if (!task) throw new Error('任务不存在');
      task.assignee = assignee;
      appendAudit('改派任务', 'task', id, task.title, { assignee }, await actor());
      return { ok: true, id, assignee };
    },
  );
}

export async function urge(id: string) {
  return pick(
    async () => {
      await apiPost(`/tasks/${id}/urge`, {});
      return { ok: true, id, message: '已发送站内信催办' };
    },
    async () => {
      const task = workflowStore.listTasks().find((item) => item.id === id);
      if (task) appendAudit('催办任务', 'task', id, task.title, {}, await actor());
      return { ok: true, id, message: '已发送站内信催办' };
    },
  );
}
