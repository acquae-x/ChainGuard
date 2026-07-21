import { isApiMode } from './dataMode';
import { apiGet, apiPost } from '@/utils/request';

export type OnboardingStatus = {
  phase: 'empty' | 'preparing' | 'ready' | 'demo_ready';
  guideVisible: boolean;
  canInjectDemo: boolean;
  entitySummary: {
    counts: Record<string, number>;
    realCounts: Record<string, number>;
    demoCounts: Record<string, number>;
    isEmpty: boolean;
    hasBusinessData: boolean;
    hasRealData: boolean;
    hasDemoData: boolean;
    decisionReady: boolean;
  };
  state: { lastStep: string; dismissed: boolean; progress: Record<string, unknown> };
  recommendedData: Array<{ type: string; label: string; required: boolean; template: string; fields: string[] }>;
  recommendedOrder: string[];
  imports: Array<{ id: string; status: string; fileName: string }>;
};

const mockEmptyStatus: OnboardingStatus = {
  phase: 'empty', guideVisible: true, canInjectDemo: true,
  entitySummary: { counts: {}, realCounts: {}, demoCounts: {}, isEmpty: true, hasBusinessData: false, hasRealData: false, hasDemoData: false, decisionReady: false },
  state: { lastStep: 'welcome', dismissed: false, progress: {} },
  recommendedData: [], recommendedOrder: [], imports: [],
};

export async function getOnboardingStatus() {
  return isApiMode() ? apiGet<OnboardingStatus>('/onboarding/status') : mockEmptyStatus;
}

export async function saveProgress(values: Record<string, unknown>) {
  return isApiMode() ? apiPost<{ ok: boolean; status: OnboardingStatus }>('/onboarding/progress', values) : { ok: true, status: mockEmptyStatus };
}

export async function injectDemoDataset() {
  return apiPost<{ status: OnboardingStatus }>('/onboarding/demo-dataset', { values: { confirmed: true } });
}
