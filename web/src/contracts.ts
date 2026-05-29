export type WorkspaceKind = 'rust' | 'node' | 'python' | 'docs' | 'unknown';

export type WorkspaceFolder = {
  id: string;
  name: string;
  absolutePath: string;
  displayPath: string;
  lastOpenedAt?: string;
  projectKind?: WorkspaceKind;
  git?: {
    isRepo: boolean;
    branch?: string;
    dirty?: boolean;
    remote?: string;
  };
  summary?: string;
};

export type RunStatus =
  | 'initializing'
  | 'running'
  | 'needs_approval'
  | 'reviewing'
  | 'completed'
  | 'paused'
  | 'failed';

export type RuntimeAdapter = 'claude_code' | 'codex' | 'gemini_cli' | 'local' | 'system';

export type AgentStatus =
  | 'queued'
  | 'active'
  | 'waiting'
  | 'reviewing'
  | 'complete'
  | 'failed'
  | 'cancelled';

export type TimelineEvent = {
  id: string;
  runId: string;
  time: string;
  type: 'plan' | 'agent' | 'approval' | 'system' | 'error' | 'terminal' | 'review';
  title: string;
  detail: string;
  actor?: string;
  severity?: 'info' | 'warning' | 'error';
  relatedId?: string;
};

export type AgentProjection = {
  id: string;
  role: string;
  name: string;
  model?: string;
  runtime: RuntimeAdapter;
  status: AgentStatus;
  progress?: number;
  focus?: string;
  currentStep?: string;
  startedAt?: string;
  finishedAt?: string;
};

export type ArtifactProjection = {
  id: string;
  runId: string;
  kind: 'diff' | 'summary' | 'log' | 'doc' | 'file' | 'screenshot';
  title: string;
  description?: string;
  contentPreview?: string;
  uri?: string;
  filePath?: string;
  createdAt: string;
  createdBy: string;
};

export type ArtifactRef = {
  id: string;
  kind: ArtifactProjection['kind'];
  title: string;
};

export type FileOp = {
  path: string;
  change: 'added' | 'modified' | 'deleted' | 'renamed';
  add: number;
  del: number;
};

export type ChatMessage = {
  id: string;
  runId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  actor?: string;
  content: string;
  createdAt: string;
  status?: 'streaming' | 'complete' | 'failed';
  model?: string;
  startedAt?: string;
  finishedAt?: string;
  attachments?: ArtifactRef[];
  fileOps?: FileOp[];
};

export type ApprovalRequest = {
  id: string;
  runId: string;
  title: string;
  risk: 'low' | 'medium' | 'high';
  command?: string;
  reason: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  requestedBy: string;
  createdAt: string;
  resolvedAt?: string;
  policyHint?: string;
};

export type DiffHunkLine = {
  oldLine?: number;
  newLine?: number;
  type: 'context' | 'add' | 'del';
  content: string;
};

export type DiffHunk = {
  header: string;
  lines: DiffHunkLine[];
};

export type DiffFile = {
  path: string;
  status: 'added' | 'modified' | 'deleted' | 'renamed';
  add: number;
  del: number;
  language?: string;
  hunks: DiffHunk[];
};

export type RiskItem = {
  title: string;
  detail: string;
  severity: 'low' | 'medium' | 'high';
};

export type ReviewProjection = {
  baseRef?: string;
  headRef?: string;
  files: DiffFile[];
  summary?: string;
  riskItems?: RiskItem[];
};

export type TerminalLine = {
  id: string;
  text: string;
  kind: 'input' | 'output' | 'error' | 'status';
  createdAt: string;
};

export type TerminalProjection = {
  sessionId: string;
  runId: string;
  cwd: string;
  shell: string;
  status: 'idle' | 'running' | 'closed';
  lines: TerminalLine[];
};

export type FinalResponseProjection = {
  summary: string;
  remainingRisks: string[];
  nextSteps: string[];
};

export type RunProjection = {
  id: string;
  title: string;
  subtitle?: string;
  status: RunStatus;
  owner: string;
  objective: string;
  workspaceId: string;
  workspacePath: string;
  createdAt: string;
  updatedAt: string;
  durationMs: number;
  health?: number;
  agents: AgentProjection[];
  timeline: TimelineEvent[];
  messages: ChatMessage[];
  approvals: ApprovalRequest[];
  review?: ReviewProjection;
  terminal?: TerminalProjection;
  finalResponse?: FinalResponseProjection;
};

export type DashboardSummary = {
  sessions: number;
  messages: number;
  replies: number;
  approvals: number;
};

export type DashboardActivityPoint = {
  day: string;
  review: number;
  terminal: number;
  agent: number;
};

export type AppSettings = {
  theme: 'dark' | 'light';
  compactLayout: boolean;
  defaultRuntime: RuntimeAdapter;
  approvalPolicy: 'balanced' | 'strict' | 'relaxed';
  autoOpenInspector: boolean;
  recentWorkspaceLimit: number;
  autoRoute: boolean;
};

export type RunStreamEvent =
  | { type: 'run.updated'; run: Partial<RunProjection> & { id: string } }
  | { type: 'message.delta'; messageId: string; delta: string; runId: string }
  | { type: 'message.completed'; message: ChatMessage }
  | { type: 'agent.updated'; agent: AgentProjection; runId: string }
  | { type: 'timeline.created'; event: TimelineEvent }
  | { type: 'approval.created'; approval: ApprovalRequest }
  | { type: 'approval.updated'; approval: ApprovalRequest }
  | { type: 'review.updated'; review: ReviewProjection; runId: string }
  | { type: 'terminal.output'; sessionId: string; line: TerminalLine; runId: string }
  | { type: 'error'; message: string; severity: 'warning' | 'error'; runId?: string };
