/* Палитра команд (Ctrl+K): быстрый переход по разделам, клиентам, узлам и хостам. */

import { api, esc, icon } from './core.js';

const PAGES = [
  ['#/dashboard', 'Дашборд', 'Сводка по трафику и нодам', 'grid'],
  ['#/inbounds', 'Входящие', 'Протоколы, транспорт и Reality-цели', 'inbox'],
  ['#/users', 'Клиенты', 'Доступы, лимиты и подписки', 'users'],
  ['#/groups', 'Группы', 'Объединения клиентов', 'layers'],
  ['#/nodes', 'Узлы', 'Серверы Xray и агенты', 'server'],
  ['#/nodes?tab=agents', 'Агенты нод', 'Heartbeat, версии и ревизии конфигов', 'terminal'],
  ['#/nodes?new=1', 'Добавить сервер', 'Новая нода: адрес, протокол, установка', 'plus'],
  ['#/hosts', 'Хосты', 'Домены-маски и SNI', 'globe'],
  ['#/outbounds', 'Исходящие', 'Маршруты наружу', 'upload'],
  ['#/routing', 'Маршрутизация', 'Правила и DNS', 'route'],
  ['#/xray', 'Конфигурации Xray', 'Конфиг ноды и Reality-ключи', 'terminal'],
  ['#/settings?section=general', 'Настройки панели', 'Общие, подписка, безопасность', 'settings'],
  ['#/settings?section=update', 'Обновление панели', 'Проверка версий и установка', 'refresh'],
  ['#/api-docs', 'Документация API', 'Все эндпоинты панели', 'book'],
];

let cache = { users: [], nodes: [], hosts: [], at: 0 };

async function loadData() {
  const fresh = Date.now() - cache.at < 20000;
  if (fresh) return cache;
  try {
    const [users, nodes, hosts] = await Promise.all([
      api('/api/users?limit=200').catch(() => ({ items: [] })),
      api('/api/nodes').catch(() => ({ items: [] })),
      api('/api/hosts').catch(() => ({ items: [] })),
    ]);
    cache = {
      users: users.items || [],
      nodes: nodes.items || [],
      hosts: hosts.items || [],
      at: Date.now(),
    };
  } catch (err) { /* работаем без данных */ }
  return cache;
}

function score(haystack, needle) {
  const text = haystack.toLowerCase();
  const query = needle.toLowerCase();
  if (!query) return 1;
  if (text === query) return 100;
  if (text.startsWith(query)) return 60;
  if (text.includes(query)) return 30;
  const words = query.split(/\s+/);
  if (words.every((word) => text.includes(word))) return 12;
  return 0;
}

function buildItems(query, data) {
  const items = [];
  PAGES.forEach(([href, title, subtitle, iconName]) => {
    const value = score(`${title} ${subtitle}`, query);
    if (value) items.push({ kind: 'Раздел', title, subtitle, href, icon: iconName, value });
  });
  (data.nodes || []).forEach((node) => {
    const value = score(`${node.name} ${node.address}`, query);
    if (value) {
      items.push({
        kind: 'Узел',
        title: node.name,
        subtitle: `${node.address}:${node.port} · ${node.protocol}/${node.transport}`,
        href: '#/nodes',
        icon: 'server',
        value: value + 2,
      });
    }
  });
  (data.users || []).forEach((user) => {
    const value = score(`${user.username} ${user.email || ''} ${user.note || ''}`, query);
    if (value) {
      items.push({
        kind: 'Клиент',
        title: user.username,
        subtitle: `${user.used_human} · ${user.status === 'active' ? 'активен' : user.status}`,
        href: `#/users?q=${encodeURIComponent(user.username)}`,
        icon: 'user',
        value: value + 2,
      });
    }
  });
  (data.hosts || []).forEach((host) => {
    const value = score(host.host, query);
    if (value) {
      items.push({
        kind: 'Хост',
        title: host.host,
        subtitle: `нод: ${host.nodes_count}`,
        href: '#/hosts',
        icon: 'globe',
        value: value + 1,
      });
    }
  });
  return items.sort((a, b) => b.value - a.value).slice(0, 24);
}

export function openPalette({ navigate }) {
  if (document.querySelector('.palette-layer')) return;

  const layer = document.createElement('div');
  layer.className = 'palette-layer';
  layer.innerHTML = `
    <div class="palette" role="dialog" aria-label="Быстрый переход">
      <div class="palette-input">
        ${icon('search')}
        <input class="input" id="palette-q" placeholder="Раздел, клиент, узел или хост…" autocomplete="off" spellcheck="false">
        <kbd>Esc</kbd>
      </div>
      <div class="palette-list" id="palette-list"></div>
      <div class="palette-foot">
        <span><kbd>↑</kbd><kbd>↓</kbd> выбор</span>
        <span><kbd>Enter</kbd> перейти</span>
        <span class="spacer"></span>
        <span>${icon('bolt')}Ctrl K</span>
      </div>
    </div>`;
  document.body.appendChild(layer);

  const input = layer.querySelector('#palette-q');
  const list = layer.querySelector('#palette-list');
  let active = 0;
  let items = [];

  const close = () => {
    layer.remove();
    document.removeEventListener('keydown', onKey, true);
  };

  const render = (query) => {
    items = buildItems(query, cache);
    active = Math.min(active, Math.max(items.length - 1, 0));
    if (!items.length) {
      list.innerHTML = '<div class="palette-empty">Ничего не найдено</div>';
      return;
    }
    let lastKind = '';
    list.innerHTML = items.map((item, index) => {
      const header = item.kind !== lastKind ? `<div class="palette-group">${item.kind}</div>` : '';
      lastKind = item.kind;
      return `${header}
        <button class="palette-item ${index === active ? 'active' : ''}" data-index="${index}">
          <span class="pi-icon">${icon(item.icon)}</span>
          <span class="pi-text"><b>${esc(item.title)}</b><small>${esc(item.subtitle)}</small></span>
          <span class="pi-go">↵</span>
        </button>`;
    }).join('');
    const current = list.querySelector('.palette-item.active');
    if (current) current.scrollIntoView({ block: 'nearest' });
  };

  const go = (item) => {
    if (!item) return;
    close();
    navigate(item.href);
  };

  const onKey = (ev) => {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      close();
    } else if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      active = Math.min(active + 1, items.length - 1);
      render(input.value.trim());
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      active = Math.max(active - 1, 0);
      render(input.value.trim());
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      go(items[active]);
    }
  };

  layer.addEventListener('click', (ev) => {
    if (ev.target === layer) close();
    const item = ev.target.closest('.palette-item');
    if (item) go(items[Number(item.dataset.index)]);
  });

  input.addEventListener('input', () => {
    active = 0;
    render(input.value.trim());
  });
  document.addEventListener('keydown', onKey, true);

  render('');
  input.focus();
  loadData().then(() => render(input.value.trim()));
}
