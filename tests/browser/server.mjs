import { spawn } from 'node:child_process';
import { mkdirSync, rmSync, createWriteStream } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(`test-results/server-${process.pid}`);
mkdirSync(resolve(root, 'runtime'), { recursive: true });
const server = spawn(resolve('.venv/bin/python'), ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8765'], {
  cwd: process.cwd(),
  stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, APP_ENV: 'test', AI_ENABLED: 'false', STORAGE_ROOT: root, TMPDIR: resolve(root, 'runtime'), TEMP: resolve(root, 'runtime'), TMP: resolve(root, 'runtime') }
});
const log = createWriteStream(resolve('test-results/full-verification-server.log'));
server.stdout.on('data', chunk => { process.stdout.write(chunk); log.write(chunk); });
server.stderr.on('data', chunk => { process.stderr.write(chunk); log.write(chunk); });
server.on('exit', () => log.end());
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.kill(signal));
server.on('error', error => { console.error(`Cannot start browser-test API: ${error.message}. Create .venv and install requirements.txt first.`); rmSync(root, { recursive: true, force: true }); process.exitCode = 1; });
server.on('exit', code => { rmSync(root, { recursive: true, force: true }); process.exitCode = code ?? 0; });
