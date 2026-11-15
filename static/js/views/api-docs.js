/* Документация API: список эндпоинтов панели и агентов нод. */

import { api, bind, copy, esc, icon, toast } from '../core.js';

const METHOD_CLASS = {
  GET: 'get', POST: 'post', PATCH: 'patch', DELETE: 'delete', PUT: 'put',
};

function groupOf(path) {
  if (path.startsWith('/api/agent/') || path.startsWith('/api/node/')) return 'Агент и установка';
  if (path.startsWith('/api/auth/') || path.startsWith('/api/account/')) return 'Сессии и аккаунт';
  if (path.startsWith('/api/users')) return 'Клиенты';
  if (path.startsWith('/api/groups')) return 'Группы';
  if (path.startsWith('/api/nodes')) return 'Узлы';
  if (path.startsWith('/api/outbounds')) return 'Исходящие';
  if (path.startsWith('/api/reality')) return 'Сканер Reality';
  if (path.startsWith('/api/updates')) return 'Обновления';
  if (path.startsWith('/api/settings')) return 'Настройки';
  if (path.startsWith('/api/subscriptions')) return 'Подписки';
  if (path.startsWith('/api/dashboard')) return 'Дашборд';
  if (path.startsWith('/api/audit')) return 'Журнал';
  if (path.startsWith('/api/maintenance')) return 'Обслуживание';
  if (path.startsWith('/api/docs')) return 'Документация';
  return 'Прочее';
}

function rowsHtml(items) {
  return items.map((item) => `
    <tr>
      <td><span class="method ${METHOD_CLASS[item.method] || ''}">${esc(item.method)}</span></td>
      <td class="mono path" data-path="${esc(item.path)}">${esc(item.path)}</td>
      <td>${item.agent ? '<span class="chip chip-quiet">токен ноды</span>' : !item.auth ? '<span class="chip chip-quiet">публичный</span>' : '<span class="chip chip-quiet">сессия</span>'}</td>
      <td class="right"><button class="icon-btn" data-copy="${esc(item.path)}" title="Копировать путь">${icon('copy')}</button></td>
    </tr>`).join('');
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  setActions(`<span class="muted" style="font-size:12px">CSRF: <code class="mono">X-Requested-With: DF_Xray</code></span>`);
  container.innerHTML = '<div class="skeleton" style="height:320px"></div>';
  const data = await api('/api/docs');
  const items = data.items || [];

  const ORDER = [
    'Дашборд', 'Клиенты', 'Группы', 'Узлы', 'Сканер Reality', 'Исходящие',
    'Маршрутизация', 'Подписки', 'Настройки', 'Обновления', 'Обслуживание',
    'Журнал', 'Агент и установка', 'Сессии и аккаунт', 'Документация', 'Прочее',
  ];
  const groups = new Map();
  items.forEach((item) => {
    const key = groupOf(item.path);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  const ordered = new Map(
    [...groups.entries()].sort((a, b) => {
      const first = ORDER.indexOf(a[0]);
      const second = ORDER.indexOf(b[0]);
      return (first < 0 ? 99 : first) - (second < 0 ? 99 : second);
    }),
  );
  groups.clear();
  ordered.forEach((value, key) => groups.set(key, value));

  container.innerHTML = `
    <div class="toolbar">
      <div class="search" style="max-width:320px">
        ${icon('search')}<input class="input" id="docs-q" placeholder="Поиск по эндпоинту">
      </div>
      <div class="spacer"></div>
      <span class="muted" style="font-size:12.5px">эндпоинтов: <b>${items.length}</b> · API v${data.version}</span>
    </div>
    <div id="docs-body">
      ${[...groups.entries()].map(([name, list]) => `
        <div class="card docs-group">
          <div class="card-head"><h3>${esc(name)}</h3><span class="chip chip-quiet">${list.length}</span></div>
          <div class="table-wrap">
            <table class="data compact">
              <thead><tr><th style="width:78px">Метод</th><th>Путь</th><th style="width:150px">Доступ</th><th></th></tr></thead>
              <tbody>${rowsHtml(list)}</tbody>
            </table>
          </div>
        </div>`).join('')}
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Базовые правила</h3></div>
      <div class="card-body">
        <div class="kv"><span>Базовый адрес</span><b class="mono">${esc(data.base || location.origin)}</b></div>
        <div class="kv"><span>Формат</span><b>JSON, кодировка UTF-8</b></div>
        <div class="kv"><span>Аутентификация</span><b>cookie-сессия панели или <code class="mono">X-Node-Token</code> для агентов</b></div>
        <div class="kv"><span>Ошибки</span><b><code class="mono">{ "error": "текст" }</code> и HTTP-код</b></div>
        <div class="kv"><span>Публичные подписки</span><b class="mono">/sub/&lt;token&gt;, /sub/&lt;token&gt;/info, /qr.svg</b></div>
      </div>
    </div>`;

  const search = container.querySelector('#docs-q');
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    container.querySelectorAll('.docs-group').forEach((group) => {
      let visible = 0;
      group.querySelectorAll('tbody tr').forEach((row) => {
        const path = row.querySelector('.path').dataset.path.toLowerCase();
        const match = !q || path.includes(q);
        row.style.display = match ? '' : 'none';
        if (match) visible += 1;
      });
      group.style.display = visible ? '' : 'none';
    });
  });

  bind(container, 'click', (ev) => {
    const btn = ev.target.closest('[data-copy]');
    if (!btn) return;
    copy(btn.dataset.copy);
    toast('Путь скопирован');
  });
}
