/* DF_Xray Panel — точка входа: оболочка, навигация, роутер. */

import { api, clearBindings, esc, icon, state, toast } from './core.js';
import { renderLogin } from './views/login.js';
import * as dashboardView from './views/dashboard.js';
import * as usersView from './views/users.js';
import * as subsView from './views/subs.js';
import * as nodesView from './views/nodes.js';
import * as auditView from './views/audit.js';
import * as settingsView from './views/settings.js';
import * as inboundsView from './views/inbounds.js';
import * as groupsView from './views/groups.js';
import * as hostsView from './views/hosts.js';
import * as outboundsView from './views/outbounds.js';
import * as routingView from './views/routing.js';
import * as xrayView from './views/xray.js';
import * as apiDocsView from './views/api-docs.js';
import { openPalette } from './palette.js';

const routes = {
  '#/dashboard': {
    title: 'Дашборд',
    subtitle: 'Сводка по пользователям, трафику и нодам',
    view: dashboardView,
    icon: 'grid',
    nav: false,
  },
  '#/users': {
    title: 'Клиенты',
    subtitle: 'Доступы, лимиты, сроки и конфигурации',
    view: usersView,
    icon: 'users',
    nav: true,
  },
  '#/subscriptions': {
    title: 'Подписки',
    subtitle: 'Ссылки, QR-коды и публичная страница',
    view: subsView,
    icon: 'link',
    nav: true,
  },
  '#/nodes': {
    title: 'Ноды',
    subtitle: 'Серверы Xray и их конфигурация',
    view: nodesView,
    icon: 'server',
    nav: true,
  },
  '#/audit': {
    title: 'Журнал',
    subtitle: 'История действий администраторов',
    view: auditView,
    icon: 'activity',
    nav: true,
  },
  '#/inbounds': {
    title: 'Входящие',
    subtitle: 'Протоколы, транспорт и маскировка Reality',
    view: inboundsView,
    icon: 'inbox',
    nav: false,
  },
  '#/groups': {
    title: 'Группы',
    subtitle: 'Объединения клиентов для фильтров и массовых действий',
    view: groupsView,
    icon: 'layers',
    nav: false,
  },
  '#/hosts': {
    title: 'Хосты',
    subtitle: 'Домены-маски из входящих и их проверка',
    view: hostsView,
    icon: 'globe',
    nav: false,
  },
  '#/outbounds': {
    title: 'Исходящие',
    subtitle: 'Маршруты наружу, попадающие в конфиг Xray',
    view: outboundsView,
    icon: 'upload',
    nav: false,
  },
  '#/routing': {
    title: 'Маршрутизация',
    subtitle: 'Правила Xray, DNS и выбор основного исходящего',
    view: routingView,
    icon: 'route',
    nav: false,
  },
  '#/xray': {
    title: 'Конфигурации Xray',
    subtitle: 'Готовый конфиг ноды и Reality-ключи',
    view: xrayView,
    icon: 'terminal',
    nav: false,
  },
  '#/api-docs': {
    title: 'Документация API',
    subtitle: 'Эндпоинты панели и агентов нод',
    view: apiDocsView,
    icon: 'book',
    nav: false,
  },
  '#/settings': {
    title: 'Настройки',
    subtitle: 'Общие параметры, подписки, безопасность и обновления',
    view: settingsView,
    icon: 'settings',
    nav: true,
  },
};

const NAV = [
  { href: '#/dashboard', label: 'Дашборд', icon: 'grid' },
  { href: '#/inbounds', label: 'Входящие', icon: 'inbox' },
  { href: '#/users', label: 'Клиенты', icon: 'users', badge: 'users' },
  { href: '#/groups', label: 'Группы', icon: 'layers' },
  { href: '#/nodes', label: 'Узлы', icon: 'server' },
  { href: '#/hosts', label: 'Хосты', icon: 'globe' },
  { href: '#/outbounds', label: 'Исходящие', icon: 'upload' },
  { href: '#/routing', label: 'Маршрутизация', icon: 'route' },
  {
    id: 'panel',
    label: 'Настройки панели',
    icon: 'settings',
    badge: 'update',
    items: [
      ['#/settings?section=general', 'Общие'],
      ['#/settings?section=subscription', 'Подписки'],
      ['#/settings?section=security', 'Безопасность'],
      ['#/settings?section=update', 'Обновление'],
      ['#/settings?section=maintenance', 'Обслуживание'],
      ['#/audit', 'Журнал действий'],
      ['#/settings?section=about', 'О панели'],
    ],
  },
  {
    id: 'xray',
    label: 'Конфигурации Xray',
    icon: 'terminal',
    items: [
      ['#/xray?tab=config', 'Конфиг ноды'],
      ['#/xray?tab=reality', 'Reality-ключи'],
      ['#/nodes?tab=agents', 'Агенты нод'],
    ],
  },
  { href: '#/api-docs', label: 'Документация API', icon: 'book' },
];

function navKey(href) {
  return (href || '').split('?')[0];
}

const root = document.getElementById('app');
let shell = null;
let contentEl = null;
let currentRoute = '#/dashboard';
let booted = false;
let miniTimer = null;

function currentHash() {
  const hash = window.location.hash || '#/dashboard';
  const base = hash.split('?')[0];
  return routes[base] ? base : '#/dashboard';
}

function brandHtml() {
  const title = state.panel.panel_title || 'DF_Xray';
  const subtitle = state.panel.panel_subtitle || 'Panel';
  return `
    <div class="brand-mark">DF</div>
    <div class="brand-name">${esc(title)}<small>${esc(subtitle)}</small></div>`;
}

function navBadge(kind) {
  if (kind === 'users') return '<span class="nav-badge" id="nav-users-count">—</span>';
  if (kind === 'update') return '<span class="nav-dot" id="nav-update-dot" hidden></span>';
  return '';
}

const GROUP_KEY = 'dfx_nav_groups';

function groupState() {
  try {
    return JSON.parse(localStorage.getItem(GROUP_KEY) || '{}') || {};
  } catch (err) {
    return {};
  }
}

function isGroupOpen(id) {
  const saved = groupState();
  return saved[id] === undefined ? true : Boolean(saved[id]);
}

function toggleGroup(id) {
  const saved = groupState();
  saved[id] = !isGroupOpen(id);
  try { localStorage.setItem(GROUP_KEY, JSON.stringify(saved)); } catch (err) { /* приватный режим */ }
}

function navHtml() {
  return NAV.map((item) => {
    if (item.items) {
      return `
        <div class="nav-group ${isGroupOpen(item.id) ? 'open' : ''}" data-group="${item.id}">
          <button class="nav-item nav-parent" data-toggle="${item.id}">
            ${icon(item.icon)}<span>${item.label}</span>
            ${navBadge(item.badge)}
            <span class="nav-caret">${icon('chevron')}</span>
          </button>
          <div class="nav-sub">
            ${item.items.map(([href, label]) => `
              <button class="nav-subitem" data-nav="${href}">${label}</button>`).join('')}
          </div>
        </div>`;
    }
    return `
      <button class="nav-item" data-nav="${item.href}">
        ${icon(item.icon)}<span>${item.label}</span>${navBadge(item.badge)}
      </button>`;
  }).join('');
}

function shellHtml() {
  return `
    <div class="app">
      <div class="drawer-backdrop" id="nav-backdrop" style="z-index:35"></div>
      <aside class="sidebar" id="sidebar">
        <div class="brand" id="brand">${brandHtml()}</div>
        <button class="nav-search" id="nav-search" type="button">
          ${icon('search')}<span>Поиск…</span><kbd>Ctrl K</kbd>
        </button>
        <div class="nav-label">Навигация</div>
        <nav class="nav" id="nav">${navHtml()}</nav>
        <div class="sidebar-foot">
          <button class="update-pill" id="update-pill" type="button" hidden>
            ${icon('refresh')}<span id="update-pill-text">Доступно обновление</span>
          </button>
          <div class="node-mini" id="node-mini">
            <div class="row"><span class="muted">Ноды</span><b>—</b></div>
          </div>
          <div class="acct">
            <div class="avatar" id="acct-avatar">?</div>
            <div class="acct-meta">
              <b id="acct-name">admin</b>
              <span>администратор</span>
            </div>
            <button class="icon-btn" id="logout" title="Выйти">${icon('logout')}</button>
          </div>
        </div>
      </aside>
      <div class="main">
        <header class="topbar">
          <button class="icon-btn menu-toggle" id="menu-toggle" title="Меню">${icon('menu')}</button>
          <div style="min-width:0">
            <h1 id="page-title">Дашборд</h1>
            <div class="sub" id="page-sub"></div>
          </div>
          <div class="topbar-actions" id="topbar-actions"></div>
        </header>
        <main class="content" id="content"></main>
      </div>
    </div>`;
}

function setActions(html) {
  const old = document.getElementById('topbar-actions');
  const fresh = document.createElement('div');
  fresh.className = 'topbar-actions';
  fresh.id = 'topbar-actions';
  fresh.innerHTML = html;
  old.replaceWith(fresh);
  return fresh;
}

function hashParams(hash) {
  return new URLSearchParams((hash || '').split('?')[1] || '');
}

function setActiveNav(hash) {
  const base = navKey(hash);
  document.querySelectorAll('[data-nav]').forEach((el) => {
    const key = navKey(el.dataset.nav);
    let active = key === base && el.dataset.nav === hash;
    if (key === base && key === '#/settings' && el.dataset.nav.includes('section=')) {
      const current = hashParams(hash).get('section') || 'general';
      active = hashParams(el.dataset.nav).get('section') === current;
    }
    if (key === base && key === '#/xray' && el.dataset.nav.includes('tab=')) {
      const current = hashParams(hash).get('tab') || 'config';
      active = hashParams(el.dataset.nav).get('tab') === current;
    }
    el.classList.toggle('active', active);
    if (active) {
      const group = el.closest('.nav-group');
      if (group) group.classList.add('open');
    }
  });
  document.querySelectorAll('.nav-group').forEach((group) => {
    const hasActive = Boolean(group.querySelector('.nav-subitem.active'));
    group.classList.toggle('child-active', hasActive);
    if (hasActive) group.classList.add('open');
  });
}

function closeMobileNav() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('nav-backdrop');
  if (sidebar) sidebar.classList.remove('open');
  if (backdrop) backdrop.classList.remove('show');
}

async function refreshNodeMini() {
  try {
    const data = await api('/api/nodes');
    const host = document.getElementById('node-mini');
    if (host) {
      const online = data.summary.online;
      const total = data.summary.total;
      const tone = online === 0 ? 'offline' : online < total ? 'limited' : 'online';
      const label = online === 0 ? 'нет связи' : online < total ? 'частично' : 'связь есть';
      host.innerHTML = `
        <div class="row"><span class="muted">Ноды</span>
          <b>${online}<span class="muted" style="font-weight:400">/${total}</span></b></div>
        <div class="row" style="margin-top:4px">
          <span class="muted" style="font-size:11px">онлайн</span>
          <span class="status ${tone}" style="font-size:10.5px;padding:1px 7px">
            <span class="dot"></span>${label}</span>
        </div>`;
    }
    state.nodes = data.items;
  } catch (err) { /* тихо */ }
}

export function navigate(hash) {
  if (!hash) return;
  if (window.location.hash === hash) renderRoute();
  else window.location.hash = hash;
}

async function renderRoute() {
  const hash = currentHash();
  currentRoute = hash;
  const route = routes[hash];
  if (!contentEl) return;
  setActiveNav(window.location.hash || hash);
  document.getElementById('page-title').textContent = route.title;
  document.getElementById('page-sub').textContent = route.subtitle;
  closeMobileNav();
  clearBindings(contentEl);
  contentEl.replaceChildren();
  try {
    await route.view.render(contentEl, { setActions, navigate });
  } catch (err) {
    if (err && err.status === 401) return; // обработчик unauthorized покажет вход
    contentEl.innerHTML = `
      <div class="empty">
        ${icon('alert')}
        <b>Не удалось загрузить раздел</b>
        <p>${esc(err.message || 'Неизвестная ошибка')}</p>
        <button class="btn" style="margin-top:14px" onclick="location.reload()">${icon('refresh')}Перезагрузить</button>
      </div>`;
  }
  if (hash === '#/users' && window.__dfxPendingNewUser) {
    window.__dfxPendingNewUser = false;
    usersView.openUserForm();
  }
}

function bindShell() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('nav-backdrop');

  sidebar.addEventListener('click', (ev) => {
    const toggle = ev.target.closest('[data-toggle]');
    if (toggle) {
      const id = toggle.dataset.toggle;
      const group = toggle.closest('.nav-group');
      toggleGroup(id);
      if (group) group.classList.toggle('open');
      return;
    }
    const navItem = ev.target.closest('[data-nav]');
    if (navItem) {
      navigate(navItem.dataset.nav);
      closeMobileNav();
    }
  });

  const searchBtn = document.getElementById('nav-search');
  if (searchBtn) searchBtn.addEventListener('click', () => openPalette({ navigate }));

  const updatePill = document.getElementById('update-pill');
  if (updatePill) {
    updatePill.addEventListener('click', () => navigate('#/settings?section=update'));
  }

  document.getElementById('menu-toggle').addEventListener('click', () => {
    sidebar.classList.add('open');
    backdrop.classList.add('show');
  });
  backdrop.addEventListener('click', closeMobileNav);

  document.getElementById('logout').addEventListener('click', async () => {
    try {
      await api('/api/auth/logout', { method: 'POST' });
    } catch (err) { /* игнорируем */ }
    state.me = null;
    booted = false;
    showLogin();
  });

  const acctName = document.getElementById('acct-name');
  const acctAvatar = document.getElementById('acct-avatar');
  if (state.me) {
    acctName.textContent = state.me.username;
    acctAvatar.textContent = state.me.username.slice(0, 1).toUpperCase();
  }
  document.getElementById('brand').innerHTML = brandHtml();
  document.title = `${state.panel.panel_title || 'DF_Xray'} · Панель`;
  refreshNodeMini();
  if (miniTimer) clearInterval(miniTimer);
  miniTimer = setInterval(refreshNodeMini, 60000);
}

function showLogin() {
  shell = null;
  contentEl = null;
  document.body.innerHTML = '';
  const mount = document.createElement('div');
  mount.id = 'app';
  document.body.appendChild(mount);
  renderLogin(mount, { onSuccess: async () => { await boot(); } });
}

async function boot() {
  let me;
  try {
    me = await api('/api/me');
  } catch (err) {
    showLogin();
    return;
  }
  state.me = me.admin;
  state.panel = me.panel;
  state.version = me.version;
  state.bootstrapPassword = Boolean(me.bootstrap_password);
  state.baseUrl = me.base_url;

  try {
    state.settings = await api('/api/settings');
  } catch (err) {
    state.settings = {};
  }

  let usersSummary = null;
  try {
    const users = await api('/api/users?limit=1');
    usersSummary = users.summary;
  } catch (err) { /* тихо */ }

  document.body.innerHTML = `<div id="app">${shellHtml()}</div>`;
  contentEl = document.getElementById('content');
  shell = document.getElementById('app');
  bindShell();

  const badge = document.getElementById('nav-users-count');
  if (badge && usersSummary) badge.textContent = usersSummary.total;

  if (!window.location.hash || !routes[currentHash()]) {
    window.location.hash = '#/dashboard';
  }
  await renderRoute();
  booted = true;
  refreshUpdateBadge();

  if (state.bootstrapPassword) {
    toast('Смените пароль администратора по умолчанию', 'err', 6000);
  }
}

window.addEventListener('hashchange', () => {
  if (booted) renderRoute();
});

document.addEventListener('keydown', (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && String(ev.key).toLowerCase() === 'k') {
    ev.preventDefault();
    if (booted) openPalette({ navigate });
  }
});

async function refreshUpdateBadge() {
  try {
    const data = await api('/api/updates');
    state.update = data;
  } catch (err) {
    return;
  }
  const pill = document.getElementById('update-pill');
  const text = document.getElementById('update-pill-text');
  const dot = document.getElementById('nav-update-dot');
  const available = Boolean(state.update && state.update.update_available);
  if (pill) pill.hidden = !available;
  if (text) text.textContent = available ? `Обновление ${state.update.latest}` : 'Доступно обновление';
  if (dot) dot.hidden = !available;
}

window.addEventListener('dfx:unauthorized', () => {
  if (booted) {
    booted = false;
    showLogin();
  }
});

window.addEventListener('dfx:new-user', () => {
  window.__dfxPendingNewUser = true;
  navigate('#/users');
});

window.addEventListener('dfx:panel-updated', () => {
  const brand = document.getElementById('brand');
  if (brand) brand.innerHTML = brandHtml();
  document.title = `${state.panel.panel_title || 'DF_Xray'} · Панель`;
});

const originalRender = renderRoute;
void originalRender;

boot();
