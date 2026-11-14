/* DF_Xray Panel — точка входа: оболочка, навигация, роутер. */

import { api, clearBindings, esc, icon, state, toast } from './core.js';
import { renderLogin } from './views/login.js';
import * as dashboardView from './views/dashboard.js';
import * as usersView from './views/users.js';
import * as subsView from './views/subs.js';
import * as nodesView from './views/nodes.js';
import * as auditView from './views/audit.js';
import * as settingsView from './views/settings.js';

const routes = {
  '#/dashboard': {
    title: 'Дашборд',
    subtitle: 'Сводка по пользователям, трафику и нодам',
    view: dashboardView,
    icon: 'grid',
    nav: false,
  },
  '#/users': {
    title: 'Пользователи',
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
  '#/settings': {
    title: 'Настройки',
    subtitle: 'Панель, подписки, маршрутизация и безопасность',
    view: settingsView,
    icon: 'settings',
    nav: true,
  },
};

const NAV_ITEMS = [
  ['#/dashboard', 'Дашборд', 'grid'],
  ['#/users', 'Пользователи', 'users'],
  ['#/subscriptions', 'Подписки', 'link'],
  ['#/nodes', 'Ноды', 'server'],
  ['#/audit', 'Журнал', 'activity'],
  ['#/settings', 'Настройки', 'settings'],
];

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

function navHtml() {
  return NAV_ITEMS.map(([href, label, iconName]) => `
    <button class="nav-item" data-nav="${href}">
      ${icon(iconName)}<span>${label}</span>
      ${href === '#/users' ? '<span class="nav-badge" id="nav-users-count">—</span>' : ''}
    </button>`).join('');
}

function shellHtml() {
  return `
    <div class="app">
      <div class="drawer-backdrop" id="nav-backdrop" style="z-index:35"></div>
      <aside class="sidebar" id="sidebar">
        <div class="brand" id="brand">${brandHtml()}</div>
        <div class="nav-label">Управление</div>
        <nav class="nav">${navHtml()}</nav>
        <div class="sidebar-foot">
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

function setActiveNav(hash) {
  document.querySelectorAll('[data-nav]').forEach((el) => {
    el.classList.toggle('active', el.dataset.nav === hash);
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
  setActiveNav(hash);
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
    const navItem = ev.target.closest('[data-nav]');
    if (navItem) {
      navigate(navItem.dataset.nav);
      closeMobileNav();
    }
  });

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

  if (state.bootstrapPassword) {
    toast('Смените пароль администратора по умолчанию', 'err', 6000);
  }
}

window.addEventListener('hashchange', () => {
  if (booted) renderRoute();
});

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
