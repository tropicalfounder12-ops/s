// Zero-dependency server: serves ./public and a small JSON API backed by data/sessions.json
const http = require('http');
const os = require('os');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
// 127.0.0.1 = this computer only. Use HOST=0.0.0.0 (npm run start:lan) to allow phones on your Wi-Fi.
const HOST = process.env.HOST || '127.0.0.1';
const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_DIR = path.join(__dirname, 'data');
const DATA_FILE = path.join(DATA_DIR, 'sessions.json');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json',
  '.ico': 'image/x-icon',
};

function loadSessions() {
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  } catch {
    return [];
  }
}

function saveSessions(sessions) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const tmp = DATA_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(sessions, null, 2));
  fs.renameSync(tmp, DATA_FILE);
}

function sendJson(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 1e6) {
        reject(new Error('Body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
    req.on('error', reject);
  });
}

function validate(input) {
  const date = String(input.date || '');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(date))) {
    return { error: 'date must be YYYY-MM-DD' };
  }
  const type = String(input.type || '').trim().slice(0, 40);
  if (!type) return { error: 'type is required' };
  const minutes = Number(input.minutes);
  if (!Number.isFinite(minutes) || minutes <= 0 || minutes > 1440) {
    return { error: 'minutes must be between 1 and 1440' };
  }
  const notes = String(input.notes || '').slice(0, 1000);
  return { value: { date, type, minutes: Math.round(minutes), notes } };
}

async function handleApi(req, res, pathname) {
  const idMatch = pathname.match(/^\/api\/sessions\/([\w-]+)$/);

  if (pathname === '/api/sessions' && req.method === 'GET') {
    return sendJson(res, 200, loadSessions());
  }

  if (pathname === '/api/sessions' && req.method === 'POST') {
    const { value, error } = validate(await readBody(req));
    if (error) return sendJson(res, 400, { error });
    const sessions = loadSessions();
    const session = { id: crypto.randomUUID(), ...value };
    sessions.push(session);
    saveSessions(sessions);
    return sendJson(res, 201, session);
  }

  if (idMatch && req.method === 'PUT') {
    const { value, error } = validate(await readBody(req));
    if (error) return sendJson(res, 400, { error });
    const sessions = loadSessions();
    const idx = sessions.findIndex((s) => s.id === idMatch[1]);
    if (idx === -1) return sendJson(res, 404, { error: 'Not found' });
    sessions[idx] = { id: idMatch[1], ...value };
    saveSessions(sessions);
    return sendJson(res, 200, sessions[idx]);
  }

  if (idMatch && req.method === 'DELETE') {
    const sessions = loadSessions();
    const next = sessions.filter((s) => s.id !== idMatch[1]);
    if (next.length === sessions.length) return sendJson(res, 404, { error: 'Not found' });
    saveSessions(next);
    return sendJson(res, 200, { ok: true });
  }

  return sendJson(res, 404, { error: 'Not found' });
}

function serveStatic(req, res, pathname) {
  const rel = pathname === '/' ? '/index.html' : pathname;
  const file = path.normalize(path.join(PUBLIC_DIR, rel));
  if (!file.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    return res.end('Forbidden');
  }
  fs.readFile(file, (err, content) => {
    if (err) {
      res.writeHead(404);
      return res.end('Not found');
    }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    res.end(content);
  });
}

const server = http.createServer(async (req, res) => {
  const { pathname } = new URL(req.url, 'http://localhost');
  try {
    if (pathname.startsWith('/api/')) return await handleApi(req, res, pathname);
    return serveStatic(req, res, pathname);
  } catch (err) {
    sendJson(res, 400, { error: err.message });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Gym tracker running at http://localhost:${PORT}`);
  if (HOST === '127.0.0.1') return;
  const urls = Object.values(os.networkInterfaces())
    .flat()
    .filter((i) => i.family === 'IPv4' && !i.internal)
    .map((i) => `http://${i.address}:${PORT}`);
  console.log('On your phone (same Wi-Fi), open:');
  for (const url of urls) console.log(`  ${url}`);
  console.log('Note: there is no password, so anyone on this network can open it.');
});
