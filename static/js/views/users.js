/* Пользователи: таблица, фильтры, карточка с QR/подпиской, форма создания. */

import {
  api, bind, closeLayer, confirmDialog, copy, esc, fmtBytes, fmtDate, fmtDateTime, icon,
  initials, openDrawer, relTime, state, statusBadge, toast, usageBar, daysLabel,
} from '../core.js';

const filters = { q: '', status: 'all', sort: 'created_desc' };
let cache = { items: [], summary: {}, nodes: [] };

function avatarStyle(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 360;
  const hue = 200 + (hash % 140);
  return `background:linear-gradient(135deg,hsl(${hue} 72% 58%),hsl(${(hue + 40) % 360} 70% 45%))`;
}

async function loadAll() {
  const [users, nodes] = await Promise.all([api('/api/users?limit=1000'), api('/api/nodes')]);
  cache = { items: users.items, summary: users.summary, nodes: nodes.items };
  return cache;
}

function applyFilters() {
  let items = cache.items.slice();
  if (filters.q) {
    const q = filters.q.toLowerCase();
    items = items.filter((u) =>
      u.username.toLowerCase().includes(q)
      || (u.email || '').toLowerCase().includes(q)
      || (u.note || '').toLowerCase().includes(q)
      || u.uuid.includes(q));
  }
  if (filters.status !== 'all') items = items.filter((u) => u.status === filters.status);
  if (filters.sort === 'traffic_desc') items.sort((a, b) => b.used_bytes - a.used_bytes);
  else if (filters.sort === 'traffic_asc') items.sort((a, b) => a.used_bytes - b.used_bytes);
  else if (filters.sort === 'name') items.sort((a, b) => a.username.localeCompare(b.username));
  else if (filters.sort === 'expires') {
    items.sort((a, b) => (a.expires_at || '9999').localeCompare(b.expires_at || '9999'));
  } else items.sort((a, b) => b.id - a.id);
  return items;
}

function rowHtml(user) {
  const expiry = user.expires_at
    ? `<div>${fmtDate(user.expires_at)}</div><div class="muted" style="font-size:11px">${esc(daysLabel(user.days_left))}</div>`
    : '<span class="muted">бессрочно</span>';
  return `
    <tr data-id="${user.id}" data-act="open" style="cursor:pointer">
      <td>
        <div class="cell-user">
          <div class="avatar" style="${avatarStyle(user.username)}">${esc(initials(user.username))}</div>
          <div class="meta">
            <b>${esc(user.username)}</b>
            <span>${esc(user.email || user.note || '—')}</span>
          </div>
        </div>
      </td>
      <td>${statusBadge(user.status)}</td>
      <td>${usageBar(user.used_bytes, user.limit_bytes)}</td>
      <td>${expiry}</td>
      <td class="mono muted nowrap" style="font-size:11.5px">${user.device_limit || '—'}</td>
      <td class="actions">
        <span class="row-actions">
          <button class="icon-btn" data-act="qr" data-id="${user.id}" title="QR-код">${icon('qr')}</button>
          <button class="icon-btn" data-act="edit" data-id="${user.id}" title="Редактировать">${icon('edit')}</button>
          <button class="icon-btn" data-act="toggle" data-id="${user.id}" title="${user.enabled ? 'Отключить' : 'Включить'}">${icon('power')}</button>
          <button class="icon-btn" data-act="delete" data-id="${user.id}" title="Удалить">${icon('trash')}</button>
        </span>
      </td>
    </tr>`;
}

function tableHtml() {
  const items = applyFilters();
  if (!items.length) {
    return `<div class="empty" style="margin:16px">
      <b>Ничего не найдено</b>
      <p>Измените фильтр или создайте нового пользователя.</p>
    </div>`;
  }
  return `
    <div class="table-wrap">
      <table class="data">
        <thead>
          <tr>
            <th>Пользователь</th>
            <th>Статус</th>
            <th style="min-width:160px">Трафик</th>
            <th>Подписка до</th>
            <th>Устройств</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${items.map(rowHtml).join('')}</tbody>
      </table>
    </div>`;
}

function userLinksHtml(user) {
  if (!user.links || !user.links.length) {
    return `<div class="empty" style="padding:22px"><b>Нет доступных нод</b><p>Добавьте ноду, чтобы получить конфигурации.</p></div>`;
  }
  return user.links.map((link) => `
    <div class="card" style="margin-bottom:10px;background:var(--panel-2)">
      <div class="card-body tight" style="padding:12px 13px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <b style="font-size:13px">${esc(link.node_name)}</b>
          <span class="chips">
            <span class="chip accent">${esc(link.protocol.toUpperCase())}</span>
            <span class="chip">${esc(link.transport)}</span>
            <span class="chip">${esc(link.security)}</span>
            <span class="chip">${esc(link.address)}:${link.port}</span>
          </span>
          <button class="btn btn-sm" style="margin-left:auto" data-act="copy-link" data-link="${esc(link.link)}">${icon('copy')}Копировать</button>
        </div>
        <div class="mono" style="font-size:11px;color:#8b97b3;word-break:break-all;margin-top:9px;line-height:1.6">${esc(link.link)}</div>
      </div>
    </div>`).join('');
}

function detailHtml(user, nodes, nodeId) {
  const node = nodes.find((n) => n.id === nodeId) || nodes[0];
  const qrSrc = node
    ? `/api/users/${user.id}/qr.svg?node_id=${node.id}&v=${Date.now()}`
    : '';
  const statusHint = {
    active: 'Доступ разрешён, конфигурации выдаются.',
    disabled: 'Пользователь отключён вручную — конфигурации не выдаются.',
    expired: 'Срок действия истёк — продлите подписку.',
    limited: 'Исчерпан лимит трафика — увеличьте лимит или сбросьте статистику.',
  }[user.status] || '';
  return `
    <div class="grid grid-2" style="gap:10px">
      <div class="tile-like" style="background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:10px 12px">
        <div class="muted" style="font-size:10.5px;letter-spacing:.08em;text-transform:uppercase">Статус</div>
        <div style="margin-top:5px">${statusBadge(user.status)}</div>
      </div>
      <div style="background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:10px 12px">
        <div class="muted" style="font-size:10.5px;letter-spacing:.08em;text-transform:uppercase">Подписка до</div>
        <div style="margin-top:5px;font-weight:600">${user.expires_at ? esc(fmtDate(user.expires_at)) : 'бессрочно'}
          <span class="muted" style="font-weight:400;font-size:11.5px">${user.expires_at ? esc(daysLabel(user.days_left)) : ''}</span>
        </div>
      </div>
    </div>
    <p class="muted" style="font-size:12px;margin-top:10px">${esc(statusHint)}</p>

    <div style="margin-top:16px">${usageBar(user.used_bytes, user.limit_bytes)}</div>
    <div style="display:flex;gap:16px;margin-top:8px;font-size:11.5px;color:var(--muted)">
      <span>↑ ${fmtBytes(user.up_bytes)}</span>
      <span>↓ ${fmtBytes(user.down_bytes)}</span>
      <span>лимит: ${user.limit_bytes ? fmtBytes(user.limit_bytes) : '∞'}</span>
      ${user.device_limit ? `<span>устройств: ${user.device_limit}</span>` : ''}
    </div>

    <div style="margin-top:18px">
      <div class="muted" style="font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px">Ссылка подписки</div>
      <div class="sub-url-row">
        <input class="input" value="${esc(user.sub_url)}" readonly onclick="this.select()">
        <button class="icon-btn" data-act="copy-sub" title="Копировать">${icon('copy')}</button>
        <a class="icon-btn" href="${esc(user.sub_page_url)}" target="_blank" rel="noopener" title="Открыть страницу">${icon('external')}</a>
      </div>
    </div>

    ${node ? `
    <div style="margin-top:16px">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:7px">
        <div class="muted" style="font-size:10.5px;letter-spacing:.1em;text-transform:uppercase">QR-код</div>
        ${nodes.length > 1 ? `<div class="segmented" style="margin-left:auto">${nodes.map((n) => `
          <button data-node="${n.id}" class="${n.id === node.id ? 'active' : ''}" style="font-size:11.5px">${esc(n.name)}</button>`).join('')}</div>` : `<span class="muted" style="font-size:11.5px">· ${esc(node.name)}</span>`}
      </div>
      <div class="qr-box"><img src="${qrSrc}" alt="QR-код" width="240" height="240"></div>
    </div>` : ''}

    <div style="margin-top:18px">
      <div class="muted" style="font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px">Конфигурации</div>
      ${userLinksHtml(user)}
    </div>

    <div style="margin-top:18px">
      <div class="muted" style="font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px">Служебное</div>
      <div class="kv"><span>UUID</span><b class="mono" style="font-size:11px">${esc(user.uuid)}</b></div>
      <div class="kv"><span>Токен подписки</span><b class="mono" style="font-size:11px">${esc(user.sub_token)}</b></div>
      <div class="kv"><span>Создан</span><b>${esc(fmtDateTime(user.created_at))}</b></div>
      <div class="kv"><span>Последний онлайн</span><b>${esc(relTime(user.last_online_at))}</b></div>
      <div class="kv"><span>Запрос подписки</span><b>${esc(relTime(user.last_sub_at))}</b></div>
      <div class="kv"><span>Ноды</span><b>${user.node_ids.length ? user.node_ids.length + ' из ' + nodes.length : 'все'}</b></div>
      ${user.note ? `<div class="kv"><span>Заметка</span><b style="max-width:60%;text-align:right">${esc(user.note)}</b></div>` : ''}
    </div>
  `;
}

async function openUserDetail(userId) {
  const [user, nodesResponse] = await Promise.all([
    api(`/api/users/${userId}`),
    api('/api/nodes'),
  ]);
  const nodes = nodesResponse.items.filter((n) => n.enabled);
  let nodeId = nodes[0] ? nodes[0].id : 0;

  const drawer = openDrawer({
    title: user.username,
    subtitle: esc(user.email || 'без e-mail'),
    body: detailHtml(user, nodes, nodeId),
    footer: `
      <button class="btn btn-danger btn-icon" data-act="delete" title="Удалить">${icon('trash')}</button>
      <button class="btn" data-act="toggle">${icon('power')}${user.enabled ? 'Отключить' : 'Включить'}</button>
      <button class="btn btn-primary" data-act="edit">${icon('edit')}Редактировать</button>`,
  });

  const rerender = async () => {
    const fresh = await api(`/api/users/${userId}`);
    drawer.querySelector('.drawer-body').innerHTML = detailHtml(fresh, nodes, nodeId);
    const toggleBtn = drawer.querySelector('[data-act="toggle"]');
    toggleBtn.innerHTML = `${icon('power')}${fresh.enabled ? 'Отключить' : 'Включить'}`;
    await refreshTable();
    return fresh;
  };

  drawer.addEventListener('click', async (ev) => {
    const nodeBtn = ev.target.closest('[data-node]');
    if (nodeBtn) {
      nodeId = Number(nodeBtn.dataset.node);
      const img = drawer.querySelector('.qr-box img');
      if (img) img.src = `/api/users/${userId}/qr.svg?node_id=${nodeId}&v=${Date.now()}`;
      drawer.querySelectorAll('[data-node]').forEach((btn) => {
        btn.classList.toggle('active', btn === nodeBtn);
      });
      return;
    }
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    try {
      if (act === 'copy-link') {
        await copy(el.dataset.link, 'Ссылка скопирована');
      } else if (act === 'copy-sub') {
        await copy(user.sub_url, 'Ссылка подписки скопирована');
      } else if (act === 'toggle') {
        await api(`/api/users/${userId}/action`, {
          method: 'POST', body: { action: user.enabled ? 'disable' : 'enable' },
        });
        toast(user.enabled ? 'Пользователь отключён' : 'Пользователь включён');
        const fresh = await rerender();
        user.enabled = fresh.enabled;
        user.status = fresh.status;
      } else if (act === 'edit') {
        closeLayer();
        openUserForm(user);
      } else if (act === 'delete') {
        const ok = await confirmDialog({
          title: 'Удалить пользователя?',
          text: `Пользователь <b>${esc(user.username)}</b> будет удалён вместе со статистикой и подпиской.`,
          confirmText: 'Удалить', danger: true,
        });
        if (!ok) return;
        await api(`/api/users/${userId}`, { method: 'DELETE' });
        toast('Пользователь удалён');
        closeLayer();
        await refreshTable();
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });

}

export function openUserForm(user = null) {
  const isEdit = Boolean(user);
  const nodes = cache.nodes || [];
  const selected = new Set(user ? user.node_ids : []);
  const defaults = state.settings || {};
  const daysDefault = Number(defaults.default_days ?? 30);

  const nodeChips = nodes.length
    ? nodes.map((node) => `
        <label class="switch" style="padding:6px 10px;border:1px solid var(--line);border-radius:9px;background:var(--panel-2)">
          <input type="checkbox" name="node_ids" value="${node.id}" ${selected.has(node.id) ? 'checked' : ''}>
          <span class="track" style="width:30px;height:18px"></span>
          <span class="label" style="font-size:12px">${esc(node.name)}</span>
        </label>`).join('')
    : '<span class="muted" style="font-size:12px">Нод пока нет — пользователь будет доступен на всех будущих нодах.</span>';

  const form = `
    <form id="user-form" autocomplete="off">
      <div class="form-grid">
        <div class="field">
          <label>Имя пользователя *</label>
          <input class="input" name="username" required maxlength="64" placeholder="например, alex"
                 value="${user ? esc(user.username) : ''}">
        </div>
        <div class="field">
          <label>E-mail</label>
          <input class="input" name="email" type="email" placeholder="необязательно"
                 value="${user ? esc(user.email) : ''}">
        </div>
        <div class="field">
          <label>Лимит трафика, ГБ</label>
          <input class="input" name="limit_gb" type="number" min="0" step="0.5"
                 value="${user ? user.limit_gb : Number(defaults.default_limit_gb ?? 0)}">
          <div class="hint">0 — без ограничений</div>
        </div>
        <div class="field">
          <label>Устройств одновременно</label>
          <input class="input" name="device_limit" type="number" min="0" step="1"
                 value="${user ? user.device_limit : Number(defaults.default_device_limit ?? 0)}">
          <div class="hint">0 — без ограничений (только для VLESS)</div>
        </div>
        ${isEdit ? `
        <div class="field">
          <label>Действует до</label>
          <input class="input" name="expires_at" type="date" value="${esc(user.expires_at)}">
          <div class="hint">Пусто — бессрочно</div>
        </div>` : `
        <div class="field">
          <label>Срок, дней</label>
          <input class="input" name="days" type="number" min="0" step="1" value="${daysDefault}">
          <div class="hint">0 — бессрочно</div>
        </div>`}
        <div class="field">
          <label>Flow (VLESS + TCP + TLS/Reality)</label>
          <select class="select" name="flow">
            <option value="">по умолчанию (нода)</option>
            <option value="xtls-rprx-vision" ${user && user.flow === 'xtls-rprx-vision' ? 'selected' : ''}>xtls-rprx-vision</option>
          </select>
        </div>
        <div class="field full">
          <label>Заметка</label>
          <textarea class="textarea" name="note" rows="2" placeholder="внутренний комментарий">${user ? esc(user.note) : ''}</textarea>
        </div>
        <div class="field full">
          <label>Доступ только к выбранным нодам</label>
          <div style="display:flex;flex-wrap:wrap;gap:8px">${nodeChips}</div>
          <div class="hint">Если ничего не выбрано — доступ ко всем нодам.</div>
        </div>
        <div class="field full">
          <label class="switch">
            <input type="checkbox" name="enabled" ${!user || user.enabled ? 'checked' : ''}>
            <span class="track"></span>
            <span class="label">Пользователь активен</span>
          </label>
        </div>
      </div>
    </form>`;

  const drawer = openDrawer({
    title: isEdit ? 'Редактирование пользователя' : 'Новый пользователь',
    subtitle: isEdit ? esc(user.username) : 'UUID и токен подписки создадутся автоматически',
    body: form,
    footer: `
      <button class="btn" data-act="cancel">Отмена</button>
      <button class="btn btn-primary" data-act="submit">${isEdit ? 'Сохранить' : 'Создать пользователя'}</button>`,
    onMount(root) {
      root.querySelector('[name="username"]').focus();
    },
  });

  const submit = async () => {
    const formEl = drawer.querySelector('#user-form');
    if (!formEl.reportValidity()) return;
    const data = Object.fromEntries(new FormData(formEl).entries());
    const nodesChecked = [...formEl.querySelectorAll('[name="node_ids"]:checked')].map((el) => Number(el.value));
    const payload = {
      username: data.username.trim(),
      email: data.email.trim(),
      limit_gb: Number(data.limit_gb || 0),
      device_limit: Number(data.device_limit || 0),
      flow: data.flow,
      note: data.note,
      enabled: formEl.querySelector('[name="enabled"]').checked,
      node_ids: nodesChecked,
    };
    if (isEdit) {
      payload.expires_at = data.expires_at || '';
    } else {
      payload.days = Number(data.days || 0);
    }
    const buttons = drawer.querySelectorAll('.drawer-foot .btn');
    buttons.forEach((b) => { b.disabled = true; });
    try {
      if (isEdit) {
        await api(`/api/users/${user.id}`, { method: 'PATCH', body: payload });
        toast('Изменения сохранены');
        closeLayer();
        await refreshTable();
        openUserDetail(user.id);
      } else {
        const created = await api('/api/users', { method: 'POST', body: payload });
        toast('Пользователь создан');
        closeLayer();
        await refreshTable();
        openUserDetail(created.id);
      }
    } catch (err) {
      toast(err.message, 'err');
      buttons.forEach((b) => { b.disabled = false; });
    }
  };

  drawer.querySelector('[data-act="submit"]').addEventListener('click', submit);
  drawer.querySelector('[data-act="cancel"]').addEventListener('click', () => closeLayer());
  drawer.querySelector('#user-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    submit();
  });
}

async function refreshTable() {
  await loadAll();
  const host = document.querySelector('#users-table');
  if (host) host.innerHTML = tableHtml();
  const badge = document.getElementById('nav-users-count');
  if (badge) badge.textContent = cache.summary.total;
  const counts = document.querySelector('#users-counts');
  if (counts) {
    counts.innerHTML = `
      <span class="muted">Всего: <b style="color:var(--text-dim)">${cache.summary.total}</b></span>
      <span class="muted">· активных <b style="color:var(--mint)">${cache.summary.active}</b></span>
      ${cache.summary.limited ? `<span class="muted">· лимит <b style="color:var(--amber)">${cache.summary.limited}</b></span>` : ''}
      ${cache.summary.expired ? `<span class="muted">· истекло <b style="color:var(--amber)">${cache.summary.expired}</b></span>` : ''}`;
  }
}

export async function render(container, { setActions }) {
  const actions = setActions(`
    <a class="btn" href="/api/users/export" download>${icon('download')}CSV</a>
    <button class="btn btn-primary" data-act="new">${icon('plus')}Новый пользователь</button>
  `);
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="new"]')) openUserForm();
  });

  container.innerHTML = `
    <div class="toolbar">
      <div class="search">
        ${icon('search')}
        <input class="input" id="user-search" placeholder="Поиск: имя, e-mail, заметка, UUID" value="${esc(filters.q)}">
      </div>
      <div class="segmented" id="status-filter"></div>
      <select class="select" id="sort-filter" style="width:auto;min-width:170px">
        <option value="created_desc">Сначала новые</option>
        <option value="traffic_desc">Больше трафика</option>
        <option value="name">По имени</option>
        <option value="expires">По дате окончания</option>
      </select>
      <div class="spacer"></div>
      <span id="users-counts" class="chips" style="gap:10px;font-size:12px"></span>
    </div>
    <div class="card"><div id="users-table"><div style="padding:20px">${
      Array.from({ length: 6 }).map(() => '<div class="skeleton" style="height:44px;margin-bottom:8px"></div>').join('')
    }</div></div></div>
  `;

  await loadAll();

  const statusHost = container.querySelector('#status-filter');
  const statuses = [
    ['all', 'Все'], ['active', 'Активные'], ['expired', 'Истекшие'],
    ['limited', 'Лимит'], ['disabled', 'Отключённые'],
  ];
  const renderSegmented = () => {
    statusHost.innerHTML = statuses.map(([value, label]) => `
      <button data-status="${value}" class="${filters.status === value ? 'active' : ''}">
        ${label}<span class="n">${value === 'all' ? cache.summary.total : (cache.summary[value] || 0)}</span>
      </button>`).join('');
  };
  renderSegmented();

  const sortSelect = container.querySelector('#sort-filter');
  sortSelect.value = filters.sort;
  sortSelect.addEventListener('change', () => {
    filters.sort = sortSelect.value;
    container.querySelector('#users-table').innerHTML = tableHtml();
  });

  const searchInput = container.querySelector('#user-search');
  let timer = null;
  searchInput.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      filters.q = searchInput.value.trim();
      container.querySelector('#users-table').innerHTML = tableHtml();
    }, 180);
  });

  statusHost.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-status]');
    if (!btn) return;
    filters.status = btn.dataset.status;
    renderSegmented();
    container.querySelector('#users-table').innerHTML = tableHtml();
  });

  await refreshTable();

  bind(container, 'click', async (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    const id = Number(el.dataset.id || 0);
    const act = el.dataset.act;
    try {
      if (act === 'open') {
        if (ev.target.closest('button')) return;
        openUserDetail(id);
      } else if (act === 'qr') {
        openUserDetail(id);
      } else if (act === 'edit') {
        const user = await api(`/api/users/${id}`);
        openUserForm(user);
      } else if (act === 'toggle') {
        const user = cache.items.find((u) => u.id === id);
        await api(`/api/users/${id}/action`, {
          method: 'POST', body: { action: user && user.enabled ? 'disable' : 'enable' },
        });
        toast(user && user.enabled ? 'Пользователь отключён' : 'Пользователь включён');
        await refreshTable();
      } else if (act === 'delete') {
        const user = cache.items.find((u) => u.id === id);
        const ok = await confirmDialog({
          title: 'Удалить пользователя?',
          text: `<b>${esc(user ? user.username : '')}</b> будет удалён вместе с подпиской и статистикой.`,
          confirmText: 'Удалить', danger: true,
        });
        if (!ok) return;
        await api(`/api/users/${id}`, { method: 'DELETE' });
        toast('Пользователь удалён');
        await refreshTable();
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });

}
