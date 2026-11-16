/* Исходящие: маршруты наружу, попадающие в конфиг Xray. */

import {
  api, bind, closeLayer, confirmDialog, esc, formChecked, formValue, icon, openModal, toast,
} from '../core.js';

const TYPES = [
  ['direct', 'Direct (freedom)'],
  ['block', 'Block (blackhole)'],
  ['socks', 'SOCKS5'],
  ['http', 'HTTP'],
  ['shadowsocks', 'Shadowsocks'],
  ['trojan', 'Trojan'],
];

function typeTitle(type) {
  const found = TYPES.find(([value]) => value === type);
  return found ? found[1] : type;
}

function rowHtml(item, isDefault) {
  return `
    <tr>
      <td>
        <div class="cell-main">${esc(item.name)}</div>
        <div class="cell-sub mono">${esc(item.tag)}</div>
      </td>
      <td><span class="chip chip-quiet">${esc(typeTitle(item.type))}</span></td>
      <td class="mono">${esc(item.address || '—')}${item.port ? `:${item.port}` : ''}</td>
      <td class="mono muted">${esc(item.username || '—')}</td>
      <td>${item.enabled ? '<span class="status online" style="font-size:10.5px"><span class="dot"></span>вкл</span>' : '<span class="status offline" style="font-size:10.5px"><span class="dot"></span>выкл</span>'}</td>
      <td>${isDefault ? '<span class="chip chip-accent">по умолчанию</span>' : '<span class="muted">—</span>'}</td>
      <td class="right nowrap">
        <button class="icon-btn" data-act="edit" data-id="${item.id}" title="Изменить">${icon('edit')}</button>
        <button class="icon-btn" data-act="delete" data-id="${item.id}" title="Удалить">${icon('trash')}</button>
      </td>
    </tr>`;
}

function openForm(item = null, onSaved = null) {
  const modal = openModal({
    title: item ? 'Изменить исходящий' : 'Новый исходящий',
    body: `
      <form id="outbound-form" autocomplete="off">
        <div class="form-grid">
          <div class="field">
            <label>Название *</label>
            <input class="input" name="name" required value="${esc(item ? item.name : '')}" placeholder="Например: Германия SOCKS">
          </div>
          <div class="field">
            <label>Тип</label>
            <select class="select" name="type">
              ${TYPES.map(([value, label]) => `<option value="${value}" ${(item ? item.type : 'direct') === value ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label>Тег в конфиге</label>
            <input class="input mono" name="tag" value="${esc(item ? item.tag : '')}" placeholder="генерируется из названия">
          </div>
          <div class="field">
            <label>Адрес</label>
            <input class="input mono" name="address" value="${esc(item ? item.address : '')}" placeholder="proxy.example.com">
          </div>
          <div class="field">
            <label>Порт</label>
            <input class="input" type="number" min="0" max="65535" name="port" value="${item ? item.port : ''}">
          </div>
          <div class="field">
            <label>Пользователь</label>
            <input class="input" name="username" value="${esc(item ? item.username : '')}">
          </div>
          <div class="field">
            <label>Пароль</label>
            <input class="input" name="password" type="password" placeholder="${item && item.password ? 'не менять' : ''}">
          </div>
          <div class="field">
            <label>SNI / TLS-сервер</label>
            <input class="input mono" name="sni" value="${esc(item ? item.sni : '')}">
          </div>
          <div class="field full">
            <label class="switch">
              <input type="checkbox" name="enabled" ${!item || item.enabled ? 'checked' : ''}>
              <span class="track"></span><span class="label">Включён в конфиг</span>
            </label>
          </div>
        </div>
      </form>`,
    footer: `
      <button class="btn" data-cancel>Отмена</button>
      <button class="btn btn-primary" data-save>${item ? 'Сохранить' : 'Создать'}</button>`,
  });
  modal.querySelector('[data-cancel]').addEventListener('click', () => closeLayer());
  modal.querySelector('[data-save]').addEventListener('click', async () => {
    const form = modal.querySelector('#outbound-form');
    const body = {
      name: formValue(form, 'name').trim(),
      type: formValue(form, 'type', 'direct'),
      tag: formValue(form, 'tag').trim(),
      address: formValue(form, 'address').trim(),
      port: Number(formValue(form, 'port', '0') || 0),
      username: formValue(form, 'username').trim(),
      sni: formValue(form, 'sni').trim(),
      enabled: formChecked(form, 'enabled'),
    };
    const password = formValue(form, 'password');
    if (password) body.password = password;
    if (!body.name) {
      toast('Укажите название', 'err');
      return;
    }
    try {
      if (item) await api(`/api/outbounds/${item.id}`, { method: 'PATCH', body });
      else await api('/api/outbounds', { method: 'POST', body });
      toast(item ? 'Исходящий обновлён' : 'Исходящий создан');
      closeLayer();
      if (onSaved) onSaved();
    } catch (err) { toast(err.message, 'err'); }
  });
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  const actions = setActions(`<button class="btn btn-primary" data-act="new">${icon('plus')}Новый исходящий</button>`);
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="new"]')) openForm(null, () => render(container, ctx));
  });

  container.innerHTML = '<div class="skeleton" style="height:260px"></div>';
  const data = await api('/api/outbounds?secrets=1');
  const items = data.items || [];
  const defaultTag = data.default || '';

  container.innerHTML = `
    <div class="toolbar">
      <span class="muted" style="font-size:12.5px">Исходящих: <b>${items.length}</b></span>
      <div class="spacer"></div>
      <div class="field-inline">
        <label>Основной</label>
        <select class="select" id="default-outbound" style="min-width:190px">
          <option value="">первый в списке</option>
          ${items.map((item) => `<option value="${esc(item.tag)}" ${item.tag === defaultTag ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="card">
      ${items.length ? `
        <div class="table-wrap">
          <table class="data">
            <thead><tr>
              <th>Исходящий</th><th>Тип</th><th>Адрес</th><th>Пользователь</th>
              <th>Статус</th><th>Маршрут</th><th></th>
            </tr></thead>
            <tbody>${items.map((item) => rowHtml(item, item.tag === defaultTag)).join('')}</tbody>
          </table>
        </div>` : `
        <div class="empty">
          ${icon('upload')}
          <b>Исходящих нет</b>
          <p>Конфиг использует direct и block. Добавьте SOCKS/HTTP/Shadowsocks, если нужен внешний прокси.</p>
        </div>`}
    </div>
    <p class="hint" style="margin-top:12px;line-height:1.7">
      Исходящие попадают в блок <code class="mono">outbounds</code> конфига Xray. Порядок и тег
      используются правилами маршрутизации.
    </p>`;

  const select = container.querySelector('#default-outbound');
  if (select) {
    select.addEventListener('change', async () => {
      try {
        await api('/api/settings', { method: 'PATCH', body: { route_default_outbound: select.value } });
        toast('Основной исходящий сохранён');
        render(container, ctx);
      } catch (err) { toast(err.message, 'err'); }
    });
  }

  bind(container, 'click', async (ev) => {
    const edit = ev.target.closest('[data-act="edit"]');
    const remove = ev.target.closest('[data-act="delete"]');
    if (edit) {
      const item = items.find((row) => String(row.id) === edit.dataset.id);
      openForm(item, () => render(container, ctx));
    } else if (remove) {
      const item = items.find((row) => String(row.id) === remove.dataset.id);
      const ok = await confirmDialog({
        title: `Удалить «${item.name}»?`,
        text: 'Исходящий исчезнет из конфига Xray на всех нодах.',
        confirmText: 'Удалить',
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/api/outbounds/${item.id}`, { method: 'DELETE' });
        toast('Исходящий удалён');
        render(container, ctx);
      } catch (err) { toast(err.message, 'err'); }
    }
  });
}
