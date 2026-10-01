const PRESET_TYPES = {
  chest: '#e11d48',
  back: '#2563eb',
  legs: '#16a34a',
  arms: '#ea580c',
  shoulders: '#9333ea',
  abs: '#0891b2',
  cardio: '#ca8a04',
  'full body': '#475569',
};

const $ = (id) => document.getElementById(id);

const state = {
  sessions: [],
  year: new Date().getFullYear(),
  month: new Date().getMonth(),
  selectedDate: null,
  editingId: null,
};

// ---------- helpers ----------

function pad(n) {
  return String(n).padStart(2, '0');
}

function toDateStr(y, m, d) {
  return `${y}-${pad(m + 1)}-${pad(d)}`;
}

function todayStr() {
  const t = new Date();
  return toDateStr(t.getFullYear(), t.getMonth(), t.getDate());
}

function formatMinutes(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h && m) return `${h}h ${m}m`;
  return h ? `${h}h` : `${m}m`;
}

function normalizeType(raw) {
  const t = raw.trim().replace(/\s+/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function colorFor(type) {
  const key = type.toLowerCase();
  if (PRESET_TYPES[key]) return PRESET_TYPES[key];
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${hash}, 55%, 42%)`;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}

async function api(path, options) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || 'Request failed');
  return body;
}

function sessionsOn(date) {
  return state.sessions.filter((s) => s.date === date);
}

// ---------- calendar ----------

function renderCalendar() {
  const { year, month } = state;
  $('monthLabel').textContent = new Date(year, month, 1).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  });

  const grid = $('grid');
  grid.replaceChildren();

  // Monday-first grid
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7;
  const start = new Date(year, month, 1 - firstWeekday);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
  const today = todayStr();

  for (let i = 0; i < cells; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const dateStr = toDateStr(d.getFullYear(), d.getMonth(), d.getDate());
    const cell = el('div', { className: 'day' });
    if (d.getMonth() !== month) cell.classList.add('other');
    if (dateStr === today) cell.classList.add('today');

    cell.append(el('span', { className: 'num' }, String(d.getDate())));

    const daySessions = sessionsOn(dateStr);
    for (const s of daySessions) {
      const chip = el(
        'span',
        { className: 'chip', title: s.notes || '' },
        el('span', { className: 't' }, s.type),
        el('span', { className: 'd' }, formatMinutes(s.minutes))
      );
      chip.style.background = colorFor(s.type);
      cell.append(chip);
    }
    if (daySessions.length > 1) {
      const total = daySessions.reduce((sum, s) => sum + s.minutes, 0);
      cell.append(el('span', { className: 'total' }, el('span', { className: 'lbl' }, 'Total '), formatMinutes(total)));
    }

    cell.addEventListener('click', () => openDay(dateStr));
    grid.append(cell);
  }

  renderSummary();
}

function renderSummary() {
  const prefix = `${state.year}-${pad(state.month + 1)}-`;
  const monthSessions = state.sessions.filter((s) => s.date.startsWith(prefix));
  const totalMin = monthSessions.reduce((sum, s) => sum + s.minutes, 0);

  $('statSessions').textContent = monthSessions.length;
  $('statTime').textContent = formatMinutes(totalMin);
  $('statDays').textContent = new Set(monthSessions.map((s) => s.date)).size;

  const byType = new Map();
  for (const s of monthSessions) {
    const key = s.type.toLowerCase();
    const entry = byType.get(key) || { label: s.type, minutes: 0, count: 0 };
    entry.minutes += s.minutes;
    entry.count += 1;
    byType.set(key, entry);
  }

  const list = $('breakdown');
  list.replaceChildren();
  if (!byType.size) {
    list.append(el('li', { className: 'empty' }, 'No sessions this month yet.'));
    return;
  }
  const sorted = [...byType.values()].sort((a, b) => b.minutes - a.minutes);
  for (const entry of sorted) {
    const bar = el('div', { className: 'bar' });
    const fill = el('i');
    fill.style.width = `${Math.round((entry.minutes / totalMin) * 100)}%`;
    fill.style.background = colorFor(entry.label);
    bar.append(fill);
    list.append(
      el(
        'li',
        {},
        el(
          'div',
          { className: 'row' },
          el('span', {}, `${entry.label} (${entry.count})`),
          el('span', {}, formatMinutes(entry.minutes))
        ),
        bar
      )
    );
  }
}

// ---------- day dialog ----------

function renderTypeSuggestions() {
  const names = new Set(Object.keys(PRESET_TYPES).map(normalizeType));
  for (const s of state.sessions) names.add(s.type);
  $('types').replaceChildren(...[...names].sort().map((n) => el('option', { value: n })));
}

function renderDayList() {
  const list = $('dayList');
  list.replaceChildren();
  const daySessions = sessionsOn(state.selectedDate);
  if (!daySessions.length) {
    list.append(el('li', { className: 'empty' }, 'Nothing logged for this day.'));
    return;
  }
  for (const s of daySessions) {
    const info = el('div', { className: 'info' }, el('strong', {}, `${s.type} · ${formatMinutes(s.minutes)}`));
    if (s.notes) info.append(el('small', {}, s.notes));

    const edit = el('button', { className: 'ghost', type: 'button' }, 'Edit');
    edit.addEventListener('click', () => startEdit(s));
    const del = el('button', { className: 'ghost danger', type: 'button' }, 'Delete');
    del.addEventListener('click', () => removeSession(s));

    const li = el('li', {}, info, edit, del);
    li.style.borderLeftColor = colorFor(s.type);
    list.append(li);
  }
}

function resetForm() {
  state.editingId = null;
  $('type').value = '';
  $('minutes').value = 60;
  $('notes').value = '';
  $('formTitle').textContent = 'Add session';
  $('submit').textContent = 'Add session';
  $('cancelEdit').hidden = true;
  $('error').hidden = true;
}

function startEdit(session) {
  state.editingId = session.id;
  $('type').value = session.type;
  $('minutes').value = session.minutes;
  $('notes').value = session.notes || '';
  $('formTitle').textContent = 'Edit session';
  $('submit').textContent = 'Save changes';
  $('cancelEdit').hidden = false;
  $('type').focus();
}

function openDay(dateStr) {
  state.selectedDate = dateStr;
  const [y, m, d] = dateStr.split('-').map(Number);
  $('dialogTitle').textContent = new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
  resetForm();
  renderTypeSuggestions();
  renderDayList();
  $('dialog').showModal();
  $('type').focus();
}

async function removeSession(session) {
  if (!confirm(`Delete ${session.type} (${formatMinutes(session.minutes)})?`)) return;
  try {
    await api(`/api/sessions/${session.id}`, { method: 'DELETE' });
    state.sessions = state.sessions.filter((s) => s.id !== session.id);
    if (state.editingId === session.id) resetForm();
    renderDayList();
    renderCalendar();
  } catch (err) {
    showError(err.message);
  }
}

function showError(message) {
  $('error').textContent = message;
  $('error').hidden = false;
}

$('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    date: state.selectedDate,
    type: normalizeType($('type').value),
    minutes: Number($('minutes').value),
    notes: $('notes').value.trim(),
  };
  try {
    if (state.editingId) {
      const updated = await api(`/api/sessions/${state.editingId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      state.sessions = state.sessions.map((s) => (s.id === updated.id ? updated : s));
    } else {
      state.sessions.push(await api('/api/sessions', { method: 'POST', body: JSON.stringify(payload) }));
    }
    resetForm();
    renderTypeSuggestions();
    renderDayList();
    renderCalendar();
  } catch (err) {
    showError(err.message);
  }
});

$('cancelEdit').addEventListener('click', resetForm);
$('closeDialog').addEventListener('click', () => $('dialog').close());
$('dialog').addEventListener('click', (e) => {
  if (e.target === $('dialog')) $('dialog').close();
});

// ---------- navigation ----------

function shiftMonth(delta) {
  const d = new Date(state.year, state.month + delta, 1);
  state.year = d.getFullYear();
  state.month = d.getMonth();
  renderCalendar();
}

$('prev').addEventListener('click', () => shiftMonth(-1));
$('next').addEventListener('click', () => shiftMonth(1));
$('today').addEventListener('click', () => {
  const t = new Date();
  state.year = t.getFullYear();
  state.month = t.getMonth();
  renderCalendar();
});

// ---------- init ----------

(async function init() {
  try {
    state.sessions = await api('/api/sessions');
  } catch (err) {
    alert(`Could not load sessions: ${err.message}`);
  }
  renderCalendar();
})();
