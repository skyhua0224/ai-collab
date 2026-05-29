import { promises as fs } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import crypto from 'node:crypto';

const execFileAsync = promisify(execFile);
const ignoredNames = new Set(['node_modules', '.git', 'dist', '.cache', '.temp']);

export async function loadJson(filePath, fallback) {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'));
  } catch {
    return fallback;
  }
}

export async function saveJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

export function nowIso() {
  return new Date().toISOString();
}

export function uid(prefix) {
  return `${prefix}_${crypto.randomUUID().slice(0, 8)}`;
}

export function expandHome(input) {
  if (!input) return input;
  if (input === '~') return os.homedir();
  if (input.startsWith('~/')) return path.join(os.homedir(), input.slice(2));
  return input;
}

export function displayPath(input) {
  const home = os.homedir();
  if (input === home) return '~';
  if (input?.startsWith(`${home}${path.sep}`)) return `~${input.slice(home.length)}`;
  return input;
}

export async function isDirectory(target) {
  try {
    return (await fs.stat(target)).isDirectory();
  } catch {
    return false;
  }
}

async function pathExists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

async function findGitRoot(startPath) {
  let current = path.resolve(startPath);
  while (true) {
    if (await pathExists(path.join(current, '.git'))) return current;
    const parent = path.dirname(current);
    if (parent === current) return null;
    current = parent;
  }
}

export async function readGitInfo(targetPath) {
  const gitRoot = await findGitRoot(targetPath);
  if (!gitRoot) return { isRepo: false };

  const [branch, dirty, remote] = await Promise.allSettled([
    execFileAsync('git', ['-C', gitRoot, 'rev-parse', '--abbrev-ref', 'HEAD']),
    execFileAsync('git', ['-C', gitRoot, 'status', '--porcelain']),
    execFileAsync('git', ['-C', gitRoot, 'remote', 'get-url', 'origin']),
  ]);

  return {
    isRepo: true,
    branch: branch.status === 'fulfilled' ? branch.value.stdout.trim() : undefined,
    dirty: dirty.status === 'fulfilled' ? dirty.value.stdout.trim().length > 0 : undefined,
    remote: remote.status === 'fulfilled' ? remote.value.stdout.trim() : undefined,
    gitRoot,
  };
}

async function detectProjectKind(targetPath) {
  const checks = [
    ['rust', 'Cargo.toml'],
    ['node', 'package.json'],
    ['python', 'pyproject.toml'],
    ['docs', 'README.md'],
  ];
  for (const [kind, fileName] of checks) {
    if (await pathExists(path.join(targetPath, fileName))) return kind;
  }
  if (await pathExists(path.join(targetPath, 'web', 'package.json'))) return 'node';
  if (await pathExists(path.join(targetPath, 'src'))) return 'docs';
  return 'unknown';
}

async function listTopEntries(targetPath, limit = 8) {
  try {
    return (await fs.readdir(targetPath, { withFileTypes: true }))
      .filter((entry) => !ignoredNames.has(entry.name))
      .slice(0, limit)
      .map((entry) => ({ name: entry.name, kind: entry.isDirectory() ? 'directory' : 'file' }));
  } catch {
    return [];
  }
}

export async function listTree(targetPath, maxDepth = 2, currentDepth = 0) {
  if (currentDepth > maxDepth) return [];
  try {
    const entries = await fs.readdir(targetPath, { withFileTypes: true });
    const result = [];
    for (const entry of entries.filter((item) => !ignoredNames.has(item.name)).sort((a, b) => Number(b.isDirectory()) - Number(a.isDirectory()) || a.name.localeCompare(b.name)).slice(0, 80)) {
      const fullPath = path.join(targetPath, entry.name);
      const node = { name: entry.name, path: fullPath, kind: entry.isDirectory() ? 'directory' : 'file' };
      if (entry.isDirectory()) node.children = await listTree(fullPath, maxDepth, currentDepth + 1);
      result.push(node);
    }
    return result;
  } catch {
    return [];
  }
}

export async function summarizeWorkspace(targetPath) {
  const kind = await detectProjectKind(targetPath);
  const git = await readGitInfo(targetPath);
  const entries = await listTopEntries(targetPath);
  const name = path.basename(targetPath) || targetPath;
  let summary = `${name} · ${kind}`;
  if (git.isRepo && git.branch) summary += ` · branch ${git.branch}`;
  if (entries.length) summary += ` · ${entries.slice(0, 3).map((entry) => entry.name).join(', ')}`;
  return { kind, git, summary };
}

export async function buildWorkspaceFolder(absolutePath, id = uid('ws')) {
  const summary = await summarizeWorkspace(absolutePath);
  return {
    id,
    name: path.basename(absolutePath) || absolutePath,
    absolutePath,
    displayPath: displayPath(absolutePath),
    lastOpenedAt: nowIso(),
    projectKind: summary.kind,
    git: summary.git,
    summary: summary.summary,
  };
}

function isSeedRun(run) {
  return String(run?.id ?? '').startsWith('run-') || run?.objective === '待输入首条需求';
}

export async function createInitialState({ persisted }) {
  const workspaceByPath = new Map();
  for (const workspace of Array.isArray(persisted?.workspaces) ? persisted.workspaces : []) {
    if (workspace?.absolutePath && await isDirectory(workspace.absolutePath)) {
      workspaceByPath.set(workspace.absolutePath, workspace);
    }
  }

  return {
    settings: persisted?.settings ?? {
      theme: 'dark',
      compactLayout: true,
      defaultRuntime: 'codex',
      approvalPolicy: 'balanced',
      autoOpenInspector: true,
      recentWorkspaceLimit: 6,
    },
    workspaces: [...workspaceByPath.values()],
    runs: (Array.isArray(persisted?.runs) ? persisted.runs : []).filter((run) => !isSeedRun(run)),
  };
}

function parseDiffName(line) {
  return line.replace(/^diff --git a\//, '').replace(/ b\/.*$/, '');
}

export async function buildReviewProjection(gitRoot) {
  try {
    const { stdout } = await execFileAsync('git', ['-C', gitRoot, 'diff', '--unified=3', '--no-ext-diff', '--no-color'], { maxBuffer: 8 * 1024 * 1024 });
    const files = [];
    let current = null;
    let currentHunk = null;
    for (const line of stdout.split('\n')) {
      if (line.startsWith('diff --git ')) {
        current = { path: parseDiffName(line), status: 'modified', add: 0, del: 0, hunks: [] };
        files.push(current);
      } else if (current && line.startsWith('@@')) {
        currentHunk = { header: line, lines: [] };
        current.hunks.push(currentHunk);
      } else if (currentHunk && line.startsWith('+') && !line.startsWith('+++')) {
        current.add += 1;
        currentHunk.lines.push({ type: 'add', content: line });
      } else if (currentHunk && line.startsWith('-') && !line.startsWith('---')) {
        current.del += 1;
        currentHunk.lines.push({ type: 'del', content: line });
      } else if (currentHunk && line) {
        currentHunk.lines.push({ type: 'context', content: line });
      }
    }
    return { files, summary: files.length ? `当前有 ${files.length} 个文件存在未提交变更。` : '当前没有未提交 diff。', riskItems: [] };
  } catch {
    return { files: [], summary: '无法读取 git diff。', riskItems: [] };
  }
}

export function computeDashboardSummary(runs) {
  const total = runs.length || 1;
  const completed = runs.filter((run) => run.status === 'completed').length;
  return {
    sessions: runs.length,
    agents: runs.reduce((sum, run) => sum + (run.agents?.length ?? 0), 0),
    reviewPassRate: Math.round((completed / total) * 100),
    shipTimeMinutes: Math.round(runs.reduce((sum, run) => sum + (run.durationMs ?? 0), 0) / total / 60000),
    approvals: runs.reduce((sum, run) => sum + (run.approvals ?? []).filter((approval) => approval.status === 'pending').length, 0),
    slowReviews: runs.filter((run) => run.review?.files?.length && run.durationMs > 60 * 60 * 1000).length,
  };
}

export function buildActivitySeries(days = 18) {
  return Array.from({ length: days }, (_, index) => ({ day: `D-${days - index}`, review: 0, terminal: 0, agent: 0 }));
}
