import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve(process.argv[2] || '.');
const port = Number(process.env.PORT || 4173);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml' };
createServer(async (req, res) => {
  try {
    let pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (pathname === '/') pathname = '/index.html';
    if (root === process.cwd() && pathname.startsWith('/data/')) pathname = `/public${pathname}`;
    const file = path.resolve(root, `.${pathname}`);
    if (!file.startsWith(root + path.sep) || pathname.split('/').some(p => p.startsWith('.') || ['node_modules', 'config', 'scripts', 'reports'].includes(p))) throw new Error('Forbidden');
    if (!(await stat(file)).isFile()) throw new Error('Not found');
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(await readFile(file));
  } catch {
    res.writeHead(404); res.end('Not found');
  }
}).listen(port, '127.0.0.1', () => console.log(`Beach Note → http://127.0.0.1:${port}`));
