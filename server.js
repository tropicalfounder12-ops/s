// Zero-dependency server: serves ./public and a small JSON API backed by data/sessions.json
const http = require('http');
const os = require('os');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
// 127.0.0.1 = this computer only. Use HOST=0.0.0.0 (npm run start:lan) to allow phones on your Wi-Fi.
const HOST = process.env.HOST || '127.0.0.1';
// Set PASSWORD to require a login (always do this when the app is reachable from the internet).
const PASSWORD = process.env.PASSWORD || '';
const SESSION_DAYS = 30;
const COOKIE_NAME = 'gym_session';
// Behind a reverse proxy (Fly, Render, Cloudflare...) set TRUST_PROXY=1 so login throttling sees real IPs.
const TRUST_PROXY = process.env.TRUST_PROXY === '1';
// Optional: enables the Claude-powered features. Read from the environment only, never commit it.
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || '';
const SECRET = crypto.createHash('sha256').update(`gym-tracker:${process.env.SESSION_SECRET || PASSWORD}`).digest();

if (!PASSWORD && HOST !== '127.0.0.1' && process.env.NODE_ENV === 'production') {
  console.error('Refusing to start: set PASSWORD when the app is exposed beyond this computer.');
  process.exit(1);
}
const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
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

// ---------- auth ----------

function sign(value) {
  return crypto.createHmac('sha256', SECRET).update(value).digest('base64url');
}

function makeToken() {
  const expires = String(Date.now() + SESSION_DAYS * 86400 * 1000);
  return `${expires}.${sign(expires)}`;
}

function safeEqual(a, b) {
  const ha = crypto.createHash('sha256').update(String(a)).digest();
  const hb = crypto.createHash('sha256').update(String(b)).digest();
  return crypto.timingSafeEqual(ha, hb);
}

function getCookie(req, name) {
  for (const part of (req.headers.cookie || '').split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return v.join('=');
  }
  return '';
}

function isAuthed(req) {
  if (!PASSWORD) return true;
  const [expires, sig] = getCookie(req, COOKIE_NAME).split('.');
  if (!expires || !sig || !safeEqual(sig, sign(expires))) return false;
  return Number(expires) > Date.now();
}

function cookieHeader(req, value, maxAgeSec) {
  const secure = req.socket.encrypted || req.headers['x-forwarded-proto'] === 'https' ? '; Secure' : '';
  return `${COOKIE_NAME}=${value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAgeSec}${secure}`;
}

// Throttle wrong passwords: 8 failures per 15 minutes per client IP.
const failures = new Map();
function clientIp(req) {
  if (TRUST_PROXY && req.headers['x-forwarded-for']) return req.headers['x-forwarded-for'].split(',')[0].trim();
  return req.socket.remoteAddress;
}
function isThrottled(ip) {
  const f = failures.get(ip);
  return Boolean(f && f.count >= 8 && Date.now() - f.first < 15 * 60 * 1000);
}
function recordFailure(ip) {
  const f = failures.get(ip);
  if (!f || Date.now() - f.first >= 15 * 60 * 1000) failures.set(ip, { count: 1, first: Date.now() });
  else f.count += 1;
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
  if (pathname === '/api/me' && req.method === 'GET') {
    return sendJson(res, 200, {
      authRequired: Boolean(PASSWORD),
      loggedIn: isAuthed(req),
      aiEnabled: Boolean(ANTHROPIC_API_KEY),
    });
  }

  if (pathname === '/api/login' && req.method === 'POST') {
    const ip = clientIp(req);
    if (isThrottled(ip)) return sendJson(res, 429, { error: 'Too many attempts. Try again in 15 minutes.' });
    const { password } = await readBody(req);
    if (!PASSWORD || !safeEqual(password || '', PASSWORD)) {
      recordFailure(ip);
      return sendJson(res, 401, { error: 'Wrong password' });
    }
    failures.delete(ip);
    res.setHeader('Set-Cookie', cookieHeader(req, makeToken(), SESSION_DAYS * 86400));
    return sendJson(res, 200, { ok: true });
  }

  if (pathname === '/api/logout' && req.method === 'POST') {
    res.setHeader('Set-Cookie', cookieHeader(req, '', 0));
    return sendJson(res, 200, { ok: true });
  }

  if (!isAuthed(req)) return sendJson(res, 401, { error: 'Not logged in' });

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
  if (rel === '/index.html' && !isAuthed(req)) {
    res.writeHead(302, { Location: '/login.html' });
    return res.end();
  }
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
  console.log(`Gym tracker running at http://localhost:${PORT}${PASSWORD ? ' (password protected)' : ''}`);
  console.log(ANTHROPIC_API_KEY ? 'Claude features: on' : 'Claude features: off (set ANTHROPIC_API_KEY to enable)');
  if (HOST === '127.0.0.1') return;
  const urls = Object.values(os.networkInterfaces())
    .flat()
    .filter((i) => i.family === 'IPv4' && !i.internal)
    .map((i) => `http://${i.address}:${PORT}`);
  console.log('On your phone (same Wi-Fi), open:');
  for (const url of urls) console.log(`  ${url}`);
  if (!PASSWORD) console.log('Note: no PASSWORD set, so anyone on this network can open it.');
});
