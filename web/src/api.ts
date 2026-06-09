import type {
  AppSettings,
  ApprovalRequest,
  DashboardActivityPoint,
  DashboardSummary,
  FinalResponseProjection,
  ReviewProjection,
  RunProjection,
  RunStreamEvent,
  TerminalProjection,
  WorkspaceFolder,
} from './contracts';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8787';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { message?: string } | null;
    throw new Error(body?.message ?? `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export type WorkspaceTreeEntry = {
  name: string;
  path: string;
  kind: 'file' | 'directory';
  size?: number;
  language?: string;
  children?: WorkspaceTreeEntry[];
};

export const api = {
  workspaces: {
    recent: () => requestJson<WorkspaceFolder[]>('/api/workspaces/recent'),
    open: (path: string) => requestJson<WorkspaceFolder>('/api/workspaces/open', { method: 'POST', body: JSON.stringify({ path }) }),
    pick: () => requestJson<{ canceled: boolean; workspace?: WorkspaceFolder }>('/api/workspaces/pick', { method: 'POST' }),
    summary: (workspaceId: string) => requestJson<WorkspaceFolder>(`/api/workspaces/${workspaceId}/summary`),
    tree: (workspaceId: string, path?: string) => requestJson<{ path: string; entries: WorkspaceTreeEntry[] }>(`/api/workspaces/${workspaceId}/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  },
  runs: {
    list: () => requestJson<RunProjection[]>('/api/runs'),
    get: (runId: string) => requestJson<RunProjection>(`/api/runs/${runId}`),
    create: (payload: { workspaceId: string; objective: string; mode?: string }) => requestJson<RunProjection>('/api/runs', { method: 'POST', body: JSON.stringify(payload) }),
    delete: (runId: string) => requestJson<{ ok: true }>(`/api/runs/${runId}`, { method: 'DELETE' }),
    cancel: (runId: string) => requestJson<RunProjection>(`/api/runs/${runId}/cancel`, { method: 'POST' }),
    resume: (runId: string) => requestJson<RunProjection>(`/api/runs/${runId}/resume`, { method: 'POST' }),
    retry: (runId: string) => requestJson<RunProjection>(`/api/runs/${runId}/retry`, { method: 'POST' }),
    messages: {
      list: (runId: string) => requestJson<RunProjection['messages']>(`/api/runs/${runId}/messages`),
      send: (runId: string, content: string) => requestJson<{ message: RunProjection['messages'][number]; run: RunProjection }>(`/api/runs/${runId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),
    },
    events: (runId: string, onEvent: (event: RunStreamEvent) => void) => subscribeSSE(`/api/runs/${runId}/events`, onEvent),
    approvals: (runId: string) => requestJson<ApprovalRequest[]>(`/api/runs/${runId}/approvals`),
    review: (runId: string) => requestJson<ReviewProjection>(`/api/runs/${runId}/review`),
    diff: (runId: string) => requestJson<ReviewProjection>(`/api/runs/${runId}/diff`),
    terminal: {
      create: (runId: string, payload?: { cwd?: string; shell?: string }) => requestJson<TerminalProjection>(`/api/runs/${runId}/terminal`, {
        method: 'POST',
        body: JSON.stringify(payload ?? {}),
      }),
    },
    finalResponse: (runId: string) => requestJson<FinalResponseProjection | undefined>(`/api/runs/${runId}/final-response`),
  },
  approvals: {
    approve: (approvalId: string, note?: string) => requestJson<ApprovalRequest>(`/api/approvals/${approvalId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
    reject: (approvalId: string, note?: string) => requestJson<ApprovalRequest>(`/api/approvals/${approvalId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  },
  terminal: {
    input: (sessionId: string, command: string) => requestJson<TerminalProjection>(`/api/terminal/${sessionId}/input`, {
      method: 'POST',
      body: JSON.stringify({ command }),
    }),
    kill: (sessionId: string) => requestJson<TerminalProjection>(`/api/terminal/${sessionId}/kill`, { method: 'POST' }),
    events: (sessionId: string, onEvent: (event: RunStreamEvent) => void) => subscribeSSE(`/api/terminal/${sessionId}/events`, onEvent),
  },
  dashboard: {
    summary: () => requestJson<DashboardSummary>('/api/dashboard/summary'),
    activity: (days = 18) => requestJson<DashboardActivityPoint[]>(`/api/dashboard/activity?days=${days}`),
  },
  settings: {
    get: () => requestJson<AppSettings>('/api/settings'),
    patch: (payload: Partial<AppSettings>) => requestJson<AppSettings>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  },
};

function subscribeSSE(path: string, onEvent: (event: RunStreamEvent) => void) {
  const source = new EventSource(`${API_BASE}${path}`);
  const handler = (event: MessageEvent) => onEvent(JSON.parse(event.data) as RunStreamEvent);

  for (const name of ['run.updated', 'message.delta', 'message.completed', 'agent.updated', 'timeline.created', 'approval.created', 'approval.updated', 'review.updated', 'terminal.output']) {
    source.addEventListener(name, handler as EventListener);
  }

  source.addEventListener('error', () => {
    onEvent({ type: 'error', message: '事件流连接中断', severity: 'warning' });
  });

  return () => source.close();
}
