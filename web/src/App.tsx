import {
  Activity,
  Ban,
  Check,
  ChevronDown,
  CircleAlert,
  Clock,
  Command,
  Cpu,
  FilePen,
  FilePlus,
  FileText,
  FileX,
  Folder,
  FolderOpen,
  GitBranch,
  Layers,
  MessagesSquare,
  PanelRight,
  Plus,
  Send,
  Settings,
  Sparkles,
  Square,
  TerminalSquare,
  TrendingUp,
  UserRound,
  X,
  Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from 'react';
import { api, type WorkspaceTreeEntry } from './api';
import type {
  ApprovalRequest,
  AppSettings,
  DashboardActivityPoint,
  DashboardSummary,
  DiffFile,
  RunProjection,
  RunStreamEvent,
  RunStatus,
  TerminalLine,
  WorkspaceFolder,
} from './contracts';

type RailView = 'sessions' | 'dashboard' | 'settings';
type InspectorTab = 'review' | 'terminal';

const INSPECTOR_WIDTH_STORAGE_KEY = 'ai-collab.inspector-width.v1';
const DEFAULT_INSPECTOR_WIDTH = 430;
const MIN_INSPECTOR_WIDTH = 280;
const MAX_INSPECTOR_WIDTH = 760;

const runStatusTone: Record<RunStatus, string> = {
  initializing: 'running',
  running: 'running',
  needs_approval: 'needs_approval',
  reviewing: 'reviewing',
  completed: 'completed',
  paused: 'reviewing',
  failed: 'needs_approval',
};

const approvalRiskLabel: Record<ApprovalRequest['risk'], string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
};

function formatDuration(durationMs: number) {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

function formatRelativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff)) return '';
  if (diff < 60_000) return '刚刚';
  const minutes = Math.round(diff / 60_000);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  return `${days} 天前`;
}

function formatClock(date: Date) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function readStoredInspectorWidth() {
  if (typeof window === 'undefined') return DEFAULT_INSPECTOR_WIDTH;
  try {
    const value = Number.parseInt(window.localStorage.getItem(INSPECTOR_WIDTH_STORAGE_KEY) ?? '', 10);
    if (!Number.isFinite(value)) return DEFAULT_INSPECTOR_WIDTH;
    return clampNumber(value, MIN_INSPECTOR_WIDTH, MAX_INSPECTOR_WIDTH);
  } catch {
    return DEFAULT_INSPECTOR_WIDTH;
  }
}

function storeInspectorWidth(value: number) {
  try {
    window.localStorage.setItem(INSPECTOR_WIDTH_STORAGE_KEY, String(clampNumber(value, MIN_INSPECTOR_WIDTH, MAX_INSPECTOR_WIDTH)));
  } catch {
    // ignore storage access errors
  }
}

function mergeRuns(runs: RunProjection[], nextRun: RunProjection) {
  const index = runs.findIndex((run) => run.id === nextRun.id);
  if (index === -1) return [nextRun, ...runs];
  const next = runs.slice();
  next[index] = nextRun;
  return next;
}

function replaceRun(runs: RunProjection[], previousId: string, nextRun: RunProjection) {
  const index = runs.findIndex((run) => run.id === previousId);
  if (index === -1) return mergeRuns(runs, nextRun);
  const next = runs.slice();
  next[index] = nextRun;
  return next;
}

function renderInlineMarkdown(text: string, keyPrefix = 'md') {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.filter(Boolean).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={key}>{part.slice(1, -1)}</code>;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('*') && part.endsWith('*')) return <em key={key}>{part.slice(1, -1)}</em>;
    return <span key={key}>{part}</span>;
  });
}

function renderMarkdown(text: string) {
  const elements: React.ReactNode[] = [];
  const lines = text.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        code.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      elements.push(
        <pre className="md-code-block" key={`code-${elements.length}`}>
          {lang ? <span className="md-code-lang">{lang}</span> : null}
          <code>{code.join('\n')}</code>
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = renderInlineMarkdown(heading[2], `h-${elements.length}`);
      elements.push(level === 1
        ? <h3 key={`h-${elements.length}`}>{content}</h3>
        : level === 2
          ? <h4 key={`h-${elements.length}`}>{content}</h4>
          : <h5 key={`h-${elements.length}`}>{content}</h5>);
      i += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(<li key={`li-${i}`}>{renderInlineMarkdown(lines[i].replace(/^\s*[-*]\s+/, ''), `li-${i}`)}</li>);
        i += 1;
      }
      elements.push(<ul key={`ul-${elements.length}`}>{items}</ul>);
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(<li key={`oli-${i}`}>{renderInlineMarkdown(lines[i].replace(/^\s*\d+[.)]\s+/, ''), `oli-${i}`)}</li>);
        i += 1;
      }
      elements.push(<ol key={`ol-${elements.length}`}>{items}</ol>);
      continue;
    }

    const paragraph: string[] = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith('```') && !/^(#{1,3})\s+/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) && !/^\s*\d+[.)]\s+/.test(lines[i])) {
      paragraph.push(lines[i]);
      i += 1;
    }
    elements.push(<p key={`p-${elements.length}`}>{renderInlineMarkdown(paragraph.join('\n'), `p-${elements.length}`)}</p>);
  }
  return elements.length ? elements : <p />;
}

function MarkdownMessage({ text }: { text: string }) {
  return <div className="markdown-body">{renderMarkdown(text)}</div>;
}

function formatElapsedSeconds(startedAt?: string) {
  if (!startedAt) return '0s';
  const start = new Date(startedAt).getTime();
  if (!Number.isFinite(start)) return '0s';
  const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function messageRuntime(message: RunProjection['messages'][number]) {
  const raw = `${message.model ?? ''} ${message.actor ?? ''}`.toLowerCase();
  if (raw.includes('claude')) return 'claude';
  if (raw.includes('gemini')) return 'gemini';
  if (raw.includes('codex')) return 'codex';
  return 'ai';
}

function normalizeProviderNoise(text: string) {
  // Stream/token glitches from provider CLIs can duplicate adjacent CJK words
  // character-by-character ("我我先先找到找到"). Collapse only pure CJK repeated
  // runs so English/paths/code remain untouched.
  return text.replace(/([一-鿿]{1,4})\1/g, '$1');
}

function appendMessageDelta(content: string, delta: string) {
  const nextDelta = normalizeProviderNoise(delta);
  if (!nextDelta) return content;
  if (content.endsWith(nextDelta)) return content;
  // Duplicate SSE listeners or provider retries can resend the same line. Avoid
  // accumulating repeated status/sentence blocks.
  const deltaTrimmed = nextDelta.trim();
  if (deltaTrimmed) {
    const lines = content.split('\n').map((line) => line.trim()).filter(Boolean);
    if (lines[lines.length - 1] === deltaTrimmed) return content;
  }
  return content + nextDelta;
}

function createThinkingMessage(runId: string, startedAt: string): RunProjection['messages'][number] {
  return {
    id: `${runId}-thinking-${startedAt}`,
    runId,
    role: 'assistant',
    actor: 'Codex',
    content: '',
    createdAt: startedAt,
    startedAt,
    status: 'streaming',
  };
}

function applyRunEvent(runs: RunProjection[], event: RunStreamEvent) {
  switch (event.type) {
    case 'run.updated':
      return mergeRuns(runs, {
        ...(runs.find((run) => run.id === event.run.id) ?? ({} as RunProjection)),
        ...event.run,
      } as RunProjection);
    case 'message.delta':
      return runs.map((run) => {
        if (run.id !== event.runId) return run;
        const messages = run.messages.slice();
        const current = messages.find((message) => message.id === event.messageId);
        if (current) {
          current.content = appendMessageDelta(current.content, event.delta);
          current.status = 'streaming';
          return { ...run, messages, updatedAt: new Date().toISOString() };
        }
        const now = new Date().toISOString();
        messages.push({
          id: event.messageId,
          runId: run.id,
          role: 'assistant',
          actor: 'AI',
          model: 'ai',
          content: normalizeProviderNoise(event.delta),
          createdAt: now,
          startedAt: now,
          status: 'streaming',
        });
        return { ...run, messages, updatedAt: new Date().toISOString() };
      });
    case 'message.completed':
      return runs.map((run) => {
        if (run.id !== event.message.runId) return run;
        const messages = run.messages.slice();
        const index = messages.findIndex((item) => item.id === event.message.id);
        const nextMessage = {
          ...event.message,
          startedAt: event.message.startedAt ?? event.message.createdAt,
          finishedAt: event.message.finishedAt ?? event.message.createdAt,
        };
        if (index >= 0) messages[index] = nextMessage;
        else messages.push(nextMessage);
        return { ...run, messages, updatedAt: event.message.createdAt };
      });
    case 'agent.updated':
      return runs.map((run) => run.id === event.runId
        ? { ...run, agents: run.agents.map((agent) => agent.id === event.agent.id ? event.agent : agent) }
        : run);
    case 'timeline.created':
      return runs.map((run) => run.id === event.event.runId
        ? { ...run, timeline: [event.event, ...run.timeline.filter((item) => item.id !== event.event.id)] }
        : run);
    case 'approval.created':
      return runs.map((run) => run.id === event.approval.runId
        ? { ...run, approvals: [event.approval, ...run.approvals.filter((item) => item.id !== event.approval.id)] }
        : run);
    case 'approval.updated':
      return runs.map((run) => run.id === event.approval.runId
        ? { ...run, approvals: run.approvals.map((approval) => approval.id === event.approval.id ? event.approval : approval) }
        : run);
    case 'review.updated':
      return runs.map((run) => run.id === event.runId ? { ...run, review: event.review } : run);
    case 'terminal.output':
      return runs.map((run) => {
        if (run.id !== event.runId) return run;
        const terminal = run.terminal ?? {
          sessionId: event.sessionId,
          runId: run.id,
          cwd: run.workspacePath,
          shell: 'zsh',
          status: 'idle',
          lines: [],
        };
        const lines = [...terminal.lines, event.line];
        const nextStatus: 'idle' | 'running' = event.line.kind === 'status' ? 'idle' : 'running';
        const nextTerminal = { ...terminal, lines, status: nextStatus };
        return { ...run, terminal: nextTerminal };
      });
    case 'error':
      return runs;
    default:
      return runs;
  }
}

function reviewStats(files: DiffFile[]) {
  return files.reduce((acc, file) => {
    acc.add += file.add;
    acc.del += file.del;
    return acc;
  }, { add: 0, del: 0 });
}

function computeRuntimeShare(runs: RunProjection[]) {
  const totals = runs.reduce((acc, run) => {
    for (const agent of run.agents) {
      acc[agent.runtime] = (acc[agent.runtime] ?? 0) + 1;
    }
    return acc;
  }, {} as Record<string, number>);
  const total = Object.values(totals).reduce((sum, count) => sum + count, 0) || 1;
  return [
    ['Claude', totals.claude_code ?? 0],
    ['Codex', totals.codex ?? 0],
    ['Gemini', totals.gemini_cli ?? 0],
    ['Local', totals.local ?? 0],
  ].map(([label, value]) => [String(label), Number(value) / total * 100] as const);
}

function flattenTree(nodes: WorkspaceTreeEntry[], prefix = '') {
  const result: WorkspaceTreeEntry[] = [];
  for (const node of nodes) {
    result.push(node);
    if ('children' in node && Array.isArray((node as WorkspaceTreeEntry & { children?: WorkspaceTreeEntry[] }).children)) {
      result.push(...flattenTree((node as WorkspaceTreeEntry & { children?: WorkspaceTreeEntry[] }).children ?? [], `${prefix}${node.name}/`));
    }
  }
  return result;
}

function stripPromptPrefix(text: string) {
  return text.replace(/^\s*\$\s*/, '');
}

function diffAnchorId(path: string) {
  return `diff-${path.replace(/[^a-zA-Z0-9]/g, '-')}`;
}

function shortCwd(path?: string) {
  if (!path) return '~';
  const parts = path.split('/').filter(Boolean);
  if (parts.length <= 2) return `/${parts.join('/')}`;
  return `…/${parts.slice(-2).join('/')}`;
}

function useCountUp(target: number, duration = 900) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setValue(target);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

function CountUp({ value, decimals = 0, suffix = '' }: { value: number; decimals?: number; suffix?: string }) {
  const animated = useCountUp(value);
  return <>{animated.toFixed(decimals)}{suffix}</>;
}

const ACTIVITY_SERIES = [
  { key: 'review' as const, label: '用户', color: 'var(--cream)' },
  { key: 'agent' as const, label: 'AI 回复', color: 'var(--blue)' },
  { key: 'terminal' as const, label: '终端', color: 'var(--violet)' },
];

function smoothPath(points: Array<[number, number]>) {
  if (points.length < 2) return points.length ? `M ${points[0][0]} ${points[0][1]}` : '';
  let d = `M ${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const cx = (x0 + x1) / 2;
    d += ` C ${cx.toFixed(1)} ${y0.toFixed(1)}, ${cx.toFixed(1)} ${y1.toFixed(1)}, ${x1.toFixed(1)} ${y1.toFixed(1)}`;
  }
  return d;
}

function ActivityChart({ data }: { data: DashboardActivityPoint[] }) {
  const W = 520;
  const H = 168;
  const PAD = 10;
  const totals = data.map((point) => point.review + point.terminal + point.agent);
  const max = Math.max(1, ...totals);
  const stepX = data.length > 1 ? (W - PAD * 2) / (data.length - 1) : 0;
  const yFor = (value: number) => H - PAD - (value / max) * (H - PAD * 2);
  // Cumulative (stacked) layers — largest drawn first so smaller bands sit on top.
  const layers = [
    { key: 'terminal' as const, color: 'var(--violet)', cum: data.map((p) => p.review + p.agent + p.terminal) },
    { key: 'agent' as const, color: 'var(--blue)', cum: data.map((p) => p.review + p.agent) },
    { key: 'review' as const, color: 'var(--cream)', cum: data.map((p) => p.review) },
  ];

  return (
    <svg className="activity-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="活动趋势">
      <defs>
        {ACTIVITY_SERIES.map((series) => (
          <linearGradient key={series.key} id={`grad-${series.key}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={series.color} stopOpacity="0.42" />
            <stop offset="100%" stopColor={series.color} stopOpacity="0.04" />
          </linearGradient>
        ))}
        <clipPath id="reveal-clip">
          <rect className="chart-reveal" x="0" y="0" width={W} height={H} />
        </clipPath>
      </defs>
      {[0.25, 0.5, 0.75].map((ratio) => (
        <line key={ratio} className="chart-grid" x1={PAD} x2={W - PAD} y1={H * ratio} y2={H * ratio} />
      ))}
      <g clipPath="url(#reveal-clip)">
        {layers.map((layer) => {
          const points = layer.cum.map((value, index): [number, number] => [PAD + index * stepX, yFor(value)]);
          if (points.length < 2) return null;
          const line = smoothPath(points);
          const area = `${line} L ${W - PAD} ${H - PAD} L ${PAD} ${H - PAD} Z`;
          return (
            <g key={layer.key}>
              <path d={area} fill={`url(#grad-${layer.key})`} />
              <path className="chart-line" d={line} fill="none" stroke={layer.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
            </g>
          );
        })}
      </g>
    </svg>
  );
}

type DonutSegment = { label: string; value: number; color: string };

function DonutChart({ segments }: { segments: DonutSegment[] }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const total = segments.reduce((sum, segment) => sum + Math.max(0, segment.value), 0);
  const r = 52;
  const cx = 64;
  const cy = 64;
  const circ = 2 * Math.PI * r;
  let acc = 0;
  return (
    <div className="donut-wrap">
      <svg className="donut" viewBox="0 0 128 128" role="img" aria-label="数据构成">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--hover)" strokeWidth={13} />
        {total > 0 && segments.map((segment) => {
          const len = (Math.max(0, segment.value) / total) * circ;
          const dashoffset = mounted ? -acc : -circ;
          acc += len;
          if (segment.value <= 0) return null;
          return (
            <circle
              key={segment.label}
              className="donut-seg"
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={segment.color}
              strokeWidth={13}
              strokeLinecap="round"
              strokeDasharray={`${len} ${circ - len}`}
              strokeDashoffset={dashoffset}
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          );
        })}
        <text className="donut-total" x={cx} y={cy} textAnchor="middle" dominantBaseline="central">{total}</text>
      </svg>
      <div className="donut-legend">
        {segments.map((segment) => (
          <span key={segment.label}><i style={{ background: segment.color }} />{segment.label}<b>{segment.value}</b></span>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const shellRef = useRef<HTMLElement | null>(null);
  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const eventUnsubscribeRef = useRef<(() => void) | null>(null);
  const stickToBottomRef = useRef(true);
  const terminalInputRef = useRef<HTMLInputElement | null>(null);

  const [activeView, setActiveView] = useState<RailView>('sessions');
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [reviewTabOpen, setReviewTabOpen] = useState(true);
  const [terminalTabOpen, setTerminalTabOpen] = useState(true);
  const [activeInspectorTab, setActiveInspectorTab] = useState<InspectorTab>('review');
  const [diffFilesOpen, setDiffFilesOpen] = useState(true);
  const [collapsedDiffFiles, setCollapsedDiffFiles] = useState<Record<string, boolean>>({});
  const [inspectorWidth, setInspectorWidth] = useState(readStoredInspectorWidth);
  const [fileTreeWidth, setFileTreeWidth] = useState(150);

  const [workspaces, setWorkspaces] = useState<WorkspaceFolder[]>([]);
  const [runs, setRuns] = useState<RunProjection[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>('');
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>('');
  const [workspaceTree, setWorkspaceTree] = useState<WorkspaceTreeEntry[]>([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [newConversationMode, setNewConversationMode] = useState(true);
  const [composerText, setComposerText] = useState('');
  const [terminalCommand, setTerminalCommand] = useState('');
  const [draftTerminalLines, setDraftTerminalLines] = useState<TerminalLine[]>([]);
  const [clock, setClock] = useState(() => new Date());
  const [pendingReplyRunId, setPendingReplyRunId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [thinkingStartedAt, setThinkingStartedAt] = useState<number | null>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(() => new Set());

  const toggleMessageExpanded = (id: string) => setExpandedMessages((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const [dashboardSummary, setDashboardSummary] = useState<DashboardSummary | null>(null);
  const [dashboardActivity, setDashboardActivity] = useState<DashboardActivityPoint[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const selectedRun = useMemo(() => runs.find((run) => run.id === selectedRunId), [runs, selectedRunId]);
  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? undefined,
    [workspaces, selectedWorkspaceId],
  );
  const hasLeftPanel = activeView === 'sessions';
  const canOpenInspector = activeView !== 'settings';
  const inspectorOpen = rightOpen && canOpenInspector;
  const inspectorTabs: { id: InspectorTab; label: string; icon: typeof FileText }[] = activeView === 'dashboard'
    ? [{ id: 'terminal', label: '终端', icon: TerminalSquare }]
    : [
        { id: 'review', label: '改动', icon: FileText },
        { id: 'terminal', label: '终端', icon: TerminalSquare },
      ];
  const effectiveTab: InspectorTab = inspectorTabs.some((tab) => tab.id === activeInspectorTab) ? activeInspectorTab : inspectorTabs[0].id;
  const showReviewPanel = effectiveTab === 'review' && activeView === 'sessions';

  useEffect(() => {
    const load = async () => {
      try {
        const [workspaceList, runList, summary, activity, appSettings] = await Promise.all([
          api.workspaces.recent(),
          api.runs.list(),
          api.dashboard.summary(),
          api.dashboard.activity(18),
          api.settings.get(),
        ]);
        setWorkspaces(workspaceList);
        setRuns(runList);
        setDashboardSummary(summary);
        setDashboardActivity(activity);
        setSettings(appSettings);
        setSelectedRunId((current) => current || '');
        setNewConversationMode(true);
      } catch (error) {
        setPageError(error instanceof Error ? error.message : '加载失败');
      }
    };
    void load();
  }, []);

  useEffect(() => {
    eventUnsubscribeRef.current?.();
    eventUnsubscribeRef.current = null;
    if (!selectedRunId || selectedRunId.startsWith('draft-')) return;
    eventUnsubscribeRef.current = api.runs.events(selectedRunId, (event) => {
      setRuns((current) => applyRunEvent(current, event));
    });
    return () => {
      eventUnsubscribeRef.current?.();
      eventUnsubscribeRef.current = null;
    };
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedWorkspaceId || !newConversationMode) return;
    void (async () => {
      try {
        const tree = await api.workspaces.tree(selectedWorkspaceId);
        setWorkspaceTree(flattenTree(tree.entries).slice(0, 16));
      } catch {
        setWorkspaceTree([]);
      }
    })();
  }, [selectedWorkspaceId, newConversationMode]);

  useEffect(() => {
    if (!selectedRun) return;
    if (selectedRun.review && !reviewTabOpen) setReviewTabOpen(true);
    if (selectedRun.terminal && !terminalTabOpen) setTerminalTabOpen(true);
  }, [selectedRun?.id]);

  // Switching conversation (or entering/leaving draft mode) jumps to the latest message.
  useEffect(() => {
    const el = messageScrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    stickToBottomRef.current = true;
  }, [selectedRunId, newConversationMode]);

  // Follow streaming/new replies only while the user is already pinned to the bottom,
  // so a reply never yanks the view away from earlier scrollback they're reading.
  const lastMessage = selectedRun?.messages[selectedRun.messages.length - 1];
  useEffect(() => {
    const el = messageScrollRef.current;
    if (!el || !stickToBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [selectedRun?.messages.length, lastMessage?.content, lastMessage?.status]);

  const handleMessageScroll = () => {
    const el = messageScrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  useEffect(() => {
    if (activeView !== 'dashboard') return;
    // Refetch on every visit so the dashboard reflects current real data.
    void (async () => {
      try {
        const [summary, activity] = await Promise.all([api.dashboard.summary(), api.dashboard.activity(18)]);
        setDashboardSummary(summary);
        setDashboardActivity(activity);
      } catch {
        // ignore
      }
    })();
  }, [activeView]);

  useEffect(() => {
    if (activeInspectorTab !== 'terminal' || !terminalTabOpen) return;
    terminalInputRef.current?.focus();
  }, [activeInspectorTab, terminalTabOpen, selectedRun?.terminal?.sessionId]);

  const openInspector = () => {
    setRightOpen(true);
  };

  const toggleInspector = () => {
    setRightOpen((open) => !open);
  };

  const selectRun = (runId: string) => {
    setSelectedRunId(runId);
    setNewConversationMode(false);
    setActiveView('sessions');
    setLeftOpen(true);
    setRightOpen(settings?.autoOpenInspector ?? true);
    setActiveInspectorTab('review');
  };

  const startNewConversation = () => {
    setSelectedRunId('');
    setNewConversationMode(true);
    setLeftOpen(true);
    setRightOpen(false);
    setActiveView('sessions');
    setSelectedWorkspaceId('');
    setWorkspaceTree([]);
  };

  const chooseWorkspace = (workspace: WorkspaceFolder) => {
    setSelectedWorkspaceId(workspace.id);
  };

  const pickWorkspace = async () => {
    setWorkspaceLoading(true);
    try {
      const result = await api.workspaces.pick();
      if (result.canceled || !result.workspace) return;
      const opened = result.workspace;
      setWorkspaces((current) => [opened, ...current.filter((workspace) => workspace.id !== opened.id && workspace.absolutePath !== opened.absolutePath)]);
      setSelectedWorkspaceId(opened.id);
      setWorkspaceTree([]);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '选择文件夹失败');
    } finally {
      setWorkspaceLoading(false);
    }
  };

  const createRunFromDraft = async (objective: string) => {
    const content = objective.trim();
    if (!content || !selectedWorkspace) return;
    const draftId = `draft-${Date.now()}`;
    const now = new Date().toISOString();
    const draftRun: RunProjection = {
      id: draftId,
      title: content.slice(0, 24) || 'Chat',
      subtitle: '聊天驱动会话',
      status: 'running',
      owner: 'Codex',
      objective: content,
      workspaceId: selectedWorkspace.id,
      workspacePath: selectedWorkspace.absolutePath,
      createdAt: now,
      updatedAt: now,
      durationMs: 0,
      health: 12,
      agents: [],
      timeline: [],
      messages: [
        {
          id: `${draftId}-msg-user`,
          runId: draftId,
          role: 'user',
          actor: 'You',
          content,
          createdAt: now,
          status: 'complete',
        },
      ],
      approvals: [],
    };

    setWorkspaceLoading(true);
    setPendingReplyRunId(draftId);
    setRuns((current) => [draftRun, ...current.filter((run) => run.id !== draftId)]);
    setSelectedRunId(draftId);
    setNewConversationMode(false);
    setActiveView('sessions');
    setRightOpen(settings?.autoOpenInspector ?? true);
    setReviewTabOpen(true);
    setActiveInspectorTab('review');
    setComposerText('');
    setWorkspaceTree([]);

    try {
      const run = await api.runs.create({
        workspaceId: selectedWorkspace.id,
        objective: content,
        mode: 'chat',
      });
      setRuns((current) => replaceRun(current, draftId, run));
      setSelectedRunId(run.id);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '创建会话失败');
      setRuns((current) => current.filter((run) => run.id !== draftId));
      setSelectedRunId('');
      setNewConversationMode(true);
    } finally {
      setPendingReplyRunId((current) => (current === draftId ? null : current));
      setWorkspaceLoading(false);
    }
  };

  const sendComposer = async (event?: FormEvent) => {
    event?.preventDefault();
    const content = composerText.trim();
    if (!content) return;
    if (newConversationMode) {
      await createRunFromDraft(content);
      return;
    }
    if (!selectedRun) return;
    const pendingRunId = selectedRun.id;
    const now = new Date().toISOString();
    const optimisticUserMessage: RunProjection['messages'][number] = {
      id: `${pendingRunId}-user-${Date.now()}`,
      runId: pendingRunId,
      role: 'user',
      actor: 'You',
      content,
      createdAt: now,
      status: 'complete',
    };
    // Add the user's turn immediately. Without this, the POST can return before the
    // SSE placeholder arrives and the UI appears frozen during long provider work.
    setRuns((current) => current.map((run) => run.id === pendingRunId
      ? { ...run, messages: [...run.messages, optimisticUserMessage], updatedAt: now }
      : run));
    setComposerText('');
    try {
      setPendingReplyRunId(pendingRunId);
      const result = await api.runs.messages.send(pendingRunId, content);
      setRuns((current) => mergeRuns(current, result.run));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '发送失败');
    } finally {
      setPendingReplyRunId((current) => (current === pendingRunId ? null : current));
    }
  };

  const handleComposerButton = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (awaitingReply && selectedRun) {
      event.preventDefault();
      void cancelCurrentReply();
    }
  };

  const cancelCurrentReply = async () => {
    if (!selectedRun) return;
    try {
      const run = await api.runs.cancel(selectedRun.id);
      setPendingReplyRunId((current) => (current === selectedRun.id ? null : current));
      setRuns((current) => mergeRuns(current, run));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '终止失败');
    }
  };

  const handleApproval = async (approvalId: string, action: 'approve' | 'reject') => {
    try {
      const approval = action === 'approve'
        ? await api.approvals.approve(approvalId, '已由前端确认')
        : await api.approvals.reject(approvalId, '已由前端拒绝');
      setRuns((current) => current.map((run) => run.id === approval.runId
        ? {
            ...run,
            approvals: run.approvals.map((item) => item.id === approval.id ? approval : item),
          }
        : run));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '审批操作失败');
    }
  };

  const deleteRun = async (runId: string) => {
    const run = runs.find((item) => item.id === runId);
    if (!run) return;
    setConfirmDeleteId(null);
    const snapshot = runs;
    // Optimistically drop it so the list refreshes instantly.
    setRuns((current) => current.filter((item) => item.id !== runId));
    if (selectedRunId === runId) {
      setSelectedRunId('');
      setNewConversationMode(true);
      setRightOpen(false);
    }
    // Draft runs only live on the client; nothing to delete on the server.
    if (runId.startsWith('draft-')) return;
    try {
      await api.runs.delete(runId);
    } catch (error) {
      setRuns(snapshot);
      setPageError(error instanceof Error ? error.message : '删除失败');
    }
  };

  const handleTerminalSubmit = async (event?: FormEvent | KeyboardEvent<HTMLInputElement>) => {
    event?.preventDefault();
    const command = terminalCommand.trim();
    const sessionId = selectedRun?.terminal?.sessionId;
    if (!command) return;
    setTerminalCommand('');
    if (!selectedRun || !sessionId) {
      const createdAt = new Date().toISOString();
      setDraftTerminalLines((current) => [
        ...current,
        { id: `draft-${createdAt}-input`, text: command, kind: 'input', createdAt },
        { id: `draft-${createdAt}-status`, text: '本地预览模式只记录命令，不执行 shell。', kind: 'status', createdAt },
      ]);
      return;
    }
    try {
      const terminal = await api.terminal.input(sessionId, command);
      setRuns((current) => current.map((run) => run.id === selectedRun.id ? { ...run, terminal } : run));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '终端命令发送失败');
    }
  };

  const updateSettings = async (patch: Partial<AppSettings>) => {
    try {
      const next = await api.settings.patch(patch);
      setSettings(next);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '设置更新失败');
    }
  };

  const toggleTheme = (value: AppSettings['theme'], event: { clientX: number; clientY: number }) => {
    if ((settings?.theme ?? 'dark') === value) return;
    const startViewTransition = (document as Document & {
      startViewTransition?: (cb: () => void) => { ready: Promise<void> };
    }).startViewTransition;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (typeof startViewTransition !== 'function' || reduceMotion) {
      document.documentElement.setAttribute('data-theme', value);
      void updateSettings({ theme: value });
      return;
    }
    const x = event.clientX;
    const y = event.clientY;
    const endRadius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    const transition = startViewTransition.call(document, () => {
      document.documentElement.setAttribute('data-theme', value);
    });
    transition.ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${endRadius}px at ${x}px ${y}px)`] },
        { duration: 480, easing: 'cubic-bezier(.2,.8,.2,1)', pseudoElement: '::view-transition-new(root)' } as KeyframeAnimationOptions,
      );
    }).catch(() => undefined);
    void updateSettings({ theme: value });
  };

  const clearLocalData = async () => {
    const confirmed = window.confirm('清空所有对话并移除本地缓存？此操作不可恢复，但不影响磁盘上的代码文件。');
    if (!confirmed) return;
    const ids = runs.map((run) => run.id);
    setRuns([]);
    setSelectedRunId('');
    setNewConversationMode(true);
    setRightOpen(false);
    try {
      await Promise.all(ids.filter((id) => !id.startsWith('draft-')).map((id) => api.runs.delete(id).catch(() => undefined)));
    } catch {
      // best-effort
    }
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch {
      // ignore storage access errors
    }
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const isComposing = 'isComposing' in event.nativeEvent ? Boolean((event.nativeEvent as globalThis.KeyboardEvent).isComposing) : false;
    if (event.key !== 'Enter' || event.shiftKey || isComposing) return;
    event.preventDefault();
    void sendComposer();
  };

  const reviewFiles = selectedRun?.review?.files ?? [];
  const reviewTotals = reviewStats(reviewFiles);
  const terminalSession = selectedRun?.terminal;
  const terminalLines = terminalSession?.lines ?? draftTerminalLines;
  const terminalCwd = terminalSession?.cwd ?? selectedRun?.workspacePath ?? selectedWorkspace?.absolutePath;
  const workspaceEntries = workspaceTree.length ? workspaceTree : selectedWorkspace ? [{ name: selectedWorkspace.name, path: selectedWorkspace.absolutePath, kind: 'directory' as const }] : [];
  const latestRun = selectedRun ?? runs[0];
  const modelCalls = useMemo<DonutSegment[]>(() => {
    const palette: Record<string, string> = {
      Codex: 'var(--blue)',
      'Claude Code': 'var(--cream)',
      Gemini: 'var(--violet)',
    };
    const order = ['Codex', 'Claude Code', 'Gemini'];
    const counts: Record<string, number> = {};
    for (const run of runs) {
      for (const message of run.messages) {
        if (message.role !== 'assistant') continue;
        const label = message.actor && message.actor !== 'AI' ? message.actor : 'Codex';
        counts[label] = (counts[label] ?? 0) + 1;
      }
    }
    const labels = Object.keys(counts).sort((a, b) => {
      const ia = order.indexOf(a);
      const ib = order.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
    return labels.map((label) => ({ label, value: counts[label], color: palette[label] ?? 'var(--green)' }));
  }, [runs]);
  const clockText = useMemo(() => formatClock(clock), [clock]);
  const dashHour = clock.getHours();
  const dashGreeting = dashHour < 5 ? '夜深了' : dashHour < 11 ? '早上好' : dashHour < 13 ? '中午好' : dashHour < 18 ? '下午好' : '晚上好';
  const dashDate = clock.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' });
  const activeRunCount = runs.filter((run) => run.status === 'running' || run.status === 'reviewing' || run.status === 'initializing').length;
  const selectedMessages = useMemo(() => {
    const list = selectedRun?.messages ?? [];
    return list.slice().sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
  }, [selectedRun?.messages]);
  const selectedMessagesKey = selectedMessages.map((message) => `${message.id}:${message.status}:${message.content.length}`).join('|');
  useEffect(() => {
    setExpandedMessages((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const message of selectedMessages) {
        if (message.role === 'assistant' && message.status === 'complete' && message.content.length > 240 && !next.has(message.id)) {
          next.add(message.id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [selectedMessagesKey]);
  const awaitingReply = useMemo(() => {
    if (!selectedRun) return false;
    if (pendingReplyRunId === selectedRun.id) return true;
    const last = selectedMessages[selectedMessages.length - 1];
    if (last?.role === 'assistant' && last.status === 'streaming') return true;
    return Boolean(last && last.role === 'user' && selectedRun.status !== 'needs_approval');
  }, [selectedRun, pendingReplyRunId, selectedMessages]);
  const thinkingSeconds = thinkingStartedAt ? Math.max(0, Math.floor((clock.getTime() - thinkingStartedAt) / 1000)) : 0;

  useEffect(() => {
    setThinkingStartedAt(awaitingReply ? Date.now() : null);
  }, [awaitingReply, selectedRunId]);

  useEffect(() => {
    const updateClock = () => setClock(new Date());
    updateClock();
    const timer = window.setInterval(updateClock, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!pageError) return;
    const timer = window.setTimeout(() => setPageError(null), 3000);
    return () => window.clearTimeout(timer);
  }, [pageError]);

  useEffect(() => {
    const theme = settings?.theme ?? 'dark';
    document.documentElement.setAttribute('data-theme', theme);
  }, [settings?.theme]);

  useEffect(() => {
    if (!confirmDeleteId) return;
    const dismiss = (event: globalThis.PointerEvent) => {
      const target = event.target as Element | null;
      // Ignore clicks on the confirm panel itself or on a delete trigger,
      // otherwise the panel unmounts before the button's click registers.
      if (target?.closest?.('.conv-confirm, .conv-delete')) return;
      setConfirmDeleteId(null);
    };
    const onKey = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') setConfirmDeleteId(null); };
    window.addEventListener('pointerdown', dismiss);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', dismiss);
      window.removeEventListener('keydown', onKey);
    };
  }, [confirmDeleteId]);

  return (
    <main className={`client-window ${hasLeftPanel && leftOpen ? '' : 'left-collapsed'} ${inspectorOpen ? '' : 'right-collapsed'}`} ref={shellRef}>
      <aside className="rail" aria-label="App navigation">
        <div className="app-logo"><Command size={18} /></div>
        <button className={`rail-button ${activeView === 'sessions' ? 'active' : ''}`} aria-label="Sessions" onClick={() => { if (activeView === 'sessions') { setLeftOpen((open) => !open); } else { setActiveView('sessions'); setLeftOpen(true); } }}><MessagesSquare size={18} /></button>
        <button className={`rail-button ${activeView === 'dashboard' ? 'active' : ''}`} aria-label="Dashboard" onClick={() => setActiveView('dashboard')}><Activity size={18} /></button>
        <div className="rail-fill" />
        <button className={`rail-button ${activeView === 'settings' ? 'active' : ''}`} aria-label="Settings" onClick={() => setActiveView('settings')}><Settings size={18} /></button>
      </aside>

      <aside className="conversation-list" aria-hidden={!hasLeftPanel || !leftOpen}>
        {activeView === 'sessions' ? (
          <>
            <div className="sidebar-title">
              <div>
                <span>ai-collab</span>
                <strong>Runs</strong>
              </div>
              <button aria-label="New run" type="button" onClick={startNewConversation}><Plus size={16} /></button>
            </div>
            <div className="section-caption">对话 <i>{runs.length}</i></div>
            <div className="run-list">
              {runs.length ? runs.map((run, index) => {
                const live = run.status === 'running' || run.status === 'initializing' || run.status === 'reviewing';
                const isSelected = !newConversationMode && run.id === selectedRun?.id;
                const confirming = confirmDeleteId === run.id;
                const lastMessage = run.messages.length ? run.messages[run.messages.length - 1] : undefined;
                const preview = lastMessage
                  ? `${lastMessage.role === 'user' ? '你：' : ''}${lastMessage.content || (lastMessage.status === 'streaming' ? '正在回复…' : '')}`
                  : (run.objective ?? '');
                return (
                  <article
                    key={run.id}
                    className={`conv-card ${runStatusTone[run.status]} ${isSelected ? 'selected' : ''} ${confirming ? 'confirming' : ''}`}
                    style={{ animationDelay: `${Math.min(index, 12) * 32}ms` } as CSSProperties}
                  >
                    <button className="conversation-hitbox" type="button" onClick={() => selectRun(run.id)} aria-label={`打开 ${run.title}`}>
                      <span className="sr-only">打开对话</span>
                    </button>
                    <div className="conv-line">
                      <span className="conv-dot" aria-hidden="true" />
                      <strong>{run.title}</strong>
                      <em>{formatRelativeTime(run.updatedAt)}</em>
                      <button className="conv-delete" type="button" aria-label={`删除 ${run.title}`} onClick={(event) => {
                        event.stopPropagation();
                        setConfirmDeleteId(run.id);
                      }}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                    <p className="conv-sub">{preview}</p>
                    {live ? <span className="conv-progress" aria-hidden="true" /> : null}
                    {confirming ? (
                      <div className="conv-confirm" role="alertdialog" aria-label="确认删除" onPointerDown={(event) => event.stopPropagation()}>
                        <span>删除此对话？</span>
                        <div className="conv-confirm-actions">
                          <button type="button" className="ghost" onClick={(event) => { event.stopPropagation(); setConfirmDeleteId(null); }}>取消</button>
                          <button type="button" className="danger" onClick={(event) => { event.stopPropagation(); void deleteRun(run.id); }}>删除</button>
                        </div>
                      </div>
                    ) : null}
                  </article>
                );
              }) : (
                <div className="run-list-empty">
                  <MessagesSquare size={22} />
                  <strong>还没有对话</strong>
                  <span>点击右上角 + 选择文件夹开始</span>
                </div>
              )}
            </div>
          </>
        ) : null}
      </aside>

      <section
        className="workspace-pane"
        style={{
          '--inspector-width': inspectorOpen ? inspectorWidth + 'px' : '0px',
        } as CSSProperties}
      >
        <section className="chat-pane" style={{ '--chat-max': inspectorOpen ? '760px' : '840px' } as CSSProperties}>
          {activeView === 'sessions' ? (
            <>
              <div className="workspace-title-line">
                <h1>{newConversationMode || !selectedRun ? (selectedWorkspace?.displayPath ?? '未选择工作区') : selectedRun.workspacePath}</h1>
                <span><GitBranch size={12} /> {newConversationMode || !selectedRun ? (selectedWorkspace?.name ?? 'workspace') : selectedRun.id ?? 'run'}</span>
                <time className="workspace-clock" dateTime={clock.toISOString()}>{clockText}</time>
              </div>

              {newConversationMode || !selectedRun ? (
                <div className="message-scroll new-conversation-scroll" ref={messageScrollRef}>
                  <section className="folder-start-card runtime-stage">
                    <div className="folder-start-copy">
                      <span className="setup-kicker">Start a conversation</span>
                      <h2>先选择一个本地文件夹</h2>
                      <p>每个对话都会绑定一个真实工作目录。选中文件夹后输入第一条需求，再开始会话。</p>
                    </div>

                    <div className="folder-picker-wrap">
                      <button className="choose-folder-button" type="button" onClick={() => void pickWorkspace()} disabled={workspaceLoading}>
                        <Folder size={20} />
                        <span>{workspaceLoading ? '等待选择…' : '选择本地文件夹'}</span>
                        <em>Browse</em>
                      </button>
                      <div className="folder-picker-panel" aria-label="最近文件夹">
                        {workspaces.slice(0, settings?.recentWorkspaceLimit ?? 6).map((workspace) => (
                          <button
                            key={workspace.id}
                            className={`recent-folder ${selectedWorkspace?.id === workspace.id ? 'selected' : ''}`}
                            type="button"
                            onClick={() => chooseWorkspace(workspace)}
                          >
                            <FolderOpen size={15} />
                            <span><strong>{workspace.name}</strong><small>{workspace.displayPath}</small></span>
                            <em>{workspace.summary ?? workspace.projectKind ?? 'workspace'}</em>
                          </button>
                        ))}
                      </div>
                    </div>

                    <footer className="composer-wrap draft-composer-wrap">
                      <form className="composer" onSubmit={(event) => void sendComposer(event)}>
                      <textarea
                        value={composerText}
                        onChange={(event) => setComposerText(event.target.value)}
                        onKeyDown={handleComposerKeyDown}
                        placeholder={selectedWorkspace ? `输入你想在 ${selectedWorkspace.displayPath} 里做什么…` : '先选择一个本地文件夹'}
                        rows={2}
                      />
                        <div className="composer-actions">
                          <span>{selectedWorkspace ? selectedWorkspace.displayPath : '等待文件夹'}</span>
                          <button aria-label="Send" type="submit" disabled={!selectedWorkspace || workspaceLoading}><Send size={16} /></button>
                        </div>
                      </form>
                    </footer>
                  </section>
                </div>
              ) : (
                <>
                  <div className="message-scroll orchestrator-scroll" ref={messageScrollRef} onScroll={handleMessageScroll}>
                    {selectedRun?.messages.length ? null : (
                      <section className="run-brief runtime-stage">
                        <div className="run-brief-main">
                          <div className="run-kicker">
                            <span>Objective</span>
                            <em>{selectedRun?.id ?? 'draft'}</em>
                          </div>
                          <strong>{selectedRun?.title ?? 'Run'}</strong>
                          <p>{selectedRun?.objective ?? '选择工作区后即可开始。'}</p>
                        </div>
                        <aside>
                          <span>{pendingReplyRunId === selectedRun?.id ? '等待回复' : (selectedRun?.status ?? 'running')}</span>
                          <em>{selectedRun?.owner ?? 'owner'}</em>
                        </aside>
                      </section>
                    )}

                    {selectedRun?.approvals?.length ? (
                      <section className="approval-panel runtime-stage">
                        <div className="approval-panel-head">
                          <span>Approval Center</span>
                          <b>{selectedRun.approvals.filter((approval) => approval.status === 'pending').length} pending</b>
                        </div>
                        <div className="approval-list">
                          {selectedRun.approvals.map((approval) => (
                            <article key={approval.id} className={`approval-card ${approval.status}`}>
                              <div className="approval-card-head">
                                <strong>{approval.title}</strong>
                                <span className={`approval-risk ${approval.risk}`}>{approvalRiskLabel[approval.risk]}</span>
                              </div>
                              <p>{approval.reason}</p>
                              {approval.command ? <code>{approval.command}</code> : null}
                              <div className="approval-actions">
                                <button type="button" onClick={() => void handleApproval(approval.id, 'approve')} disabled={approval.status !== 'pending'}><Check size={14} />Approve</button>
                                <button type="button" onClick={() => void handleApproval(approval.id, 'reject')} disabled={approval.status !== 'pending'}><Ban size={14} />Reject</button>
                              </div>
                            </article>
                          ))}
                        </div>
                      </section>
                    ) : null}

                    {selectedMessages.map((message) => {
                      const runtime = messageRuntime(message);
                      return (
                      <article className={`message runtime-stage ${message.role === 'user' ? 'user-message' : 'assistant-message'} ${message.status === 'streaming' ? 'thinking-message' : ''} runtime-${runtime}`} key={message.id}>
                        <div className={`avatar ${message.role === 'user' ? 'user' : message.role === 'assistant' ? `agent ${runtime}` : 'system'}`}>
                          {message.role === 'user' ? <UserRound size={15} strokeWidth={2.2} /> : message.role === 'assistant' ? (runtime === 'claude' ? <Command size={15} strokeWidth={2.2} /> : <Sparkles size={15} strokeWidth={2.2} />) : 'S'}
                        </div>
                        <div className={`bubble ${message.role === 'user' ? 'user-bubble' : ''}`}>
                          <div className="message-head">
                            <strong>{message.role === 'assistant' && message.status === 'streaming' ? (message.actor ?? 'AI') : message.actor ?? message.role}</strong>
                            {message.role === 'assistant' && message.status === 'streaming' ? (
                              <time className="live-timer"><span aria-hidden="true" />回复中 · {formatElapsedSeconds(message.startedAt ?? message.createdAt)}</time>
                            ) : (
                              <time>{formatRelativeTime(message.createdAt)}</time>
                            )}
                          </div>
                          {message.role === 'assistant' && message.status === 'streaming' ? (
                            <MarkdownMessage text={message.content || '正在生成回复'} />
                          ) : message.role === 'assistant' && message.content.length > 240 ? (
                            <div className={`collapsible-reply ${expandedMessages.has(message.id) ? 'expanded' : ''}`}>
                              <MarkdownMessage text={message.content} />
                              <button type="button" className="reply-toggle" onClick={() => toggleMessageExpanded(message.id)}>
                                {expandedMessages.has(message.id) ? '收起' : '展开全部'}
                              </button>
                            </div>
                          ) : message.role === 'assistant' ? (
                            <MarkdownMessage text={message.content} />
                          ) : (
                            <p>{message.content}</p>
                          )}
                          {message.fileOps?.length ? (
                            <div className="file-ops">
                              {message.fileOps.map((op) => {
                                const OpIcon = op.change === 'added' ? FilePlus : op.change === 'deleted' ? FileX : FilePen;
                                const changeLabel = op.change === 'added' ? '新建' : op.change === 'deleted' ? '删除' : op.change === 'renamed' ? '重命名' : '修改';
                                return (
                                  <button
                                    key={op.path}
                                    type="button"
                                    className={`file-op ${op.change}`}
                                    title={op.path}
                                    onClick={() => { setActiveInspectorTab('review'); openInspector(); setTimeout(() => document.getElementById(diffAnchorId(op.path))?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60); }}
                                  >
                            <span className="file-op-icon"><OpIcon size={14} strokeWidth={2.1} /></span>
                                    <span className="file-op-text">
                                      <strong>{op.path.split('/').pop()}</strong>
                                      <small>{changeLabel} · {op.path}</small>
                                    </span>
                                    <em className="file-op-stat">{op.add ? <b>+{op.add}</b> : null}{op.del ? <i>-{op.del}</i> : null}</em>
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      </article>
                      );
                    })}
                    {awaitingReply ? (
                      <article className="message assistant-message thinking-message runtime-stage" role="status" aria-label="AI 正在思考">
                        <span className="avatar agent thinking" aria-hidden="true" />
                        <div className="bubble thinking-bubble">
                          <div className="message-head">
                            <strong>AI</strong>
                            <time>{thinkingSeconds >= 1 ? `已思考 ${thinkingSeconds}s` : '正在连接'}</time>
                          </div>
                          <span className="ai-thinking-text">正在整理思路</span>
                        </div>
                      </article>
                    ) : null}

                    {selectedRun?.finalResponse ? (
                      <section className="final-response runtime-stage">
                        <div className="final-response-head">
                          <span>Final response</span>
                          <b>{selectedRun.status}</b>
                        </div>
                        <p>{selectedRun.finalResponse.summary}</p>
                        <div className="final-response-grid">
                          <div>
                            <span>Remaining risks</span>
                            <ul>{selectedRun.finalResponse.remainingRisks.map((item) => <li key={item}>{item}</li>)}</ul>
                          </div>
                          <div>
                            <span>Next steps</span>
                            <ul>{selectedRun.finalResponse.nextSteps.map((item) => <li key={item}>{item}</li>)}</ul>
                          </div>
                        </div>
                      </section>
                    ) : null}
                  </div>

                  <footer className="composer-wrap">
                    <form className={`composer ${awaitingReply ? 'is-running' : ''}`} onSubmit={(event) => void sendComposer(event)}>
                      <textarea
                        value={composerText}
                        onChange={(event) => setComposerText(event.target.value)}
                        onKeyDown={handleComposerKeyDown}
                        placeholder={selectedRun ? `向 AI 说明你想在 ${selectedRun.workspacePath} 里做什么…` : '先选择一个工作区'}
                        rows={2}
                      />
                      <div className="composer-actions">
                        <span><Sparkles size={14} /> 本地会话</span>
                        <button className={awaitingReply ? 'stop-button' : ''} aria-label={awaitingReply ? 'Stop response' : 'Send'} type="submit" onClick={handleComposerButton}>
                          {awaitingReply ? <Square size={14} fill="currentColor" /> : <Send size={16} />}
                        </button>
                      </div>
                    </form>
                  </footer>
                </>
              )}
            </>
          ) : (
            <div className="content-page">
              {activeView === 'dashboard' ? (
                <>
                  <div className="dash">
                    <header className="dash-hero">
                      <div className="dash-hero-main">
                        <span className="dash-hero-kicker"><Activity size={13} /> 工作台总览 · {dashDate}</span>
                        <h1 className="dash-hero-title">{dashGreeting}</h1>
                        <p className="dash-hero-sub">
                          {activeRunCount > 0
                            ? <>当前有 <b>{activeRunCount}</b> 个会话正在进行，已累计 <b>{dashboardSummary?.messages ?? 0}</b> 条消息。</>
                            : <>暂无进行中的会话，已累计 <b>{dashboardSummary?.messages ?? 0}</b> 条消息。开始一段新对话吧。</>}
                        </p>
                      </div>
                      <div className="dash-stat-rail">
                        {([
                          ['会话', MessagesSquare, dashboardSummary?.sessions ?? 0, 'cream'],
                          ['消息', Layers, dashboardSummary?.messages ?? 0, 'blue'],
                          ['工作区', FolderOpen, workspaces.length, 'green'],
                        ] as const).map(([label, Icon, value, tone], index) => (
                          <div className={`dash-stat tone-${tone}`} key={label} style={{ animationDelay: `${120 + index * 70}ms` } as CSSProperties}>
                            <span className="dash-stat-icon"><Icon size={15} /></span>
                            <strong><CountUp value={value} /></strong>
                            <em>{label}</em>
                          </div>
                        ))}
                      </div>
                    </header>

                    <div className="dash-grid">
                      <section className="dash-card dash-activity" style={{ animationDelay: '240ms' } as CSSProperties}>
                        <div className="dash-card-head">
                          <div><span><TrendingUp size={14} /> 活动趋势</span><strong>近 {dashboardActivity.length} 天</strong></div>
                          <div className="dash-legend">
                            {ACTIVITY_SERIES.map((series) => (
                              <span key={series.key}><i style={{ background: series.color }} />{series.label}</span>
                            ))}
                          </div>
                        </div>
                        <ActivityChart data={dashboardActivity} />
                      </section>

                      <section className="dash-card dash-runtime" style={{ animationDelay: '300ms' } as CSSProperties}>
                        <div className="dash-card-head"><div><span><Cpu size={14} /> 模型调用</span><strong>按 Agent 统计</strong></div></div>
                        {modelCalls.length ? <DonutChart segments={modelCalls} /> : <p className="dash-empty">还没有模型调用记录</p>}
                      </section>

                      <section className="dash-card dash-recent" style={{ animationDelay: '360ms' } as CSSProperties}>
                        <div className="dash-card-head"><div><span><Clock size={14} /> 最近会话</span><strong>{runs.length}</strong></div></div>
                        <div className="dash-recent-list">
                          {runs.length ? runs.slice(0, 6).map((run) => (
                            <button key={run.id} type="button" className={`dash-recent-item ${runStatusTone[run.status]}`} onClick={() => selectRun(run.id)}>
                              <span className="dash-recent-dot" />
                              <span className="dash-recent-title">{run.title}</span>
                              <em>{formatRelativeTime(run.updatedAt)}</em>
                            </button>
                          )) : (
                            <p className="dash-empty">还没有会话记录</p>
                          )}
                        </div>
                      </section>
                    </div>
                  </div>
                </>
              ) : (
                <div className="settings-layout">
                  <div className="content-page-head settings-head"><Settings size={20} /><span>Settings</span><strong>偏好设置</strong></div>

                  <section className="settings-section">
                    <header className="settings-section-head">
                      <strong>外观</strong>
                      <span>切换界面整体配色</span>
                    </header>
                    <div className="settings-rows">
                      <div className="settings-row">
                        <div className="settings-row-label">
                          <strong>主题</strong>
                          <span>深色适合长时间编码，浅色更明亮清晰</span>
                        </div>
                        <div className="segmented" role="group" aria-label="主题">
                          {([['dark', '深色'], ['light', '浅色']] as const).map(([value, label]) => (
                            <button
                              key={value}
                              type="button"
                              className={(settings?.theme ?? 'dark') === value ? 'active' : ''}
                              onClick={(event) => toggleTheme(value, event)}
                            >{label}</button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </section>

                  <section className="settings-section">
                    <header className="settings-section-head">
                      <strong>行为</strong>
                      <span>对话与检查器的默认交互</span>
                    </header>
                    <div className="settings-rows">
                      <div className="settings-row">
                        <div className="settings-row-label">
                          <strong>按任务自动选择模型</strong>
                          <span>根据消息意图在 Codex / Claude Code / Gemini 间自动路由；关闭则固定使用当前控制器</span>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={settings?.autoRoute ?? true}
                          className={`switch ${settings?.autoRoute ?? true ? 'on' : ''}`}
                          onClick={() => void updateSettings({ autoRoute: !(settings?.autoRoute ?? true) })}
                        ><i /></button>
                      </div>
                      <div className="settings-row">
                        <div className="settings-row-label">
                          <strong>自动展开检查器</strong>
                          <span>打开对话时同时显示 Review / Terminal 面板</span>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={settings?.autoOpenInspector ?? true}
                          className={`switch ${settings?.autoOpenInspector ?? true ? 'on' : ''}`}
                          onClick={() => void updateSettings({ autoOpenInspector: !(settings?.autoOpenInspector ?? true) })}
                        ><i /></button>
                      </div>
                      <div className="settings-row">
                        <div className="settings-row-label">
                          <strong>最近文件夹数量</strong>
                          <span>新对话页面展示的历史工作区上限</span>
                        </div>
                        <div className="stepper">
                          <button type="button" aria-label="减少" onClick={() => void updateSettings({ recentWorkspaceLimit: clampNumber((settings?.recentWorkspaceLimit ?? 6) - 1, 3, 12) })}>−</button>
                          <strong>{settings?.recentWorkspaceLimit ?? 6}</strong>
                          <button type="button" aria-label="增加" onClick={() => void updateSettings({ recentWorkspaceLimit: clampNumber((settings?.recentWorkspaceLimit ?? 6) + 1, 3, 12) })}>+</button>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section className="settings-section">
                    <header className="settings-section-head">
                      <strong>数据</strong>
                      <span>清理对话与本地缓存</span>
                    </header>
                    <div className="settings-rows">
                      <div className="settings-row">
                        <div className="settings-row-label">
                          <strong>清空所有对话</strong>
                          <span>删除全部会话记录并清除本地缓存，不影响磁盘上的代码</span>
                        </div>
                        <button type="button" className="settings-btn danger" onClick={() => void clearLocalData()}>清空</button>
                      </div>
                    </div>
                  </section>
                </div>
              )}
            </div>
          )}
        </section>

        {canOpenInspector ? (
          <button
            aria-label="Toggle inspector"
            type="button"
            className={`floating-inspector-toggle ${inspectorOpen ? 'active' : ''}`}
            onClick={toggleInspector}
          >
            <PanelRight size={15} />
          </button>
        ) : null}

        {canOpenInspector ? (
          <aside className="inspector-pane" aria-hidden={!inspectorOpen}>
            <div className="resize-handle" onPointerDown={(event) => {
              event.preventDefault();
              const startX = event.clientX;
              const startWidth = inspectorWidth;
              const handleMove = (moveEvent: globalThis.PointerEvent) => {
                const nextWidth = clampNumber(startWidth + startX - moveEvent.clientX, MIN_INSPECTOR_WIDTH, MAX_INSPECTOR_WIDTH);
                setInspectorWidth(nextWidth);
              };
              const handleUp = (upEvent: globalThis.PointerEvent) => {
                const nextWidth = clampNumber(startWidth + startX - upEvent.clientX, MIN_INSPECTOR_WIDTH, MAX_INSPECTOR_WIDTH);
                setInspectorWidth(nextWidth);
                storeInspectorWidth(nextWidth);
                window.removeEventListener('pointermove', handleMove);
                window.removeEventListener('pointerup', handleUp);
              };
              window.addEventListener('pointermove', handleMove);
              window.addEventListener('pointerup', handleUp);
            }} />

            <div className="insp-header">
              <div className="insp-tabs" role="tablist">
                {inspectorTabs.map((tab) => {
                  const Icon = tab.icon;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={effectiveTab === tab.id}
                      className={`insp-tab ${effectiveTab === tab.id ? 'active' : ''}`}
                      onClick={() => { setActiveInspectorTab(tab.id); openInspector(); }}
                    >
                      <Icon size={14} />
                      <span>{tab.label}</span>
                    </button>
                  );
                })}
              </div>

              {showReviewPanel ? (
                <div className="insp-subbar">
                  <div className="insp-title">
                    <strong className="diff-wordmark"><GitBranch size={13} />DIFF</strong>
                    <span>{selectedRun?.review?.summary ?? '对照 HEAD 的未提交改动'}</span>
                  </div>
                  <div className="insp-tools">
                    <span className="diff-stat"><b>+{reviewTotals.add}</b><i>-{reviewTotals.del}</i></span>
                    <button
                      type="button"
                      className={`insp-icon-btn ${diffFilesOpen ? 'active' : ''}`}
                      aria-label={diffFilesOpen ? '隐藏文件目录' : '显示文件目录'}
                      title={diffFilesOpen ? '隐藏文件目录' : '显示文件目录'}
                      onClick={() => setDiffFilesOpen((open) => !open)}
                    >
                      <Folder size={15} />
                    </button>
                  </div>
                </div>
              ) : null}
            </div>

            {showReviewPanel ? (
              <div className="inspector-scroll diff-review">
                <div className={`diff-layout ${diffFilesOpen ? '' : 'files-collapsed'}`} style={{ '--file-tree-width': diffFilesOpen ? `${fileTreeWidth}px` : '0px' } as CSSProperties}>
                  <section className="diff-preview">
                    {reviewFiles.length ? reviewFiles.map((file) => {
                      const collapsed = Boolean(collapsedDiffFiles[file.path]);
                      const rows: { line: DiffFile['hunks'][number]['lines'][number]; key: string }[] = [];
                      let total = 0;
                      file.hunks.forEach((hunk, hunkIndex) => {
                        if (total >= 80) return;
                        for (const line of hunk.lines) {
                          if (total >= 80) break;
                          rows.push({ line, key: `${file.path}-${hunkIndex}-${total}` });
                          total += 1;
                        }
                      });
                      const fileName = file.path.split('/').pop() ?? file.path;
                      return (
                        <article id={diffAnchorId(file.path)} className={`diff-file ${file.status} ${collapsed ? 'collapsed' : ''}`} key={file.path}>
                          <div className="diff-file-head">
                            <button className="diff-file-toggle" type="button" aria-label={collapsed ? `展开 ${file.path}` : `折叠 ${file.path}`} aria-expanded={!collapsed} onClick={() => setCollapsedDiffFiles((current) => ({ ...current, [file.path]: !current[file.path] }))}>
                              <ChevronDown size={14} />
                            </button>
                            <span className="diff-file-name"><FileText size={13} /> <strong>{fileName}</strong><small>{file.path}</small></span>
                            <em><b>+{file.add}</b><i>-{file.del}</i></em>
                          </div>
                          <div className="diff-file-body">
                            <pre>
                              {rows.map((row, index) => (
                                <div className={`diff-line ${row.line.type === 'add' ? 'add' : row.line.type === 'del' ? 'del' : ''}`} key={row.key}>
                                  <span>{row.line.newLine ?? row.line.oldLine ?? ''}</span>
                                  <code>{row.line.content || ' '}</code>
                                </div>
                              ))}
                              {total >= 80 ? <div className="diff-line diff-line-more"><span /><code>… 更多改动请在编辑器中查看</code></div> : null}
                            </pre>
                          </div>
                        </article>
                      );
                    }) : (
                      <article className="diff-file diff-file-empty">
                        <div className="diff-empty">
                          <CircleAlert size={18} />
                          <strong>{selectedRun?.review?.summary ?? '暂无改动'}</strong>
                          <span>对工作区文件做出修改后，会在这里看到 diff</span>
                        </div>
                      </article>
                    )}
                  </section>

                  {diffFilesOpen ? <div className="file-splitter" onPointerDown={(event) => {
                    event.preventDefault();
                    const startX = event.clientX;
                    const startWidth = fileTreeWidth;
                    const handleMove = (moveEvent: globalThis.PointerEvent) => {
                      setFileTreeWidth(clampNumber(startWidth + startX - moveEvent.clientX, 120, 260));
                    };
                    const handleUp = (upEvent: globalThis.PointerEvent) => {
                      setFileTreeWidth(clampNumber(startWidth + startX - upEvent.clientX, 120, 260));
                      window.removeEventListener('pointermove', handleMove);
                      window.removeEventListener('pointerup', handleUp);
                    };
                    window.addEventListener('pointermove', handleMove);
                    window.addEventListener('pointerup', handleUp);
                  }} /> : null}

                  <section className="file-tree" aria-hidden={!diffFilesOpen}>
                    <div className="file-tree-head">{reviewFiles.length} 个文件</div>
                    <div className="file-tree-list">
                      {reviewFiles.map((file) => (
                        <button
                          key={file.path}
                          type="button"
                          className={`file-row ${file.status}`}
                          title={file.path}
                          onClick={() => document.getElementById(diffAnchorId(file.path))?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                        >
                          <span className="file-row-dot" aria-hidden="true" />
                          <span className="file-row-name">{file.path.split('/').pop()}</span>
                        </button>
                      ))}
                    </div>
                  </section>
                </div>

              </div>
            ) : (
              <div className="terminal-panel">
                <div className="terminal-head">
                  <span><TerminalSquare size={14} /> interactive shell</span>
                  <em title={terminalCwd}>{terminalSession?.shell ?? 'zsh'} · {shortCwd(terminalCwd)}</em>
                </div>
                <div className="terminal-body" onClick={() => terminalInputRef.current?.focus()}>
                  {terminalLines.map((line) => (
                    <p key={line.id} className={line.kind === 'error' ? 'muted' : line.kind === 'status' ? 'ok' : ''}>
                      {line.kind === 'input' ? <><span className="term-cwd">{shortCwd(terminalCwd)}</span> <b>$</b> {stripPromptPrefix(line.text)}</> : line.text}
                    </p>
                  ))}
                  <form className="terminal-prompt-line" onSubmit={(event) => void handleTerminalSubmit(event)}>
                    <span className="term-cwd">{shortCwd(terminalCwd)}</span>
                    <span className="term-sigil">$</span>
                    <input
                      ref={terminalInputRef}
                      className="terminal-input-shell"
                      value={terminalCommand}
                      onChange={(event) => setTerminalCommand(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') void handleTerminalSubmit(event);
                      }}
                      aria-label="Terminal command"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </form>
                </div>
              </div>
            )}
          </aside>
        ) : null}
      </section>

      {pageError ? (
        <div className="error-toast">
          <CircleAlert size={14} />
          <span>{pageError}</span>
          <button type="button" onClick={() => setPageError(null)}><X size={12} /></button>
        </div>
      ) : null}
    </main>
  );
}
