/* Журнал действий: кто, что и когда менял в панели. */

import {
  api, auditIcon, auditLabel, esc, fmtDateTime, icon, relTime,
} from '../core.js';

export async function render(container, ctx) {
  const { setActions } = ctx;
  const actions = setActions(`<button class="btn" data-act="reload">${icon('refresh')}Обновить</button>`);
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="reload"]')) render(container, ctx);
  });

  container.innerHTML = '<div class="skeleton" style="height:320px"></div>';
  const data = await api('/api/audit?limit=150');
  const items = data.items;

  container.innerHTML = `
    <div class="toolbar">
      <span class="muted" style="font-size:12.5px">Всего записей: <b style="color:var(--text-dim)">${data.total}</b></span>
      <div class="spacer"></div>
      <div class="search" style="max-width:260px">
        ${icon('search')}<input class="input" id="audit-search" placeholder="Поиск по действию или объекту">
      </div>
    </div>
    <div class="card">
      <div id="audit-body">${rows(items)}</div>
    </div>`;

  const body = container.querySelector('#audit-body');
  const search = container.querySelector('#audit-search');
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    const filtered = q
      ? items.filter((item) => `${auditLabel(item.action)} ${item.target} ${item.detail} ${item.actor}`.toLowerCase().includes(q))
      : items;
    body.innerHTML = rows(filtered);
  });
}

function rows(items) {
  if (!items.length) {
    return `<div class="empty" style="margin:16px"><b>Записей нет</b><p>Здесь появятся входы, изменения пользователей и нод.</p></div>`;
  }
  return `
    <div class="table-wrap">
      <table class="data">
        <thead><tr>
          <th>Событие</th><th>Объект</th><th>Автор</th><th>IP</th><th>Когда</th>
        </tr></thead>
        <tbody>
          ${items.map((item) => `
            <tr>
              <td>
                <div style="display:flex;align-items:center;gap:9px">
                  <span class="audit-item" style="padding:0;border:0"><span class="ico">${icon(auditIcon(item.action))}</span></span>
                  <div>
                    <b style="font-size:12.5px">${esc(auditLabel(item.action))}</b>
                    ${item.detail ? `<div class="muted" style="font-size:11.5px">${esc(item.detail)}</div>` : ''}
                  </div>
                </div>
              </td>
              <td class="mono" style="font-size:11.5px">${esc(item.target || '—')}</td>
              <td>${esc(item.actor || '—')}</td>
              <td class="mono muted" style="font-size:11.5px">${esc(item.ip || '—')}</td>
              <td class="muted nowrap" style="font-size:11.5px" title="${esc(fmtDateTime(item.created_at))}">${esc(relTime(item.created_at))}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
