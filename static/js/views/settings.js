/* Настройки панели: общие, подписка, маршрутизация, безопасность, обслуживание. */

import {
  api, bind, closeLayer, confirmDialog, copy, esc, formChecked, formValue, icon,
  openModal, state, toast,
} from '../core.js';

const SECTIONS = [
  { id: 'general', label: 'Общие', icon: 'settings' },
  { id: 'subscription', label: 'Подписки', icon: 'link' },
  { id: 'notifications', label: 'Уведомления', icon: 'bell' },
  { id: 'security', label: 'Безопасность', icon: 'shield' },
  { id: 'update', label: 'Обновление', icon: 'refresh' },
  { id: 'maintenance', label: 'Обслуживание', icon: 'download' },
  { id: 'about', label: 'О панели', icon: 'info' },
];

function sectionFromHash() {
  const query = window.location.hash.split('?')[1] || '';
  const value = new URLSearchParams(query).get('section') || '';
  return SECTIONS.some((item) => item.id === value) ? value : 'general';
}

let activeSection = sectionFromHash();

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
          ${sw('sub_sort_by_latency', 'Сортировать ноды по задержке', settings.sub_sort_by_latency,
               'Панель измеряет TCP-задержку до нод (кэш 5 минут) и ставит ближайшие первыми. В ссылке появляется поле <code class="mono">latency_ms</code>.')}
        </div>
        <div class="form-grid" style="margin-top:16px">
          <div class="field full">
            <label>E-mail для Let's Encrypt</label>
            <input class="input mono" name="acme_email" value="${esc(settings.acme_email || '')}" placeholder="admin@example.com">
            <div class="hint">Скрипт установки TLS-ноды сам выпускает сертификат через certbot на домен из поля SNI.
              Нужен свободный порт 80 и DNS-запись домена на сервер.</div>
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
      </div>
      <div class="card" style="margin-top:16px" id="totp-card">
        <div class="card-head"><h3>Двухфакторная аутентификация</h3></div>
        <div class="card-body"><div class="skeleton" style="height:64px"></div></div>
      </div>
      <div class="card" style="margin-top:16px" id="token-card">
        <div class="card-head"><h3>API-токены</h3><div class="spacer"></div>
          <button class="btn btn-sm" data-act="token-new">${icon('plus')}Создать токен</button></div>
        <div class="card-body" id="token-list"><div class="skeleton" style="height:64px"></div></div>
      </div>`;
  }
  if (id === 'notifications') {
    return `<div class="card" id="notify-card">
      <div class="card-head"><h3>Уведомления</h3><div class="spacer"></div>
        <span class="chip chip-quiet" id="notify-state">загрузка…</span></div>
      <div class="card-body"><div class="skeleton" style="height:220px"></div></div>
    </div>`;
  }
  if (id === 'update') {
    return `
      <div class="card">
        <div class="card-head">
          <div><h3>Обновление панели</h3>
            <div class="hint">Проверка новых версий и установка прямо из интерфейса.</div></div>
          <span id="update-badge" class="chip chip-quiet">проверка…</span>
        </div>
        <div class="card-body">
          <div class="kv"><span>Текущая версия</span><b class="mono" id="update-current">${esc(settings.version)}</b></div>
          <div class="kv"><span>Последняя версия</span><b class="mono" id="update-latest">—</b></div>
          <div class="kv"><span>Проверено</span><b id="update-checked">—</b></div>
          <div class="kv"><span>Способ обновления</span><b id="update-mode">—</b></div>
          <div class="update-notes" id="update-notes"></div>
          <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
            <button class="btn" data-act="check-update">${icon('refresh')}Проверить обновления</button>
            <button class="btn btn-primary" data-act="apply-update" disabled>${icon('download')}Обновить сейчас</button>
            <a class="btn" href="https://github.com/Dolov07KBR/DF_Xray/releases" target="_blank" rel="noopener">${icon('external')}Релизы</a>
          </div>
          <pre class="code-block update-log" id="update-log" hidden></pre>
          <p class="hint" style="margin-top:12px;line-height:1.7" id="update-hint">
            Автообновление работает, если у панели есть доступ к установщику или Docker.
            На VPS без этого доступна команда <code class="mono">dfxray update</code>.
          </p>
        </div>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h3>Каналы</h3></div>
        <div class="card-body">
          <div class="kv"><span>Репозиторий</span><b class="mono">Dolov07KBR/DF_Xray</b></div>
          <div class="kv"><span>Канал</span><b>стабильный (main / релизы)</b></div>
          <div class="kv"><span>Проверка</span><b>при входе и вручную, кэш 6 часов</b></div>
          <label class="switch" style="margin-top:12px">
            <input type="checkbox" name="update_auto" id="update-auto" ${settings.update_auto ? 'checked' : ''}>
            <span class="track"></span><span class="label">Проверять обновления автоматически</span>
          </label>
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


/* --------------------------------------------------------------- обновления --- */

let updateTimer = null;

function fmtStamp(value) {
  const n = Number(value);
  if (!n) return '—';
  try {
    return new Date(n * 1000).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
  } catch (err) { return '—'; }
}

function paintUpdate(container, data) {
  const badge = container.querySelector('#update-badge');
  const latest = container.querySelector('#update-latest');
  const checked = container.querySelector('#update-checked');
  const mode = container.querySelector('#update-mode');
  const notes = container.querySelector('#update-notes');
  const applyBtn = container.querySelector('[data-act="apply-update"]');
  if (!badge || !latest) return;

  const capability = data.capability || {};
  const current = data.current || (state.settings && state.settings.version) || '';
  if (data.error) {
    badge.className = 'chip chip-warn';
    badge.textContent = 'нет данных';
    notes.innerHTML = `<div class="notice warn">${esc(data.error)}</div>`;
  } else if (data.update_available) {
    badge.className = 'chip chip-accent';
    badge.textContent = `доступна ${data.latest}`;
  } else {
    badge.className = 'chip chip-quiet';
    badge.textContent = 'актуально';
  }
  latest.textContent = data.latest || '—';
  checked.textContent = data.checked_at ? fmtStamp(data.checked_at) : '—';
  mode.textContent = capability.label || '—';
  if (capability.hint) mode.title = capability.hint;
  if (notes && data.notes) {
    notes.innerHTML = `<div class="update-notes-body">${esc(data.notes).slice(0, 1200)}</div>`;
  } else if (notes) {
    notes.innerHTML = '';
  }
  if (applyBtn) {
    const canApply = Boolean(data.update_available) && capability.mode !== 'manual';
    applyBtn.disabled = !canApply;
    applyBtn.title = canApply
      ? (capability.hint || 'Запустить обновление')
      : 'Автообновление недоступно — обновите панель на сервере';
  }
  if (data.status) paintUpdateLog(container, data.status);
  void current;
}

function paintUpdateLog(container, status) {
  const log = container.querySelector('#update-log');
  if (!log) return;
  const text = status.log || '';
  if (!text) {
    log.hidden = true;
    return;
  }
  log.hidden = false;
  log.textContent = text;
  log.scrollTop = log.scrollHeight;
  if (status.running && !updateTimer) {
    updateTimer = setInterval(() => pollUpdateStatus(container), 2500);
  }
  if (!status.running && updateTimer) {
    clearInterval(updateTimer);
    updateTimer = null;
  }
}

async function pollUpdateStatus(container) {
  try {
    const status = await api('/api/updates/status');
    paintUpdateLog(container, status);
    if (!status.running) {
      if (status.ok) toast('Обновление завершено');
      else toast('Обновление завершилось с ошибкой — смотрите лог', 'err');
    }
  } catch (err) {
    if (updateTimer) clearInterval(updateTimer);
    updateTimer = null;
  }
}

async function hydrateUpdate(container) {
  try {
    const data = await api('/api/updates');
    paintUpdate(container, data);
  } catch (err) {
    toast(err.message, 'err');
  }
}

async function runUpdateCheck(container, btn) {
  if (btn) btn.disabled = true;
  try {
    const data = await api('/api/updates/check', { method: 'POST' });
    paintUpdate(container, data);
    toast(data.update_available ? `Доступна версия ${data.latest}` : 'Обновлений нет');
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function runUpdateApply(container, btn) {
  const ok = await confirmDialog({
    title: 'Обновить панель?',
    text: 'Панель запустит обновление и перезапустится. Сессия сохранится, данные в базе не изменятся.',
    confirmText: 'Обновить',
  });
  if (!ok) return;
  if (btn) btn.disabled = true;
  try {
    const result = await api('/api/updates/apply', { method: 'POST' });
    toast('Обновление запущено');
    const log = container.querySelector('#update-log');
    if (log) {
      log.hidden = false;
      log.textContent = `$ ${result.command}\n`;
    }
    pollUpdateStatus(container);
  } catch (err) {
    toast(err.message, 'err');
    if (btn) btn.disabled = false;
  }
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  setActions('');
  if (window.location.hash.includes('section=')) activeSection = sectionFromHash();
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

  const afterLayout = () => {
    if (activeSection === 'update') hydrateUpdate(container);
    if (activeSection === 'security') {
      hydrateTotp(container);
      hydrateTokens(container);
    }
    if (activeSection === 'notifications') hydrateNotifications(container);
  };

  layout();
  afterLayout();

  bind(container, 'click', async (ev) => {
    const sectionBtn = ev.target.closest('[data-section]');
    if (sectionBtn) {
      activeSection = sectionBtn.dataset.section;
      const next = `#/settings?section=${activeSection}`;
      if (window.location.hash !== next) {
        window.location.hash = next;
        return;
      }
      layout();
      afterLayout();
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
      } else if (action.dataset.act === 'check-update') {
        await runUpdateCheck(container, action);
      } else if (action.dataset.act === 'apply-update') {
        await runUpdateApply(container, action);
      } else if (action.dataset.act === 'totp-enable') {
        await startTotpSetup(container);
      } else if (action.dataset.act === 'totp-disable') {
        askPassword({
          title: 'Выключить 2FA?',
          text: 'Для подтверждения введите текущий пароль. Сессии будут завершены.',
          confirmText: 'Выключить', danger: true,
          onSubmit: async (password) => {
            await api('/api/account/2fa/disable', { method: 'POST', body: { password } });
            closeLayer();
            toast('2FA выключена');
            hydrateTotp(container);
          },
        });
      } else if (action.dataset.act === 'totp-recovery') {
        askPassword({
          title: 'Новые резервные коды',
          text: 'Старые коды перестанут работать.',
          confirmText: 'Сгенерировать',
          onSubmit: async (password) => {
            const result = await api('/api/account/2fa/recovery', { method: 'POST', body: { password } });
            closeLayer();
            showRecoveryCodes(result.recovery_codes || []);
            hydrateTotp(container);
          },
        });
      } else if (action.dataset.act === 'token-new') {
        openTokenCreate(container);
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
        sub_sort_by_latency: formChecked(f, 'sub_sort_by_latency'),
        acme_email: formValue(f, 'acme_email').trim(),
      };
      try {
        await api('/api/settings', { method: 'PATCH', body });
        Object.assign(state.settings || {}, body);
        toast('Настройки подписки сохранены');
      } catch (err) { toast(err.message, 'err'); }
    });
  }

  const autoToggle = panel.querySelector('#update-auto');
  if (autoToggle) {
    autoToggle.addEventListener('change', async () => {
      try {
        await api('/api/settings', { method: 'PATCH', body: { update_auto: autoToggle.checked } });
        toast(autoToggle.checked ? 'Автопроверка включена' : 'Автопроверка выключена');
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


/* ------------------------------------------------- 2FA, токены, уведомления --- */

function stamp(value) {
  if (!value) return '—';
  const raw = String(value);
  const date = new Date(raw.length <= 10 ? `${raw}T00:00:00Z` : raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
}

/* --- двухфакторная аутентификация --- */

function paintTotp(box, data) {
  const enabled = Boolean(data.enabled);
  box.innerHTML = `
    <div class="card-head">
      <div><h3>Двухфакторная аутентификация</h3>
        <div class="hint">TOTP-код из Google Authenticator, Aegis, 1Password или другого приложения.</div></div>
      <div class="spacer"></div>
      <span class="status ${enabled ? 'online' : 'unknown'}"><span class="dot"></span>${enabled ? 'включена' : 'выключена'}</span>
    </div>
    <div class="card-body">
      ${enabled ? `
        <div class="kv"><span>Подтверждена</span><b>${esc(stamp(data.confirmed_at))}</b></div>
        <div class="kv"><span>Резервных кодов осталось</span><b>${data.recovery_left ?? 0}</b></div>
        <p class="muted" style="font-size:12.5px;margin:12px 0 16px">
          Пароль + код запрашиваются при каждом входе. Резервные коды одноразовые: сохраните их в надёжном месте.
        </p>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn" data-act="totp-recovery">${icon('key')}Новые резервные коды</button>
          <button class="btn btn-danger" data-act="totp-disable">${icon('lock')}Выключить 2FA</button>
        </div>` : `
        <p class="muted" style="font-size:12.5px;margin-bottom:16px">
          Включите 2FA, чтобы одного пароля было недостаточно. Панель покажет QR-код и 8 резервных кодов.
        </p>
        <button class="btn btn-primary" data-act="totp-enable">${icon('shield')}Включить 2FA</button>`}
    </div>`;
}

async function hydrateTotp(container) {
  const box = container.querySelector('#totp-card');
  if (!box) return;
  try {
    paintTotp(box, await api('/api/account/2fa'));
  } catch (err) {
    box.innerHTML = `<div class="card-body"><div class="notice warn">${esc(err.message)}</div></div>`;
  }
}

function showRecoveryCodes(codes) {
  openModal({
    title: 'Резервные коды',
    body: `
      <div class="notice warn" style="margin-bottom:14px">${icon('alert')}
        <div>Каждый код одноразовый. Сохраните их сейчас — повторно панель их не покажет.</div></div>
      <div class="recovery-grid">${codes.map((code) => `<code class="mono">${esc(code)}</code>`).join('')}</div>`,
    footer: `<button class="btn" data-act="copy-codes">${icon('copy')}Копировать</button>
      <button class="btn btn-primary" data-act="close">Готово</button>`,
    onMount(modal) {
      modal.addEventListener('click', async (ev) => {
        const el = ev.target.closest('[data-act]');
        if (!el) return;
        if (el.dataset.act === 'copy-codes') await copy(codes.join('\n'), 'Коды скопированы');
        if (el.dataset.act === 'close') closeLayer();
      });
    },
  });
}

async function startTotpSetup(container) {
  const data = await api('/api/account/2fa/start', { method: 'POST' });
  openModal({
    title: 'Подключить 2FA',
    body: `
      <div class="totp-setup">
        <div class="totp-qr">${data.qr_svg || ''}</div>
        <div>
          <p class="muted" style="font-size:12.5px;line-height:1.7">
            Отсканируйте QR-код в приложении-аутентификаторе или введите секрет вручную:
          </p>
          <div class="sub-url-row" style="margin:8px 0 14px">
            <input class="input mono" value="${esc(data.secret_pretty || data.secret)}" readonly onclick="this.select()">
            <button class="icon-btn" data-act="copy-secret" title="Копировать">${icon('copy')}</button>
          </div>
          <div class="field">
            <label>Код из приложения</label>
            <input class="input mono" name="code" inputmode="numeric" placeholder="123 456" autocomplete="one-time-code">
            <div class="hint">Введите код, чтобы подтвердить, что приложение настроено.</div>
          </div>
          <div class="login-error" id="totp-error"></div>
        </div>
      </div>`,
    footer: `<button class="btn" data-act="cancel">Отмена</button>
      <button class="btn btn-primary" data-act="confirm">Включить</button>`,
    onMount(modal) {
      const input = modal.querySelector('[name="code"]');
      input.focus();
      const confirm = async () => {
        const err = modal.querySelector('#totp-error');
        err.classList.remove('show');
        try {
          await api('/api/account/2fa/enable', { method: 'POST', body: { code: input.value.trim() } });
          closeLayer();
          toast('2FA включена');
          hydrateTotp(container);
          showRecoveryCodes(data.recovery_codes || []);
        } catch (error) {
          err.textContent = error.message;
          err.classList.add('show');
          input.select();
        }
      };
      input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); confirm(); } });
      modal.addEventListener('click', async (ev) => {
        const el = ev.target.closest('[data-act]');
        if (!el) return;
        if (el.dataset.act === 'copy-secret') await copy(data.secret, 'Секрет скопирован');
        if (el.dataset.act === 'cancel') closeLayer();
        if (el.dataset.act === 'confirm') await confirm();
      });
    },
  });
}

function askPassword({ title, text, confirmText, danger = false, onSubmit }) {
  openModal({
    title,
    body: `
      <p class="muted" style="font-size:12.5px;margin-bottom:14px">${text}</p>
      <div class="field">
        <label>Текущий пароль</label>
        <input class="input" type="password" name="password" autocomplete="current-password">
      </div>
      <div class="login-error" id="pw-error"></div>`,
    footer: `<button class="btn" data-act="cancel">Отмена</button>
      <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">${confirmText}</button>`,
    onMount(modal) {
      const input = modal.querySelector('[name="password"]');
      input.focus();
      const run = async () => {
        const err = modal.querySelector('#pw-error');
        err.classList.remove('show');
        try {
          await onSubmit(input.value);
        } catch (error) {
          err.textContent = error.message;
          err.classList.add('show');
          input.select();
        }
      };
      input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); run(); } });
      modal.addEventListener('click', async (ev) => {
        const el = ev.target.closest('[data-act]');
        if (!el) return;
        if (el.dataset.act === 'cancel') closeLayer();
        if (el.dataset.act === 'ok') await run();
      });
    },
  });
}

/* --- API-токены --- */

const SCOPE_LABELS = { read: 'только чтение', write: 'чтение и запись' };

function paintTokens(box, items) {
  if (!items.length) {
    box.innerHTML = `<p class="muted" style="font-size:12.5px">
      Токенов пока нет. Они нужны для скриптов, мониторинга и CI —
      запросы идут с заголовком <code class="mono">Authorization: Bearer dfx_…</code>.</p>`;
    return;
  }
  box.innerHTML = `
    <table class="table">
      <thead><tr><th>Название</th><th>Доступ</th><th>Создан</th><th>Использован</th><th>Истекает</th><th></th></tr></thead>
      <tbody>
        ${items.map((item) => `<tr>
          <td><div class="cell-main">${esc(item.name)}</div>
            <div class="cell-sub mono">${esc(item.prefix)}…</div></td>
          <td><span class="chip ${item.scope === 'write' ? 'accent' : ''}">${esc(SCOPE_LABELS[item.scope] || item.scope)}</span></td>
          <td class="mono" style="font-size:11.5px">${esc(stamp(item.created_at))}</td>
          <td class="mono" style="font-size:11.5px">${item.last_used_at ? esc(stamp(item.last_used_at)) : '—'}</td>
          <td class="mono" style="font-size:11.5px">${item.expires_at ? esc(stamp(item.expires_at)) : 'бессрочно'}</td>
          <td class="num"><button class="icon-btn" data-token="${item.id}" title="Удалить">${icon('trash')}</button></td>
        </tr>`).join('')}
      </tbody>
    </table>
    <p class="muted" style="font-size:12px;margin-top:12px">
      Токен с доступом «только чтение» может выполнять лишь GET-запросы к API.
      Полное значение токена показывается один раз при создании.
    </p>`;
}

async function hydrateTokens(container) {
  const box = container.querySelector('#token-list');
  if (!box) return;
  try {
    const data = await api('/api/tokens');
    paintTokens(box, data.items || []);
    bind(box, 'click', async (ev) => {
      const btn = ev.target.closest('[data-token]');
      if (!btn) return;
      const ok = await confirmDialog({
        title: 'Удалить токен?',
        text: 'Скрипты, использующие этот токен, потеряют доступ к API.',
        confirmText: 'Удалить', danger: true,
      });
      if (!ok) return;
      try {
        await api(`/api/tokens/${btn.dataset.token}`, { method: 'DELETE' });
        toast('Токен удалён');
        hydrateTokens(container);
      } catch (err) { toast(err.message, 'err'); }
    });
  } catch (err) {
    box.innerHTML = `<div class="notice warn">${esc(err.message)}</div>`;
  }
}

function openTokenCreate(container) {
  openModal({
    title: 'Новый API-токен',
    body: `
      <div class="form-grid">
        <div class="field full">
          <label>Название</label>
          <input class="input" name="name" placeholder="Мониторинг / бэкап / CI">
        </div>
        <div class="field">
          <label>Уровень доступа</label>
          <select class="input" name="scope">
            <option value="read">Только чтение (GET)</option>
            <option value="write">Чтение и запись</option>
          </select>
        </div>
        <div class="field">
          <label>Срок действия, дней</label>
          <input class="input" name="expires_days" type="number" min="0" max="3650" value="0">
          <div class="hint">0 — бессрочно</div>
        </div>
      </div>
      <div class="login-error" id="token-error"></div>`,
    footer: `<button class="btn" data-act="cancel">Отмена</button>
      <button class="btn btn-primary" data-act="create">Создать</button>`,
    onMount(modal) {
      const name = modal.querySelector('[name="name"]');
      name.focus();
      const create = async () => {
        const err = modal.querySelector('#token-error');
        err.classList.remove('show');
        try {
          const result = await api('/api/tokens', {
            method: 'POST',
            body: {
              name: name.value.trim(),
              scope: modal.querySelector('[name="scope"]').value,
              expires_days: Number(modal.querySelector('[name="expires_days"]').value || 0),
            },
          });
          closeLayer();
          hydrateTokens(container);
          openModal({
            title: 'Токен создан',
            body: `
              <div class="notice warn" style="margin-bottom:14px">${icon('alert')}
                <div>Скопируйте токен сейчас — второй раз он не покажется.</div></div>
              <div class="sub-url-row">
                <input class="input mono" value="${esc(result.token)}" readonly onclick="this.select()">
                <button class="icon-btn" data-act="copy" title="Копировать">${icon('copy')}</button>
              </div>
              <div class="code-block" style="margin-top:12px">curl -H "Authorization: Bearer ${esc(result.token)}" \\
  ${esc(settingsBase())}/api/users</div>`,
            footer: `<button class="btn btn-primary" data-act="close">Готово</button>`,
            onMount(box) {
              box.addEventListener('click', async (ev) => {
                const el = ev.target.closest('[data-act]');
                if (!el) return;
                if (el.dataset.act === 'copy') await copy(result.token, 'Токен скопирован');
                if (el.dataset.act === 'close') closeLayer();
              });
            },
          });
        } catch (error) {
          err.textContent = error.message;
          err.classList.add('show');
        }
      };
      name.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); create(); } });
      modal.addEventListener('click', async (ev) => {
        const el = ev.target.closest('[data-act]');
        if (!el) return;
        if (el.dataset.act === 'cancel') closeLayer();
        if (el.dataset.act === 'create') await create();
      });
    },
  });
}

function settingsBase() {
  const settings = state.settings || {};
  return (settings.public_base_url || settings.base_url || window.location.origin).replace(/\/$/, '');
}

/* --- уведомления --- */

const EVENT_LABELS = {
  node_offline: 'Сервер не в сети',
  node_recovered: 'Сервер вернулся в строй',
  user_limit: 'Клиент исчерпал лимит',
  update_available: 'Доступна новая версия',
};

function paintNotifications(box, data) {
  const events = data.events || [];
  box.innerHTML = `
    <div class="card-head">
      <div><h3>Уведомления</h3>
        <div class="hint">Куда и о чём панель сообщает сама.</div></div>
      <div class="spacer"></div>
      <span class="chip ${data.enabled ? 'mint' : 'chip-quiet'}">${data.enabled ? 'включены' : 'выключены'}</span>
    </div>
    <div class="card-body">
      ${sw('notify_enabled', 'Отправлять уведомления', data.enabled,
           'Telegram-бот и/или webhook. Проверка событий — раз в 90 секунд, повторы не спамят.')}
      <div class="form-grid" style="margin-top:14px">
        <div class="field">
          <label>Токен Telegram-бота</label>
          <input class="input mono" name="telegram_token" value="${esc(data.telegram_token || '')}" placeholder="123456:AA…">
          <div class="hint">Создайте бота у <code class="mono">@BotFather</code>.</div>
        </div>
        <div class="field">
          <label>Chat ID</label>
          <input class="input mono" name="telegram_chat" value="${esc(data.telegram_chat || '')}" placeholder="-1001234567890">
        </div>
        <div class="field full">
          <label>Webhook</label>
          <input class="input mono" name="webhook" value="${esc(data.webhook || '')}" placeholder="https://hooks.example.com/dfxray">
          <div class="hint">POST c JSON <code class="mono">{event, title, text, panel, time}</code>.</div>
        </div>
      </div>
      <div class="field" style="margin-top:14px">
        <label>События</label>
        <div class="event-grid">
          ${Object.entries(data.available_events || {}).map(([name, label]) => `
            <label class="switch">
              <input type="checkbox" class="notify-event" value="${esc(name)}" ${events.includes(name) ? 'checked' : ''}>
              <span class="track"></span><span class="label">${esc(label || EVENT_LABELS[name] || name)}</span>
            </label>`).join('')}
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:18px;flex-wrap:wrap">
        <button class="btn btn-primary" type="button" data-act="notify-save">${icon('check')}Сохранить</button>
        <button class="btn" type="button" data-act="notify-test">${icon('bolt')}Тестовое сообщение</button>
        <button class="btn btn-ghost" type="button" data-act="notify-check">${icon('refresh')}Проверить события сейчас</button>
      </div>
    </div>`;
  bind(box, 'click', async (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    const val = (name) => (box.querySelector(`[name="${name}"]`) || {}).value || '';
    try {
      if (el.dataset.act === 'notify-save') {
        await api('/api/notifications', {
          method: 'PATCH',
          body: {
            enabled: box.querySelector('[name="notify_enabled"]').checked,
            telegram_token: val('telegram_token').trim(),
            telegram_chat: val('telegram_chat').trim(),
            webhook: val('webhook').trim(),
            events: [...box.querySelectorAll('.notify-event:checked')].map((input) => input.value),
          },
        });
        toast('Уведомления сохранены');
      } else if (el.dataset.act === 'notify-test') {
        await api('/api/notifications/test', { method: 'POST' });
        toast('Тестовое сообщение отправлено');
      } else if (el.dataset.act === 'notify-check') {
        const result = await api('/api/notifications/check', { method: 'POST' });
        toast(result.total ? `Отправлено событий: ${result.total}` : 'Новых событий нет');
      }
    } catch (err) { toast(err.message, 'err'); }
  });
}

async function hydrateNotifications(container) {
  const box = container.querySelector('#notify-card');
  if (!box) return;
  try {
    paintNotifications(box, await api('/api/notifications'));
  } catch (err) {
    box.innerHTML = `<div class="card-body"><div class="notice warn">${esc(err.message)}</div></div>`;
  }
}
