import { spawn } from 'node:child_process';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const webRoot = process.cwd();
const repoRoot = path.resolve(webRoot, '..');
const viteBin = path.join(webRoot, 'node_modules', 'vite', 'bin', 'vite.js');

const bundledPython = '/Users/yanmingxin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
const pythonCandidates = [process.env.PYTHON, process.env.PYTHON_BIN, bundledPython, 'python3', 'python'];
let python = null;
for (const candidate of pythonCandidates) {
  if (!candidate) continue;
  try {
    execFileSync(candidate, ['-c', 'import sys'], { stdio: 'ignore' });
    python = candidate;
    break;
  } catch {
    continue;
  }
}

if (!python) {
  throw new Error('Unable to find a usable Python interpreter for ai-collab web API.');
}

const backendEnv = {
  ...process.env,
  AI_COLLAB_DEV_MODE: '1',
  PYTHONPATH: process.env.PYTHONPATH
    ? `${repoRoot}:${process.env.PYTHONPATH}`
    : repoRoot,
};

const backend = spawn(python, ['-m', 'ai_collab.web_api', '--workspace-root', repoRoot, '--port', '8787'], {
  cwd: repoRoot,
  env: backendEnv,
  stdio: 'inherit',
});

const vite = spawn(process.execPath, [viteBin, '--host', '127.0.0.1'], {
  cwd: webRoot,
  env: process.env,
  stdio: 'inherit',
});

function shutdown(signal) {
  backend.kill(signal);
  vite.kill(signal);
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

backend.on('exit', (code) => {
  if (code && code !== 0) process.exitCode = code;
  vite.kill('SIGTERM');
});

vite.on('exit', (code) => {
  if (code && code !== 0) process.exitCode = code;
  backend.kill('SIGTERM');
});
