/* Подписки: ссылки, QR-коды, страница подписки и её оформление. */

import {
  api, bind, copy, esc, fmtDate, formChecked, formValue, icon, initials, openModal,
  relTime, statusBadge, toast,
} from '../core.js';

function avatarStyle(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 360;
  const hue = 200 + (hash % 140);
  return `background:linear-gradient(135deg,hsl(${hue} 72% 58%),hsl(${(hue + 40) % 360} 70% 45%))`;
}

function openQr(user) {
  const pageUrl = `${user.sub_page_url}`;
  openModal({
    title: `QR-код подписки · ${user.username}`,
    body: `
      <div class="qr-box" style="margin:0 auto;max-width:300px">
        <img src="/sub/${esc(user.sub_token)}/qr.svg" alt="QR-код подписки" width="300" height="300">
      </div>
      <p class="muted" style="font-size:12px;text-align:center;margin-top:12px">
        Отсканируйте в клиенте (v2rayNG, NekoBox, Streisand, Hiddify) или откройте
        <a href="${esc(pageUrl)}" target="_blank" rel="noopener" style="color:#a99cff">страницу подписки</a>.
      </p>
      <div class="sub-url-row" style="margin-top:14px">
        <input class="input" value="${esc(user.sub_url)}" readonly onclick="this.select()">
        <button class="icon-btn" data-act="copy-sub" title="Копировать">${icon('copy')}</button>
      </div>`,
    footer: `<button class="btn" data-act="open-page">${icon('external')}Открыть страницу</button>`,
    onMount(root) {
      root.addEventListener('click', async (ev) => {
        const el = ev.target.closest('[data-act]');
        if (!el) return;
        if (el.dataset.act === 'copy-sub') await copy(user.sub_url, 'Ссылка скопирована');
        if (el.dataset.act === 'open-page') window.open(pageUrl, '_blank', 'noopener');
      });
    },
  });
}

function rowsHtml(items) {
  if (!items.length) {
    return `<div class="empty" style="margin:16px"><b>Подписок нет</b>
      <p>Создайте пользователя — подписка появится автоматически.</p></div>`;
  }
  return `
    <div class="table-wrap">
      <table class="data">
        <thead><tr>
          <th>Пользователь</th><th>Статус</th><th>Ссылка подписки</th>
          <th>Запрос</th><th>Действует до</th><th></th>
        </tr></thead>
        <tbody>
          ${items.map((user) => `
            <tr>
              <td>
                <div class="cell-user">
                  <div class="avatar" style="${avatarStyle(user.username)}">${esc(initials(user.username))}</div>
                  <div class="meta"><b>${esc(user.username)}</b><span>${esc(user.email || '—')}</span></div>
                </div>
              </td>
              <td>${statusBadge(user.status)}</td>
              <td style="min-width:240px">
                <div style="display:flex;align-items:center;gap:8px">
                  <span class="mono" title="${esc(user.sub_url)}"
                        style="font-size:11.5px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px">/sub/${esc(user.sub_token)}</span>
                  <button class="icon-btn" data-act="copy" data-url="${esc(user.sub_url)}" title="Скопировать полный адрес">${icon('copy')}</button>
                </div>
              </td>
              <td class="muted" style="white-space:nowrap">${esc(relTime(user.last_sub_at))}</td>
              <td class="muted" style="white-space:nowrap">${user.expires_at ? esc(fmtDate(user.expires_at)) : 'бессрочно'}</td>
              <td class="actions">
                <span class="row-actions">
                  <button class="icon-btn" data-act="qr" data-token="${esc(user.sub_token)}" data-id="${user.id}" title="QR-код">${icon('qr')}</button>
                  <a class="icon-btn" href="${esc(user.sub_page_url)}" target="_blank" rel="noopener" title="Страница подписки">${icon('external')}</a>
                </span>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  const actions = setActions('');
  actions.innerHTML = `<a class="btn" href="#/users">${icon('users')}Пользователи</a>`;

  container.innerHTML = '<div class="skeleton" style="height:300px"></div>';
  const data = await api('/api/subscriptions');
  const items = data.items;
  const active = items.filter((u) => u.status === 'active').length;
  const recent = items.filter((u) => u.last_sub_at && Date.now() - new Date(u.last_sub_at).getTime() < 86400000).length;
  const byId = new Map(items.map((u) => [u.id, u]));

  container.innerHTML = `
    <div class="grid grid-3 section">
      <div class="card stat">
        <div class="stat-top"><div class="stat-ico blue">${icon('link')}</div><div class="stat-label">Всего подписок</div></div>
        <div class="stat-value">${items.length}</div>
        <div class="stat-foot">${active} активных</div>
      </div>
      <div class="card stat">
        <div class="stat-top"><div class="stat-ico mint">${icon('refresh')}</div><div class="stat-label">Запросы за сутки</div></div>
        <div class="stat-value">${recent}</div>
        <div class="stat-foot">клиенты обновили подписку</div>
      </div>
      <div class="card stat">
        <div class="stat-top"><div class="stat-ico">${icon('clock')}</div><div class="stat-label">Интервал обновления</div></div>
        <div class="stat-value">${data.settings.sub_update_interval}<small>ч</small></div>
        <div class="stat-foot">сообщается клиентам в заголовке</div>
      </div>
    </div>

    <div class="card section">
      <div class="card-head">
        <h3>Ссылки подписок</h3>
        <div class="spacer"></div>
        <div class="search" style="max-width:260px">
          ${icon('search')}
          <input class="input" id="sub-search" placeholder="Поиск пользователя">
        </div>
      </div>
      <div id="subs-table">${rowsHtml(items)}</div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h3>Оформление подписки</h3></div>
        <form class="card-body" id="sub-form">
          <div class="field" style="margin-bottom:12px">
            <label>Название профиля</label>
            <input class="input" name="sub_title" value="${esc(data.settings.sub_title)}" placeholder="DF_Xray">
            <div class="hint">Показывается в клиенте (заголовок profile-title).</div>
          </div>
          <div class="field" style="margin-bottom:12px">
            <label>Ссылка на поддержку</label>
            <input class="input" name="sub_support_url" value="${esc(data.settings.sub_support_url)}" placeholder="https://t.me/your_support">
          </div>
          <div class="form-grid">
            <div class="field">
              <label>Интервал обновления, ч</label>
              <input class="input" name="sub_update_interval" type="number" min="1" max="168" value="${data.settings.sub_update_interval}">
            </div>
            <div class="field">
              <label>Публичная страница</label>
              <label class="switch" style="margin-top:8px">
                <input type="checkbox" name="sub_page_enabled" ${data.settings.sub_page_enabled ? 'checked' : ''}>
                <span class="track"></span><span class="label">Включена</span>
              </label>
            </div>
          </div>
          <div class="field" style="margin-top:12px">
            <label class="switch">
              <input type="checkbox" name="sub_show_nodes" ${data.settings.sub_show_nodes ? 'checked' : ''}>
              <span class="track"></span><span class="label">Показывать список нод на странице подписки</span>
            </label>
          </div>
          <div style="margin-top:16px"><button class="btn btn-primary" type="submit">Сохранить</button></div>
        </form>
      </div>

      <div class="card">
        <div class="card-head"><h3>Как это работает</h3></div>
        <div class="card-body" style="font-size:13px;color:var(--text-dim);line-height:1.8">
          <p>Один адрес на пользователя:</p>
          <div class="code-block" style="max-height:none;white-space:pre-wrap">${esc(data.base_url)}/sub/&lt;токен&gt;</div>
          <p style="margin-top:12px">Панель отдаёт base64-список VLESS/VMess/Trojan-ссылок и заголовки:</p>
          <ul style="margin:6px 0 0;padding-left:18px">
            <li><code class="mono">subscription-userinfo</code> — расход и лимит</li>
            <li><code class="mono">profile-title</code> — название профиля</li>
            <li><code class="mono">profile-update-interval</code> — период автообновления</li>
            <li><code class="mono">profile-web-page-url</code> — страница подписки</li>
          </ul>
          <p style="margin-top:12px">Сама страница — тёмная витрина с QR-кодом, расходом трафика и кнопками копирования конфигураций.</p>
        </div>
      </div>
    </div>`;

  const tableHost = container.querySelector('#subs-table');
  const search = container.querySelector('#sub-search');
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    const filtered = q
      ? items.filter((u) => u.username.toLowerCase().includes(q) || (u.email || '').toLowerCase().includes(q))
      : items;
    tableHost.innerHTML = rowsHtml(filtered);
  });

  bind(container, 'click', async (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    if (el.dataset.act === 'copy') {
      await copy(el.dataset.url, 'Ссылка скопирована');
    } else if (el.dataset.act === 'qr') {
      const user = byId.get(Number(el.dataset.id));
      if (user) openQr(user);
    }
  });

  const form = container.querySelector('#sub-form');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const payload = {
      sub_title: formValue(form, 'sub_title').trim(),
      sub_support_url: formValue(form, 'sub_support_url').trim(),
      sub_update_interval: Number(formValue(form, 'sub_update_interval', '12') || 12),
      sub_page_enabled: formChecked(form, 'sub_page_enabled'),
      sub_show_nodes: formChecked(form, 'sub_show_nodes'),
    };
    try {
      await api('/api/settings', { method: 'PATCH', body: payload });
      toast('Настройки подписки сохранены');
    } catch (err) {
      toast(err.message, 'err');
    }
  });

}
