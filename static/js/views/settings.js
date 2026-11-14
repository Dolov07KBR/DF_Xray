/* Настройки панели: общие, подписка, маршрутизация, безопасность, обслуживание. */

import {
  api, bind, confirmDialog, esc, formChecked, formValue, icon, state, toast,
} from '../core.js';

const SECTIONS = [
  { id: 'general', label: 'Общие', icon: 'settings' },
  { id: 'subscription', label: 'Подписка', icon: 'link' },
  { id: 'routing', label: 'Маршрутизация', icon: 'globe' },
  { id: 'security', label: 'Безопасность', icon: 'shield' },
  { id: 'maintenance', label: 'Обслуживание', icon: 'refresh' },
  { id: 'about', label: 'О панели', icon: 'info' },
];

let activeSection = 'general';

function sw(name, label, checked, hint = '') {
  return `<div class="field">
    <label class="switch">
      <input type="checkbox" name="${name}" ${checked ? 'checked' : ''}>
      <span class="track"></span><span class="label">${label}</span>
    </label>
    ${hint ? `<div class="hint">${hint}</div>` : ''}
  </div>`;
}

function sectionHtml(id, settings) {
  if (id === 'general') {
    return `<form class="card" data-form="general">
      <div class="card-head"><h3>Общие настройки</h3></div>
      <div class="card-body">
        <div class="form-grid">
          <div class="field">
            <label>Название панели</label>
            <input class="input" name="panel_title" value="${esc(settings.panel_title)}">
          </div>
          <div class="field">
            <label>Подзаголовок</label>
            <input class="input" name="panel_subtitle" value="${esc(settings.panel_subtitle)}">
          </div>
          <div class="field full">
            <label>Публичный адрес панели</label>
            <input class="input mono" name="public_base_url" value="${esc(settings.public_base_url)}"
                   placeholder="https://panel.example.com">
            <div class="hint">Используется в ссылках подписок. Сейчас панель отвечает как
              <code class="mono">${esc(settings.base_url)}</code>. Оставьте пустым, чтобы определять автоматически.</div>
          </div>
          <div class="field full">
            <label>Подпись в футере</label>
            <input class="input" name="footer_note" value="${esc(settings.footer_note)}"
                   placeholder="Например: поддержка @dfxray_support">
          </div>
        </div>
        <div style="margin-top:16px"><button class="btn btn-primary" type="submit">Сохранить</button></div>
      </div>
    </form>`;
  }
  if (id === 'subscription') {
    return `<form class="card" data-form="subscription">
      <div class="card-head"><h3>Подписки</h3></div>
      <div class="card-body">
        <div class="form-grid">
          <div class="field">
            <label>Название профиля</label>
            <input class="input" name="sub_title" value="${esc(settings.sub_title)}">
            <div class="hint">Заголовок <code class="mono">profile-title</code> для клиентов.</div>
          </div>
          <div class="field">
            <label>Ссылка на поддержку</label>
            <input class="input" name="sub_support_url" value="${esc(settings.sub_support_url)}" placeholder="https://t.me/...">
          </div>
          <div class="field">
            <label>Интервал обновления, ч</label>
            <input class="input" name="sub_update_interval" type="number" min="1" max="168" value="${settings.sub_update_interval}">
          </div>
          <div class="field">
            <label>Срок подписки по умолчанию, дней</label>
            <input class="input" name="default_days" type="number" min="0" max="3650" value="${settings.default_days}">
          </div>
          <div class="field">
            <label>Лимит трафика по умолчанию, ГБ</label>
            <input class="input" name="default_limit_gb" type="number" min="0" step="0.5" value="${esc(settings.default_limit_gb)}">
            <div class="hint">0 — без лимита</div>
          </div>
          <div class="field">
            <label>Лимит устройств по умолчанию</label>
            <input class="input" name="default_device_limit" type="number" min="0" value="${settings.default_device_limit}">
          </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:12px;margin-top:16px">
          ${sw('sub_page_enabled', 'Публичная страница подписки', settings.sub_page_enabled, 'Адрес /sub/&lt;токен&gt;/page с QR-кодом и расходом.')}
          ${sw('sub_show_nodes', 'Показывать список нод на странице', settings.sub_show_nodes)}
        </div>
        <div style="margin-top:16px"><button class="btn btn-primary" type="submit">Сохранить</button></div>
      </div>
    </form>`;
  }
  if (id === 'routing') {
    return `<form class="card" data-form="routing">
      <div class="card-head">
        <div><h3>Маршрутизация и DNS</h3>
          <div class="hint">Применяется к новым конфигам нод при следующем опросе агента.</div></div>
      </div>
      <div class="card-body">
        <div class="form-grid">
          ${sw('block_bittorrent', 'Блокировать BitTorrent', settings.block_bittorrent, 'По протоколу bittorrent — снижает риск абуза.')}
          ${sw('block_ads', 'Блокировать рекламу', settings.block_ads, 'Через geosite:category-ads-all (нужен geosite.dat).')}
          ${sw('block_private', 'Блокировать приватные IP', settings.block_private, 'Защита от SSRF в локальную сеть.')}
          ${sw('route_ru_direct', 'Российские сайты — напрямую', settings.route_ru_direct, 'geosite:category-ru и geoip:ru идут мимо туннеля.')}
          <div class="field">
            <label>DNS</label>
            <select class="select" name="dns_preset">
              <option value="cloudflare" ${settings.dns_preset === 'cloudflare' ? 'selected' : ''}>Cloudflare 1.1.1.1</option>
              <option value="google" ${settings.dns_preset === 'google' ? 'selected' : ''}>Google 8.8.8.8</option>
              <option value="quad9" ${settings.dns_preset === 'quad9' ? 'selected' : ''}>Quad9 9.9.9.9</option>
              <option value="system" ${settings.dns_preset === 'system' ? 'selected' : ''}>Системный</option>
            </select>
          </div>
          <div class="field">
            <label>Период хранения статистики, дней</label>
            <input class="input" name="traffic_retention_days" type="number" min="7" max="3650" value="${settings.traffic_retention_days}">
            <div class="hint">Старые срезы трафика удаляются при обслуживании.</div>
          </div>
        </div>
        <div style="margin-top:16px"><button class="btn btn-primary" type="submit">Сохранить</button></div>
      </div>
    </form>`;
  }
  if (id === 'security') {
    return `
      <div class="card">
        <div class="card-head"><h3>Администратор</h3><div class="spacer"></div>
          <span class="chip accent">${esc(state.me ? state.me.username : '')}</span></div>
        <form class="card-body" data-form="password">
          <div class="form-grid">
            <div class="field full">
              <label>Текущий пароль</label>
              <input class="input" name="current_password" type="password" autocomplete="current-password" required>
            </div>
            <div class="field">
              <label>Новый пароль</label>
              <input class="input" name="new_password" type="password" autocomplete="new-password" minlength="8" required>
              <div class="hint">Минимум 8 символов.</div>
            </div>
            <div class="field">
              <label>Повторите пароль</label>
              <input class="input" name="repeat_password" type="password" autocomplete="new-password" minlength="8" required>
            </div>
          </div>
          <div style="margin-top:16px"><button class="btn btn-primary" type="submit">Сменить пароль</button></div>
        </form>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h3>Сессии</h3></div>
        <div class="card-body">
          <p class="muted" style="font-size:12.5px;margin-bottom:14px">
            Пароль хранится как PBKDF2-SHA256 (210 000 итераций), сессии — в SQLite, cookie HttpOnly + SameSite=Lax.
          </p>
          <button class="btn btn-danger" data-act="revoke">${icon('logout')}Завершить другие сессии</button>
        </div>
      </div>`;
  }
  if (id === 'maintenance') {
    return `
      <div class="card">
        <div class="card-head"><h3>База данных</h3></div>
        <div class="card-body">
          <div class="kv"><span>Движок</span><b>SQLite (WAL)</b></div>
          <div class="kv"><span>Период хранения трафика</span><b>${settings.traffic_retention_days} дней</b></div>
          <div class="kv"><span>Версия панели</span><b>${esc(settings.version)}</b></div>
          <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
            <a class="btn" href="/api/maintenance/backup" download>${icon('download')}Скачать бэкап</a>
            <button class="btn" data-act="purge">${icon('trash')}Очистить старую статистику</button>
          </div>
          <p class="muted" style="font-size:12px;margin-top:12px">
            Бэкап — копия SQLite-файла через встроенный backup API. Для регулярных копий
            тома <code class="mono">./data</code> достаточно rsync или restic.
          </p>
        </div>
      </div>`;
  }
  return `
    <div class="card">
      <div class="card-head"><h3>DF_Xray Panel</h3></div>
      <div class="card-body">
        <div class="kv"><span>Версия</span><b>${esc(settings.version)}</b></div>
        <div class="kv"><span>Лицензия</span><b>GPL-3.0</b></div>
        <div class="kv"><span>Стек</span><b>Python 3.11+ stdlib · SQLite · Vanilla JS</b></div>
        <div class="kv"><span>API для агентов</span><b class="mono" style="font-size:11.5px">/api/agent/*</b></div>
        <div class="kv"><span>Публичная подписка</span><b class="mono" style="font-size:11.5px">/sub/&lt;token&gt;</b></div>
        <p class="muted" style="font-size:12.5px;margin-top:14px;line-height:1.7">
          Панель работает без внешних Python-зависимостей: HTTP-сервер, БД, QR-коды и подписки —
          всё на стандартной библиотеке. Xray-конфиги генерируются на лету и отдаются агентам нод.
        </p>
        <p class="muted" style="font-size:12.5px;margin-top:8px">
          Лицензия GPL-3.0: исходники и производные работы распространяются под той же лицензией.
        </p>
      </div>
    </div>`;
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  setActions('');
  container.innerHTML = '<div class="skeleton" style="height:420px"></div>';

  const settings = await api('/api/settings');
  state.settings = settings;

  const layout = () => {
    container.innerHTML = `
      <div class="settings-grid">
        <div class="card"><div class="card-body tight" style="padding:8px">
          <div class="settings-nav">
            ${SECTIONS.map((section) => `
              <button data-section="${section.id}" class="${activeSection === section.id ? 'active' : ''}">
                ${icon(section.icon)}${section.label}
              </button>`).join('')}
          </div>
        </div></div>
        <div id="settings-panel">${sectionHtml(activeSection, settings)}</div>
      </div>`;
    bindSettings(container);
  };

  layout();

  bind(container, 'click', async (ev) => {
    const sectionBtn = ev.target.closest('[data-section]');
    if (sectionBtn) {
      activeSection = sectionBtn.dataset.section;
      layout();
      return;
    }
    const action = ev.target.closest('[data-act]');
    if (!action) return;
    try {
      if (action.dataset.act === 'revoke') {
        const ok = await confirmDialog({
          title: 'Завершить другие сессии?',
          text: 'Все остальные браузеры потеряют доступ к панели. Текущая сессия останется.',
          confirmText: 'Завершить', danger: true,
        });
        if (!ok) return;
        const result = await api('/api/account/sessions/revoke', { method: 'POST' });
        toast(`Завершено сессий: ${result.removed}`);
      } else if (action.dataset.act === 'purge') {
        const ok = await confirmDialog({
          title: 'Очистить старую статистику?',
          text: `Срезы трафика старше ${settings.traffic_retention_days} дней будут удалены. Суммарные счётчики пользователей сохранятся.`,
          confirmText: 'Очистить', danger: true,
        });
        if (!ok) return;
        const result = await api('/api/maintenance/purge-traffic', { method: 'POST' });
        toast(`Удалено записей: ${result.removed}`);
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

function bindSettings(container) {
  const panel = container.querySelector('#settings-panel');

  const generalForm = panel.querySelector('[data-form="general"]');
  if (generalForm) {
    generalForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const body = {
        panel_title: formValue(generalForm, 'panel_title').trim(),
        panel_subtitle: formValue(generalForm, 'panel_subtitle').trim(),
        public_base_url: formValue(generalForm, 'public_base_url').trim(),
        footer_note: formValue(generalForm, 'footer_note').trim(),
      };
      try {
        await api('/api/settings', { method: 'PATCH', body });
        state.panel = { ...state.panel, panel_title: body.panel_title, panel_subtitle: body.panel_subtitle };
        toast('Настройки сохранены');
        window.dispatchEvent(new CustomEvent('dfx:panel-updated'));
      } catch (err) { toast(err.message, 'err'); }
    });
  }

  const subscriptionForm = panel.querySelector('[data-form="subscription"]');
  if (subscriptionForm) {
    subscriptionForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const f = subscriptionForm;
      const body = {
        sub_title: formValue(f, 'sub_title').trim(),
        sub_support_url: formValue(f, 'sub_support_url').trim(),
        sub_update_interval: Number(formValue(f, 'sub_update_interval', '12') || 12),
        default_days: Number(formValue(f, 'default_days', '0') || 0),
        default_limit_gb: formValue(f, 'default_limit_gb', '0'),
        default_device_limit: Number(formValue(f, 'default_device_limit', '0') || 0),
        sub_page_enabled: formChecked(f, 'sub_page_enabled'),
        sub_show_nodes: formChecked(f, 'sub_show_nodes'),
      };
      try {
        await api('/api/settings', { method: 'PATCH', body });
        Object.assign(state.settings || {}, body);
        toast('Настройки подписки сохранены');
      } catch (err) { toast(err.message, 'err'); }
    });
  }

  const routingForm = panel.querySelector('[data-form="routing"]');
  if (routingForm) {
    routingForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const f = routingForm;
      const body = {
        block_bittorrent: formChecked(f, 'block_bittorrent'),
        block_ads: formChecked(f, 'block_ads'),
        block_private: formChecked(f, 'block_private'),
        route_ru_direct: formChecked(f, 'route_ru_direct'),
        dns_preset: formValue(f, 'dns_preset', 'cloudflare'),
        traffic_retention_days: Number(formValue(f, 'traffic_retention_days', '90') || 90),
      };
      try {
        await api('/api/settings', { method: 'PATCH', body });
        toast('Маршрутизация обновлена');
      } catch (err) { toast(err.message, 'err'); }
    });
  }

  const passwordForm = panel.querySelector('[data-form="password"]');
  if (passwordForm) {
    passwordForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (formValue(passwordForm, 'new_password') !== formValue(passwordForm, 'repeat_password')) {
        toast('Пароли не совпадают', 'err');
        return;
      }
      try {
        await api('/api/account/password', {
          method: 'POST',
          body: {
            current_password: formValue(passwordForm, 'current_password'),
            new_password: formValue(passwordForm, 'new_password'),
          },
        });
        toast('Пароль изменён');
        state.bootstrapPassword = false;
        passwordForm.reset();
      } catch (err) { toast(err.message, 'err'); }
    });
  }
}
