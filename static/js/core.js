/* DF_Xray Panel — ядро фронтенда: API, форматирование, UI-примитивы, графики. */

export const state = {
  me: null,
  panel: { panel_title: 'DF_Xray', panel_subtitle: 'Panel', footer_note: '' },
  version: '',
  bootstrapPassword: false,
  baseUrl: '',
  nodes: [],
};

/* ------------------------------------------------------------------ API --- */

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const options = {
    method,
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'DF_Xray', ...headers },
  };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    throw new ApiError('Нет связи с панелью', 0);
  }
  if (response.status === 204) return {};
  const type = response.headers.get('content-type') || '';
  let payload = null;
  if (type.includes('application/json')) {
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
  }
  if (!response.ok) {
    const message = (payload && (payload.error || payload.message)) || `Ошибка ${response.status}`;
    if (response.status === 401 && state.me && !path.includes('/auth/login')) {
      window.dispatchEvent(new CustomEvent('dfx:unauthorized'));
    }
    throw new ApiError(message, response.status);
  }
  return payload;
}

/* ---------------------------------------------------------- форматирование --- */

export function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const UNITS = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ', 'ПБ'];

export function fmtBytes(bytes, digits = 1) {
  let value = Number(bytes) || 0;
  if (value <= 0) return '0 Б';
  let index = 0;
  while (value >= 1024 && index < UNITS.length - 1) {
    value /= 1024;
    index += 1;
  }
  const fixed = index === 0 ? 0 : value >= 100 ? 0 : digits;
  return `${value.toFixed(fixed).replace('.', ',')} ${UNITS[index]}`;
}

export function fmtNum(value) {
  return new Intl.NumberFormat('ru-RU').format(Number(value) || 0);
}

export function fmtDate(value) {
  if (!value) return '—';
  const date = value.length <= 10 ? new Date(`${value}T12:00:00`) : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function fmtDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

export function relTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 45) return 'только что';
  if (diff < 3600) return `${Math.round(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.round(diff / 3600)} ч назад`;
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)} дн назад`;
  return fmtDate(value);
}

export function daysLabel(days) {
  if (days === null || days === undefined) return 'бессрочно';
  if (days < 0) return `истёк ${Math.abs(days)} дн назад`;
  if (days === 0) return 'истекает сегодня';
  const forms = ['день', 'дня', 'дней'];
  const mod10 = days % 10;
  const mod100 = days % 100;
  let word = forms[2];
  if (mod10 === 1 && mod100 !== 11) word = forms[0];
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) word = forms[1];
  return `${days} ${word}`;
}

export function initials(name) {
  const value = String(name || '?').trim();
  const parts = value.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return value.slice(0, 2).toUpperCase();
}

export const STATUS_LABELS = {
  active: 'Активен',
  disabled: 'Отключён',
  expired: 'Истёк',
  limited: 'Лимит',
  online: 'Онлайн',
  offline: 'Офлайн',
  unknown: 'Нет данных',
};

export function statusBadge(status, labels = STATUS_LABELS) {
  return `<span class="status ${esc(status)}"><span class="dot"></span>${esc(labels[status] || status)}</span>`;
}

export function protoChips(node) {
  return `
    <span class="chip accent">${esc((node.protocol || 'vless').toUpperCase())}</span>
    <span class="chip">${esc(node.transport)}</span>
    <span class="chip">${esc(node.security)}</span>`;
}

/* ---------------------------------------------------------------- иконки --- */

const P = {
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  layers: '<path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/>',
  route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  radar: '<path d="M19.07 4.93A10 10 0 1 0 21 12"/><path d="M15.54 8.46A5 5 0 1 0 17 12"/><path d="M12 12l7-7"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07L11.5 5.5"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07L12.5 18.5"/>',
  server: '<rect x="2" y="3" width="20" height="7" rx="2"/><rect x="2" y="14" width="20" height="7" rx="2"/><path d="M6 6.5h.01M6 17.5h.01"/>',
  activity: '<path d="M22 12h-4l-3 8L9 4l-3 8H2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  qr: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM21 14v3M18 21h3M14 21h1"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
  chevron: '<path d="M9 18l6-6-6-6"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  power: '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><path d="M12 2v10"/>',
  key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.5 12.5L20 3l1.5 1.5L20 6l1.5 1.5L19 10l-2-2"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  wifi: '<path d="M5 12.55a11 11 0 0 1 14 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><path d="M12 20h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/>',
  chart: '<path d="M3 3v18h18"/><path d="M7 15l3-4 3 3 4-6"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  bolt: '<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>',
  power_off: '<path d="M12 2v10"/><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>',
  filter: '<path d="M4 5h16l-6 7v6l-4 2v-8z"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/>',
  arrowUp: '<path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>',
  arrowDown: '<path d="M12 5v14"/><path d="M19 12l-7 7-7-7"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
};

export function icon(name, cls = '') {
  const path = P[name] || P.info;
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

/* ----------------------------------------------------------------- тосты --- */

export function toast(message, type = 'ok', ms = 3200) {
  let root = document.querySelector('.toasts');
  if (!root) {
    root = document.createElement('div');
    root.className = 'toasts';
    document.body.appendChild(root);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(type === 'ok' ? 'check' : 'alert', 'ico')}<div>${esc(message)}</div>`;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 220);
  }, ms);
}

export async function copy(text, successMessage = 'Скопировано') {
  try {
    await navigator.clipboard.writeText(text);
  } catch (err) {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    area.remove();
  }
  toast(successMessage);
}

/* -------------------------------------------------------- drawer / modal --- */

let openLayer = null;

function ensureBackdrop(cls, onClose) {
  const backdrop = document.createElement('div');
  backdrop.className = `${cls} backdrop-layer`;
  backdrop.addEventListener('click', onClose);
  document.body.appendChild(backdrop);
  requestAnimationFrame(() => backdrop.classList.add('show'));
  return backdrop;
}

export function closeLayer() {
  if (!openLayer) return;
  const { root, backdrop, onClose } = openLayer;
  openLayer = null;
  root.classList.remove('show');
  backdrop.classList.remove('show');
  document.body.style.overflow = '';
  setTimeout(() => {
    root.remove();
    backdrop.remove();
  }, 260);
  if (typeof onClose === 'function') onClose();
}

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') closeLayer();
});

export function openDrawer({ title, subtitle = '', body = '', footer = '', onMount, onClose }) {
  closeLayer();
  const backdrop = ensureBackdrop('drawer-backdrop', () => closeLayer());
  const drawer = document.createElement('aside');
  drawer.className = 'drawer';
  drawer.innerHTML = `
    <div class="drawer-head">
      <div style="flex:1;min-width:0">
        <h2>${esc(title)}</h2>
        ${subtitle ? `<div class="hint">${subtitle}</div>` : ''}
      </div>
      <button class="icon-btn" data-close aria-label="Закрыть">${icon('x')}</button>
    </div>
    <div class="drawer-body">${body}</div>
    ${footer ? `<div class="drawer-foot">${footer}</div>` : ''}
  `;
  drawer.querySelector('[data-close]').addEventListener('click', () => closeLayer());
  document.body.appendChild(drawer);
  document.body.style.overflow = 'hidden';
  requestAnimationFrame(() => drawer.classList.add('show'));
  openLayer = { root: drawer, backdrop, onClose };
  if (onMount) onMount(drawer);
  return drawer;
}

export function openModal({ title, body = '', footer = '', wide = false, onMount, onClose }) {
  closeLayer();
  const backdrop = ensureBackdrop('modal-backdrop', () => closeLayer());
  const modal = document.createElement('div');
  modal.className = `modal${wide ? ' wide' : ''}`;
  modal.innerHTML = `
    <div class="modal-head">
      <h3>${esc(title)}</h3>
      <button class="icon-btn" data-close style="margin-left:auto" aria-label="Закрыть">${icon('x')}</button>
    </div>
    <div class="modal-body">${body}</div>
    ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
  `;
  modal.querySelector('[data-close]').addEventListener('click', () => closeLayer());
  document.body.appendChild(modal);
  document.body.style.overflow = 'hidden';
  requestAnimationFrame(() => modal.classList.add('show'));
  openLayer = { root: modal, backdrop, onClose };
  if (onMount) onMount(modal);
  return modal;
}

export function confirmDialog({
  title = 'Подтвердите действие',
  text = 'Действие нельзя отменить.',
  confirmText = 'Подтвердить',
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const modal = openModal({
      title,
      body: `<p class="dim" style="font-size:13.5px;line-height:1.6">${text}</p>`,
      footer: `
        <button class="btn" data-cancel>Отмена</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-ok>${esc(confirmText)}</button>`,
      onClose: () => finish(false),
    });
    modal.querySelector('[data-cancel]').addEventListener('click', () => {
      finish(false);
      closeLayer();
    });
    modal.querySelector('[data-ok]').addEventListener('click', () => {
      finish(true);
      closeLayer();
    });
  });
}

/* ---------------------------------------------------------------- график --- */

function niceMax(value) {
  if (value <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const fraction = value / exp;
  const steps = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10];
  const step = steps.find((s) => fraction <= s) || 10;
  return step * exp;
}

export function areaChart(series, { height = 230 } = {}) {
  const width = 660;
  const pad = { l: 46, r: 12, t: 14, b: 26 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const totals = series.map((p) => p.total || 0);
  const max = niceMax(Math.max(...totals, 1));
  const stepX = series.length > 1 ? innerW / (series.length - 1) : innerW;
  const x = (i) => pad.l + i * stepX;
  const y = (v) => pad.t + innerH - (v / max) * innerH;

  const downPts = series.map((p, i) => [x(i), y(p.down || 0)]);
  const upPts = series.map((p, i) => [x(i), y((p.down || 0) + (p.up || 0))]);

  const line = (pts) => pts.map((pt, i) => `${i ? 'L' : 'M'}${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ');
  const area = (upper, lower) => {
    const top = line(upper);
    const bottom = [...lower].reverse().map((pt) => `L${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ');
    return `${top} ${bottom} Z`;
  };

  const base = series.map((p, i) => [x(i), y(0)]);
  const gridCount = 4;
  let grid = '';
  for (let i = 0; i <= gridCount; i += 1) {
    const value = (max / gridCount) * i;
    const yy = y(value);
    grid += `<line x1="${pad.l}" y1="${yy.toFixed(1)}" x2="${width - pad.r}" y2="${yy.toFixed(1)}"
      stroke="#1c2434" stroke-width="1" ${i === 0 ? '' : 'stroke-dasharray="3 5"'}/>`;
    grid += `<text x="${pad.l - 9}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end"
      fill="#6f7a92" font-size="10">${fmtBytes(value, 0)}</text>`;
  }

  const tickEvery = Math.max(1, Math.ceil(series.length / 7));
  let xLabels = '';
  series.forEach((p, i) => {
    if (i % tickEvery !== 0 && i !== series.length - 1) return;
    const date = new Date(`${p.day}T12:00:00`);
    const label = date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    xLabels += `<text x="${x(i).toFixed(1)}" y="${height - 7}" text-anchor="middle"
      fill="#6f7a92" font-size="10">${label}</text>`;
    if (i !== 0 && i !== series.length - 1) {
      xLabels += `<line x1="${x(i).toFixed(1)}" y1="${pad.t}" x2="${x(i).toFixed(1)}"
        y2="${pad.t + innerH}" stroke="#161d2b" stroke-width="1"/>`;
    }
  });

  const lastIdx = series.length - 1;
  const marker = series.length
    ? `<circle cx="${x(lastIdx).toFixed(1)}" cy="${upPts[lastIdx][1].toFixed(1)}" r="3.4"
        fill="#0b0f17" stroke="#7c5cff" stroke-width="2"/>`
    : '';

  const svg = `
    <div class="chart-wrap" style="position:relative">
      <svg class="chart" viewBox="0 0 ${width} ${height}" role="img">
        <defs>
          <linearGradient id="gDown" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#7c5cff" stop-opacity=".55"/>
            <stop offset="100%" stop-color="#7c5cff" stop-opacity=".02"/>
          </linearGradient>
          <linearGradient id="gUp" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2ee6a8" stop-opacity=".5"/>
            <stop offset="100%" stop-color="#2ee6a8" stop-opacity=".02"/>
          </linearGradient>
        </defs>
        ${grid}
        <path d="${area(downPts, base)}" fill="url(#gDown)"/>
        <path d="${line(downPts)}" fill="none" stroke="#8f74ff" stroke-width="2" stroke-linejoin="round"/>
        <path d="${area(upPts, downPts)}" fill="url(#gUp)"/>
        <path d="${line(upPts)}" fill="none" stroke="#2ee6a8" stroke-width="2" stroke-linejoin="round"/>
        ${marker}
        ${xLabels}
        <g class="hover-layer" style="opacity:0">
          <line y1="${pad.t}" y2="${pad.t + innerH}" stroke="#3c4a6b" stroke-width="1" stroke-dasharray="3 4"/>
          <circle r="4" fill="#fff"/>
        </g>
      </svg>
      <div class="chart-tip" style="position:absolute;pointer-events:none;opacity:0;transition:opacity .12s;
        background:#131927;border:1px solid #2b3650;border-radius:9px;padding:7px 10px;font-size:11.5px;
        color:#e9edf7;box-shadow:0 10px 24px rgba(0,0,0,.45);white-space:nowrap;z-index:2"></div>
    </div>`;

  return {
    html: svg,
    mount(container) {
      const wrap = container.querySelector('.chart-wrap');
      if (!wrap) return;
      const svgEl = wrap.querySelector('svg');
      const hover = wrap.querySelector('.hover-layer');
      const lineEl = hover.querySelector('line');
      const dot = hover.querySelector('circle');
      const tip = wrap.querySelector('.chart-tip');
      const move = (ev) => {
        const rect = svgEl.getBoundingClientRect();
        const ratio = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
        const i = Math.round(ratio * (series.length - 1));
        const point = upPts[i];
        if (!point) return;
        hover.style.opacity = '1';
        lineEl.setAttribute('x1', point[0]);
        lineEl.setAttribute('x2', point[0]);
        dot.setAttribute('cx', point[0]);
        dot.setAttribute('cy', point[1]);
        const data = series[i];
        const date = new Date(`${data.day}T12:00:00`).toLocaleDateString('ru-RU', {
          day: '2-digit', month: 'long',
        });
        tip.innerHTML = `<b>${date}</b><br>↓ ${fmtBytes(data.down)} &nbsp; ↑ ${fmtBytes(data.up)}`;
        const px = (point[0] / width) * rect.width;
        const left = Math.min(Math.max(px - 60, 4), rect.width - 150);
        tip.style.left = `${left}px`;
        tip.style.top = '6px';
        tip.style.opacity = '1';
      };
      svgEl.addEventListener('mousemove', move);
      svgEl.addEventListener('mouseleave', () => {
        hover.style.opacity = '0';
        tip.style.opacity = '0';
      });
    },
  };
}

export function sparkline(values, { width = 84, height = 26, stroke = '#7c5cff' } = {}) {
  if (!values || values.length < 2) return '';
  const max = Math.max(...values, 1);
  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => `${(i * stepX).toFixed(1)},${(height - (v / max) * (height - 3) - 1.5).toFixed(1)}`);
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" fill="none">
    <path d="M${points.join(' L')}" stroke="${stroke}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

/* -------------------------------------------------------------- мелочи --- */

export function usageBar(used, limit) {
  const percent = limit ? Math.min(100, (used / limit) * 100) : 0;
  const cls = limit ? (percent >= 95 ? 'danger' : percent >= 70 ? 'warn' : '') : 'unlimited';
  return `
    <div class="usage">
      <div class="lbl"><b>${fmtBytes(used)}</b><span>${limit ? `из ${fmtBytes(limit)}` : 'без лимита'}</span></div>
      <div class="bar ${cls}"><i style="width:${limit ? Math.max(percent, 1.5).toFixed(1) : 100}%"></i></div>
    </div>`;
}

export function formField(form, name) {
  return form.querySelector(`[name="${name}"]`);
}

export function formValue(form, name, fallback = '') {
  const el = formField(form, name);
  return el ? el.value : fallback;
}

export function formChecked(form, name) {
  const el = formField(form, name);
  return el ? el.checked : false;
}

export function clearBindings(container) {
  const key = '__dfx_click';
  if (container[key]) {
    container.removeEventListener('click', container[key]);
    delete container[key];
  }
}

export function bind(container, type, handler) {
  const key = `__dfx_${type}`;
  if (container[key]) container.removeEventListener(type, container[key]);
  container[key] = handler;
  container.addEventListener(type, handler);
}

export function debounce(fn, ms = 260) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function download(filename, text, type = 'application/json') {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export function timeAgoShort(value) {
  if (!value) return '—';
  const date = new Date(value);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (Number.isNaN(diff)) return '—';
  if (diff < 60) return 'сейчас';
  if (diff < 3600) return `${Math.floor(diff / 60)} мин`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч`;
  return `${Math.floor(diff / 86400)} дн`;
}

/* ------------------------------------------------------------ аудит-метки --- */

export const AUDIT_LABELS = {
  'auth.login': 'Вход в панель',
  'auth.logout': 'Выход из панели',
  'auth.login_failed': 'Неудачный вход',
  'auth.password_change': 'Смена пароля',
  'auth.sessions_revoke': 'Отзыв сессий',
  'user.create': 'Создан пользователь',
  'user.update': 'Изменён пользователь',
  'user.delete': 'Удалён пользователь',
  'user.enable': 'Пользователь включён',
  'user.disable': 'Пользователь отключён',
  'user.reset_traffic': 'Сброс трафика',
  'user.rotate_uuid': 'Перевыпуск UUID',
  'user.rotate_sub': 'Перевыпуск подписки',
  'user.extend': 'Продление подписки',
  'user.set_limit': 'Изменён лимит',
  'node.create': 'Добавлена нода',
  'node.update': 'Изменена нода',
  'node.delete': 'Удалена нода',
  'node.reality_keys': 'Новые Reality-ключи',
  'node.rotate_token': 'Обновлён токен ноды',
  'settings.update': 'Изменены настройки',
  'maintenance.purge_traffic': 'Очистка статистики',
  'seed.demo': 'Загружены демо-данные',
};

export function auditLabel(action) {
  return AUDIT_LABELS[action] || action;
}

export function auditIcon(action) {
  if (action.startsWith('node.')) return 'server';
  if (action.startsWith('user.')) return 'users';
  if (action.startsWith('auth.')) return 'lock';
  if (action.startsWith('settings.')) return 'settings';
  if (action.startsWith('maintenance.')) return 'refresh';
  return 'info';
}

export function auditText(item) {
  const parts = [];
  if (item.target) parts.push(`<b>${esc(item.target)}</b>`);
  const detail = item.detail ? ` · ${esc(item.detail)}` : '';
  return `${parts.join(' ')}${detail}`;
}
