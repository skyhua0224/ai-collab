import { createServer } from 'node:http';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import {
  buildActivitySeries,
  buildReviewProjection,
  buildWorkspaceFolder,
  computeDashboardSummary,
  createInitialState,
  expandHome,
  isDirectory,
  listTree,
  loadJson,
  nowIso,
  saveJson,
  uid,
} from './state.mjs';

const execFileAsync = promisify(execFile);
const PORT = Number(process.env.PORT ?? 8787);
const DEV_MODE = process.env.AI_COLLAB_DEV_MODE === '1';
const webRoot = process.cwd();
const persistPath = path.join(webRoot, '.ai-collab-state.json');
const staticRoot = path.join(webRoot, 'dist');

const initialState = await createInitialState({ persisted: await loadJson(persistPath, null) });
const state = {
  settings: initialState.settings,
  workspaces: initialState.workspaces,
  runs: initialState.runs,
};

const runSubscribers = new Map();
const terminalSubscribers = new Map();
const terminalSessions = new Map();

function isLocalOrigin(origin) {
  return typeof origin === 'string' && /^(https?:\/\/(localhost|127\.0\.0\.1|::1)(:\d+)?)(\/|$)/i.test(origin);
}

function applyCors(req, res) {
  const origin = req.headers.origin;
  if (!isLocalOrigin(origin)) return;
  res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PATCH,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With');
  res.setHeader('Access-Control-Max-Age', '86400');
}

for (const run of state.runs) {
  if (run.terminal) terminalSessions.set(run.terminal.sessionId, run.terminal);
}

function sendJson(req, res, code, payload) {
  applyCors(req, res);
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(payload));
}

function sendSseHeaders(req, res) {
  applyCors(req, res);
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write('\n');
}

function writeEvent(res, eventName, payload) {
  res.write(`event: ${eventName}\n`);
  res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

function addSubscriber(map, key, res) {
  if (!map.has(key)) map.set(key, new Set());
  map.get(key).add(res);
  res.on('close', () => map.get(key)?.delete(res));
}

function broadcastRun(runId, eventName, payload) {
  for (const res of runSubscribers.get(runId) ?? []) writeEvent(res, eventName, payload);
}

function broadcastTerminal(sessionId, eventName, payload) {
  for (const res of terminalSubscribers.get(sessionId) ?? []) writeEvent(res, eventName, payload);
}

async function persist() {
  await saveJson(persistPath, state);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

function findRun(runId) {
  return state.runs.find((run) => run.id === runId);
}

function removeRun(runId) {
  const index = state.runs.findIndex((run) => run.id === runId);
  if (index === -1) return null;
  const [removed] = state.runs.splice(index, 1);
  if (removed?.terminal?.sessionId) terminalSessions.delete(removed.terminal.sessionId);
  for (const map of [runSubscribers, terminalSubscribers]) {
    const subscribers = map.get(runId);
    if (!subscribers) continue;
    for (const res of subscribers) {
      try {
        res.end();
      } catch {
        // ignore
      }
    }
    map.delete(runId);
  }
  return removed ?? null;
}

function findWorkspace(workspaceId) {
  return state.workspaces.find((workspace) => workspace.id === workspaceId);
}

function riskNeedsApproval(text) {
  return /npm install|pnpm add|yarn add|rm -rf|删除|install|写入|覆盖|deploy|push|sudo|chmod 777|危险/i.test(text);
}

function deriveTitle(objective) {
  const cleaned = objective.trim().replace(/\s+/g, ' ');
  return cleaned.length > 24 ? `${cleaned.slice(0, 24)}...` : cleaned;
}

async function openWorkspace(rawPath) {
  const absolutePath = path.resolve(expandHome(String(rawPath ?? '').trim()));
  if (!await isDirectory(absolutePath)) throw new Error('Workspace path does not exist or is not a directory.');
  const existing = state.workspaces.find((workspace) => workspace.absolutePath === absolutePath);
  const workspace = existing ? { ...existing, lastOpenedAt: nowIso() } : await buildWorkspaceFolder(absolutePath);
  state.workspaces = [workspace, ...state.workspaces.filter((item) => item.id !== workspace.id && item.absolutePath !== workspace.absolutePath)];
  await persist();
  return workspace;
}

async function pickLocalFolder() {
  if (process.platform !== 'darwin') throw new Error('当前只支持 macOS 原生文件夹选择。');
  try {
    const { stdout } = await execFileAsync(
      'osascript',
      ['-e', 'POSIX path of (choose folder with prompt "选择工作区文件夹")'],
      { timeout: 120_000 },
    );
    return stdout.trim().replace(/\/$/, '');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (/User canceled|User cancelled|cancel/i.test(message)) return null;
    throw error;
  }
}

function createRun(workspace, objective, mode = 'chat') {
  const runId = uid('run');
  const now = nowIso();
  return {
    id: runId,
    title: deriveTitle(objective),
    subtitle: mode === 'chat' ? '聊天驱动会话' : `模式：${mode}`,
    status: 'running',
    owner: 'Codex',
    objective,
    workspaceId: workspace.id,
    workspacePath: workspace.absolutePath,
    createdAt: now,
    updatedAt: now,
    durationMs: 0,
    health: 12,
    agents: [
      { id: uid('ag'), role: 'Orchestrator', name: 'Codex', model: 'GPT-5.5', runtime: 'codex', status: 'active', progress: 12, focus: '读取需求', currentStep: '等待执行', startedAt: now },
    ],
    timeline: [
      { id: uid('tl'), runId, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), title: 'Run 创建', detail: '已根据首条需求创建会话。', type: 'system', actor: 'ai-collab' },
    ],
    messages: [
      { id: uid('msg'), runId, role: 'user', actor: 'You', content: objective, createdAt: now, status: 'complete' },
    ],
    approvals: [],
    terminal: {
      sessionId: uid('term'),
      runId,
      cwd: workspace.absolutePath,
      shell: process.platform === 'win32' ? 'powershell' : 'zsh',
      status: 'idle',
      lines: [],
    },
  };
}

function ensureWorkspaceRunShape(run) {
  const workspace = findWorkspace(run.workspaceId);
  if (!workspace) return run;
  run.workspacePath = workspace.absolutePath;
  if (!run.review || !run.review.files) {
    run.review = workspace.git?.gitRoot ? undefined : { files: [], summary: '暂无 diff。' };
  }
  if (!run.terminal) {
    run.terminal = {
      sessionId: uid('term'),
      runId: run.id,
      cwd: workspace.absolutePath,
      shell: process.platform === 'win32' ? 'zsh' : 'zsh',
      status: 'idle',
      lines: [],
    };
  }
  return run;
}

function streamAssistantReply(run, text) {
  const reply = riskNeedsApproval(text)
    ? `收到。这个请求包含高风险动作，我会先生成审批项，再继续处理 ${run.workspacePath}。`
    : `收到。我会基于 ${run.workspacePath} 处理这个需求，并把状态同步到当前会话。`;
  const message = { id: uid('msg'), runId: run.id, role: 'assistant', actor: 'Codex', content: '', createdAt: nowIso(), status: 'streaming' };
  run.messages.push(message);
  const tokens = reply.split(/(\s+)/).filter(Boolean);
  let index = 0;
  const pump = () => {
    if (index >= tokens.length) {
      message.status = 'complete';
      message.content = reply;
      run.updatedAt = nowIso();
      run.health = Math.max(run.health ?? 0, 28);
      broadcastRun(run.id, 'message.completed', { type: 'message.completed', message });
      broadcastRun(run.id, 'run.updated', { type: 'run.updated', run });
      persist();
      return;
    }
    const delta = tokens[index++];
    message.content += delta;
    broadcastRun(run.id, 'message.delta', { type: 'message.delta', messageId: message.id, delta, runId: run.id });
    setTimeout(pump, 30);
  };
  // Brief "thinking" pause before the first token so the UI can show a thinking state.
  setTimeout(pump, 700);
}

async function executeTerminalCommand(sessionId, command) {
  const session = terminalSessions.get(sessionId);
  if (!session || session.status === 'closed') return session;
  const run = findRun(session.runId);
  const append = (text, kind) => {
    for (const chunk of String(text).split(/\r?\n/).filter(Boolean)) {
      const line = { id: uid('line'), text: chunk, kind, createdAt: nowIso() };
      session.lines.push(line);
      broadcastTerminal(sessionId, 'terminal.output', { type: 'terminal.output', sessionId, line, runId: session.runId });
      broadcastRun(session.runId, 'terminal.output', { type: 'terminal.output', sessionId, line, runId: session.runId });
    }
  };
  append(`$ ${command}`, 'input');
  if (riskNeedsApproval(command) && run) {
    const approval = { id: uid('ap'), runId: run.id, title: `审批：${command.slice(0, 32)}`, risk: 'high', command, reason: '该命令包含高风险操作，需要确认。', status: 'pending', requestedBy: 'Policy Engine', createdAt: nowIso(), policyHint: 'terminal_command' };
    run.status = 'needs_approval';
    run.approvals.unshift(approval);
    broadcastRun(run.id, 'approval.created', { type: 'approval.created', approval });
    await persist();
    return session;
  }
  session.status = 'running';
  const child = spawn(command, { cwd: session.cwd, shell: true, env: process.env });
  child.stdout.on('data', (buf) => append(buf, 'output'));
  child.stderr.on('data', (buf) => append(buf, 'error'));
  child.on('close', async (code) => {
    session.status = 'idle';
    append(`command exited with code ${code}`, 'status');
    if (run) {
      run.terminal = session;
      run.updatedAt = nowIso();
      const workspace = findWorkspace(run.workspaceId);
      if (workspace?.git?.gitRoot) run.review = await buildReviewProjection(workspace.git.gitRoot);
      broadcastRun(run.id, 'run.updated', { type: 'run.updated', run });
    }
    await persist();
  });
  await persist();
  return session;
}

async function handleApi(req, res, url) {
  if (req.method === 'OPTIONS') {
    applyCors(req, res);
    res.statusCode = 204;
    res.end();
    return true;
  }
  if (req.method === 'GET' && url.pathname === '/api/ping') return sendJson(req, res, 200, { ok: true, time: nowIso() });
  if (req.method === 'GET' && url.pathname === '/api/workspaces/recent') return sendJson(req, res, 200, state.workspaces);
  if (req.method === 'POST' && url.pathname === '/api/workspaces/pick') {
    const picked = await pickLocalFolder();
    if (!picked) return sendJson(req, res, 200, { canceled: true });
    return sendJson(req, res, 200, { canceled: false, workspace: await openWorkspace(picked) });
  }
  if (req.method === 'POST' && url.pathname === '/api/workspaces/open') {
    try {
      return sendJson(req, res, 200, await openWorkspace((await readBody(req)).path));
    } catch (error) {
      return sendJson(req, res, 400, { message: error instanceof Error ? error.message : 'Invalid workspace path.' });
    }
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/workspaces/') && url.pathname.endsWith('/tree')) {
    const workspace = findWorkspace(url.pathname.split('/')[3]);
    if (!workspace) return sendJson(req, res, 404, { message: 'Workspace not found' });
    const targetPath = url.searchParams.get('path') ? path.resolve(workspace.absolutePath, url.searchParams.get('path')) : workspace.absolutePath;
    return sendJson(req, res, 200, { path: targetPath, entries: await listTree(targetPath, 2) });
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/workspaces/') && url.pathname.endsWith('/summary')) {
    const workspace = findWorkspace(url.pathname.split('/')[3]);
    return workspace ? sendJson(req, res, 200, workspace) : sendJson(req, res, 404, { message: 'Workspace not found' });
  }
  if (req.method === 'GET' && url.pathname === '/api/runs') return sendJson(req, res, 200, state.runs);
  if (req.method === 'POST' && url.pathname === '/api/runs') {
    const body = await readBody(req);
    const workspace = findWorkspace(body.workspaceId);
    const objective = String(body.objective ?? '').trim();
    if (!workspace) return sendJson(req, res, 404, { message: 'Workspace not found' });
    if (!objective) return sendJson(req, res, 400, { message: 'Objective is required.' });
    const run = createRun(workspace, objective, String(body.mode ?? 'chat'));
    if (workspace.git?.gitRoot) run.review = await buildReviewProjection(workspace.git.gitRoot);
    terminalSessions.set(run.terminal.sessionId, run.terminal);
    state.runs.unshift(run);
    await persist();
    streamAssistantReply(run, objective);
    return sendJson(req, res, 200, run);
  }
  if (req.method === 'DELETE' && url.pathname.startsWith('/api/runs/')) {
    const runId = url.pathname.split('/')[3];
    const removed = removeRun(runId);
    if (!removed) return sendJson(req, res, 404, { message: 'Run not found' });
    await persist();
    return sendJson(req, res, 200, { ok: true });
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/runs/') && url.pathname.endsWith('/events')) {
    const run = findRun(url.pathname.split('/')[3]);
    if (!run) return sendJson(req, res, 404, { message: 'Run not found' });
    ensureWorkspaceRunShape(run);
    sendSseHeaders(req, res);
    addSubscriber(runSubscribers, run.id, res);
    writeEvent(res, 'run.updated', { type: 'run.updated', run });
    return true;
  }
  if (req.method === 'POST' && url.pathname.startsWith('/api/runs/') && url.pathname.endsWith('/messages')) {
    const run = findRun(url.pathname.split('/')[3]);
    if (!run) return sendJson(req, res, 404, { message: 'Run not found' });
    ensureWorkspaceRunShape(run);
    const content = String((await readBody(req)).content ?? '').trim();
    if (!content) return sendJson(req, res, 400, { message: 'Message content is required.' });
    const message = { id: uid('msg'), runId: run.id, role: 'user', actor: 'You', content, createdAt: nowIso(), status: 'complete' };
    run.messages.push(message);
    run.timeline.unshift({ id: uid('tl'), runId: run.id, time: 'now', title: '收到用户消息', detail: content, type: 'system', actor: 'ai-collab' });
    if (riskNeedsApproval(content)) {
      const approval = { id: uid('ap'), runId: run.id, title: '用户消息包含高风险意图', risk: 'high', command: content, reason: '检测到可能需要危险动作，先走审批。', status: 'pending', requestedBy: 'Policy Engine', createdAt: nowIso(), policyHint: 'message_risk' };
      run.status = 'needs_approval';
      run.approvals.unshift(approval);
      broadcastRun(run.id, 'approval.created', { type: 'approval.created', approval });
    }
    run.updatedAt = nowIso();
    await persist();
    broadcastRun(run.id, 'run.updated', { type: 'run.updated', run });
    streamAssistantReply(run, content);
    return sendJson(req, res, 200, { message, run });
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/runs/')) {
    const run = findRun(url.pathname.split('/')[3]);
    if (!run) return sendJson(req, res, 404, { message: 'Run not found' });
    ensureWorkspaceRunShape(run);
    if (url.pathname.endsWith('/messages')) return sendJson(req, res, 200, run.messages);
    if (url.pathname.endsWith('/approvals')) return sendJson(req, res, 200, run.approvals);
    if (url.pathname.endsWith('/final-response')) return sendJson(req, res, 200, run.finalResponse);
    if (url.pathname.endsWith('/review') || url.pathname.endsWith('/diff')) {
      const workspace = findWorkspace(run.workspaceId);
      if (workspace?.git?.gitRoot) run.review = await buildReviewProjection(workspace.git.gitRoot);
      return sendJson(req, res, 200, run.review ?? { files: [], summary: '暂无 diff。' });
    }
    return sendJson(req, res, 200, run);
  }
  if (req.method === 'POST' && url.pathname.startsWith('/api/runs/') && url.pathname.endsWith('/terminal')) {
    const run = findRun(url.pathname.split('/')[3]);
    if (!run) return sendJson(req, res, 404, { message: 'Run not found' });
    ensureWorkspaceRunShape(run);
    const body = await readBody(req);
    const session = { sessionId: uid('term'), runId: run.id, cwd: body.cwd ? path.resolve(expandHome(String(body.cwd))) : run.workspacePath, shell: body.shell ?? 'zsh', status: 'idle', lines: [] };
    terminalSessions.set(session.sessionId, session);
    run.terminal = session;
    await persist();
    return sendJson(req, res, 200, session);
  }
  if (req.method === 'POST' && url.pathname.startsWith('/api/terminal/') && url.pathname.endsWith('/input')) {
    const session = await executeTerminalCommand(url.pathname.split('/')[3], String((await readBody(req)).command ?? '').trim());
    return session ? sendJson(req, res, 200, session) : sendJson(req, res, 404, { message: 'Terminal session not found' });
  }
  if (req.method === 'POST' && url.pathname.startsWith('/api/terminal/') && url.pathname.endsWith('/kill')) {
    const session = terminalSessions.get(url.pathname.split('/')[3]);
    if (!session) return sendJson(req, res, 404, { message: 'Terminal session not found' });
    session.status = 'closed';
    await persist();
    return sendJson(req, res, 200, session);
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/terminal/') && url.pathname.endsWith('/events')) {
    const session = terminalSessions.get(url.pathname.split('/')[3]);
    if (!session) return sendJson(req, res, 404, { message: 'Terminal session not found' });
    sendSseHeaders(req, res);
    addSubscriber(terminalSubscribers, session.sessionId, res);
    return true;
  }
  if (req.method === 'POST' && url.pathname.startsWith('/api/approvals/')) {
    const approvalId = url.pathname.split('/')[3];
    const approved = url.pathname.endsWith('/approve');
    for (const run of state.runs) {
      const approval = run.approvals.find((item) => item.id === approvalId);
      if (!approval) continue;
      ensureWorkspaceRunShape(run);
      approval.status = approved ? 'approved' : 'rejected';
      approval.resolvedAt = nowIso();
      run.status = approved ? 'running' : 'paused';
      await persist();
      broadcastRun(run.id, 'approval.updated', { type: 'approval.updated', approval });
      broadcastRun(run.id, 'run.updated', { type: 'run.updated', run });
      return sendJson(req, res, 200, approval);
    }
    return sendJson(req, res, 404, { message: 'Approval not found' });
  }
  if (req.method === 'GET' && url.pathname === '/api/dashboard/summary') return sendJson(req, res, 200, computeDashboardSummary(state.runs));
  if (req.method === 'GET' && url.pathname === '/api/dashboard/activity') return sendJson(req, res, 200, buildActivitySeries(Number(url.searchParams.get('days') ?? 18)));
  if (req.method === 'GET' && url.pathname === '/api/settings') return sendJson(req, res, 200, state.settings);
  if (req.method === 'PATCH' && url.pathname === '/api/settings') {
    Object.assign(state.settings, await readBody(req));
    await persist();
    return sendJson(req, res, 200, state.settings);
  }
  return false;
}

async function serveStatic(req, res, url) {
  if (DEV_MODE) return false;
  const target = path.join(staticRoot, url.pathname === '/' ? '/index.html' : url.pathname);
  try {
    const stat = await fs.stat(target);
    const filePath = stat.isDirectory() ? path.join(target, 'index.html') : target;
    res.statusCode = 200;
    res.end(await fs.readFile(filePath));
    return true;
  } catch {
    if (!url.pathname.includes('.')) {
      try {
        res.statusCode = 200;
        res.end(await fs.readFile(path.join(staticRoot, 'index.html')));
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? '/', `http://${req.headers.host ?? '127.0.0.1'}`);
    if (url.pathname.startsWith('/api/')) {
      const handled = await handleApi(req, res, url);
      if (!handled && !res.writableEnded) sendJson(req, res, 404, { message: 'Not found' });
      return;
    }
    if (await serveStatic(req, res, url)) return;
    sendJson(req, res, 404, { message: 'Not found' });
  } catch (error) {
    console.error(error);
    if (!res.writableEnded) sendJson(req, res, 500, { message: error instanceof Error ? error.message : 'Internal error' });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`ai-collab backend listening on http://127.0.0.1:${PORT}`);
});
