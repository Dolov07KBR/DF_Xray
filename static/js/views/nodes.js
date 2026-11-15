/* Ноды: карточки серверов, онбординг нового сервера, конфиг и метрики. */

import {
  api, bind, closeLayer, confirmDialog, copy, download, esc, fmtBytes, formField,
  formValue, icon, openModal, protoChips, relTime, toast,
} from '../core.js';

const TRANSPORTS = [
  ['tcp', 'TCP'],
  ['ws', 'WebSocket'],
  ['grpc', 'gRPC'],
  ['xhttp', 'XHTTP'],
  ['h2', 'HTTP/2'],
];
const SECURITIES = [['reality', 'Reality'], ['tls', 'TLS'], ['none', 'Без шифрования']];
const PROTOCOLS = [['vless', 'VLESS'], ['vmess', 'VMess'], ['trojan', 'Trojan']];

const HEALTH = {
  ok: ['Онлайн', 'online'],
  degraded: ['Xray не работает', 'limited'],
  offline: ['Не в сети', 'offline'],
  unknown: ['Не подключалась', 'unknown'],
  disabled: ['Выключена', 'disabled'],
};

function healthBadge(node) {
  const [label, tone] = HEALTH[node.health] || HEALTH.unknown;
  const when = node.last_seen ? ` · ${relTime(node.last_seen)}` : '';
  return `<span class="status ${tone}" title="${esc(label + when)}"><span class="dot"></span>${esc(label)}</span>`;
}

function uptimeText(seconds) {
  const value = Number(seconds || 0);
  if (value <= 0) return '—';
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (days) return `${days} д ${hours} ч`;
  if (hours) return `${hours} ч ${minutes} м`;
  return `${minutes} м`;
}

function cardHtml(node) {
  const traffic = node.up_bytes + node.down_bytes;
  const error = (node.last_error || '').trim();
  return `
    <div class="card node-card" data-id="${node.id}">
      <div class="nc-head">
        <div style="flex:1;min-width:0">
          <h3 title="${esc(node.name)}">${esc(node.name)}</h3>
          <div class="nc-addr" title="${esc(node.address)}:${node.port}">${esc(node.address)}:${node.port}</div>
        </div>
        ${healthBadge(node)}
      </div>
      <div class="chips">${protoChips(node)}${node.region ? `<span class="chip">${esc(node.region)}</span>` : ''}${node.enabled ? '' : '<span class="chip">выключена</span>'}
      </div>
      <div class="nc-stats">
        <div class="nc-stat"><span>Клиенты</span><b>${node.users_count ?? 0}</b></div>
        <div class="nc-stat"><span>Трафик</span><b>${fmtBytes(traffic)}</b></div>
        <div class="nc-stat"><span>Uptime</span><b style="font-size:12px">${uptimeText(node.uptime_seconds)}</b></div>
      </div>
      <div class="nc-stats nc-stats-sub">
        <div class="nc-stat"><span>LA1</span><b>${node.load1 ? Number(node.load1).toFixed(2) : '—'}</b></div>
        <div class="nc-stat"><span>Память</span><b>${node.mem_total ? `${Math.round((node.mem_used / node.mem_total) * 100)}%` : '—'}</b></div>
        <div class="nc-stat"><span>Агент</span><b style="font-size:11.5px">${node.agent_version ? esc(node.agent_version) : '—'}</b></div>
      </div>
      ${error ? `<div class="nc-error" title="${esc(error)}">${icon('alert')}<span>${esc(error)}</span></div>` : ''}
      <div class="nc-foot">
        <button class="btn btn-sm btn-primary" data-act="connect" data-id="${node.id}">${icon('bolt')}Подключить</button>
        <button class="btn btn-sm" data-act="config" data-id="${node.id}">${icon('terminal')}Конфиг</button>
        <div class="spacer"></div>
        <button class="icon-btn" data-act="probe" data-id="${node.id}" title="Проверить порт">${icon('wifi')}</button>
        <button class="icon-btn" data-act="edit" data-id="${node.id}" title="Изменить">${icon('edit')}</button>
        <button class="icon-btn" data-act="toggle" data-id="${node.id}" title="${node.enabled ? 'Выключить' : 'Включить'}">${icon('power')}</button>
        <button class="icon-btn" data-act="delete" data-id="${node.id}" title="Удалить">${icon('trash')}</button>
      </div>
    </div>`;
}

function field(label, inputHtml, hint = '') {
  return `<div class="field"><label>${label}</label>${inputHtml}${hint ? `<div class="hint">${hint}</div>` : ''}</div>`;
}

function nodeFormHtml(node) {
  const value = (key, fallback = '') => esc(node ? (node[key] ?? fallback) : fallback);
  return `
    <form id="node-form" autocomplete="off">
      <div class="form-grid">
        ${field('Название *', `<input class="input" name="name" required value="${value('name')}" placeholder="DF · Frankfurt">`)}
        ${field('Адрес (домен или IP) *', `<input class="input mono" name="address" required value="${value('address')}" placeholder="node.example.com">`)}
        ${field('Регион / локация', `<input class="input" name="region" value="${value('region')}" placeholder="Германия">`, 'Показывается в карточке и ссылках подписки')}
        ${field('Порт', `<input class="input" name="port" type="number" min="1" max="65535" value="${value('port', 443)}">`)}
        ${field('Протокол', `<select class="select" name="protocol">${PROTOCOLS.map(([v, l]) =>
          `<option value="${v}" ${(node ? node.protocol : 'vless') === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`)}
        ${field('Транспорт', `<select class="select" name="transport">${TRANSPORTS.map(([v, l]) =>
          `<option value="${v}" ${(node ? node.transport : 'tcp') === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`)}
        ${field('Безопасность', `<select class="select" name="security">${SECURITIES.map(([v, l]) =>
          `<option value="${v}" ${(node ? node.security : 'reality') === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`)}
      </div>

      <div data-group="tls-like" style="margin-top:14px">
        <div class="form-grid">
          ${field('SNI / Server Name', `<input class="input mono" name="sni" value="${value('sni')}" placeholder="www.microsoft.com">`,
            'Домен-маскировка для Reality или имя сертификата для TLS')}
          ${field('Fingerprint (uTLS)', `<input class="input mono" name="fingerprint" value="${value('fingerprint', 'chrome')}" placeholder="chrome">`,
            'chrome, firefox, safari, randomized')}
        </div>
      </div>

      <div data-group="reality" style="margin-top:14px">
        <div class="form-grid">
          ${field('Dest (куда проксировать Reality)', `<input class="input mono" name="dest" value="${value('dest')}" placeholder="www.microsoft.com:443">`)}
          ${field('Short ID', `<input class="input mono" name="short_id" value="${value('short_id')}" placeholder="hex, 8-16 символов">`)}
          ${field('Private key', `<input class="input mono" name="private_key" value="${value('private_key')}" placeholder="генерируется кнопкой">`)}
          ${field('Public key', `<input class="input mono" name="public_key" value="${value('public_key')}" placeholder="для клиентских ссылок">`)}
        </div>
        ${node ? `<button class="btn btn-sm" type="button" data-act="gen-keys" style="margin-top:10px">${icon('key')}Сгенерировать Reality-ключи</button>`
          : '<div class="hint" style="margin-top:8px">Ключи можно создать автоматически после сохранения ноды.</div>'}
      </div>

      <div data-group="tls" style="margin-top:14px">
        <div class="form-grid">
          ${field('Сертификат (путь на сервере)', `<input class="input mono" name="cert_file" value="${value('cert_file', '/etc/xray/cert/fullchain.pem')}">`)}
          ${field('Ключ сертификата', `<input class="input mono" name="key_file" value="${value('key_file', '/etc/xray/cert/privkey.pem')}">`)}
          ${field('ALPN', `<input class="input mono" name="alpn" value="${value('alpn', 'h2,http/1.1')}">`)}
        </div>
      </div>

      <div data-group="path" style="margin-top:14px">
        <div class="form-grid">
          ${field('Путь (path)', `<input class="input mono" name="path" value="${value('path', '/')}" placeholder="/dfws">`)}
        </div>
      </div>

      <div data-group="grpc" style="margin-top:14px">
        <div class="form-grid">
          ${field('Service name (gRPC)', `<input class="input mono" name="service_name" value="${value('service_name')}" placeholder="dfxray">`)}
        </div>
      </div>

      <div data-group="flow" style="margin-top:14px">
        <div class="form-grid">
          ${field('Flow по умолчанию', `<select class="select" name="flow">
            <option value="" ${!value('flow') ? 'selected' : ''}>без flow</option>
            <option value="xtls-rprx-vision" ${value('flow') === 'xtls-rprx-vision' ? 'selected' : ''}>xtls-rprx-vision</option>
          </select>`, 'Только для VLESS + TCP + TLS/Reality')}
          ${field('Сортировка', `<input class="input" name="sort" type="number" value="${value('sort', 0)}">`)}
        </div>
      </div>

      <div class="form-grid" style="margin-top:14px">
        ${field('Заметка', `<textarea class="textarea" name="note" rows="2">${value('note')}</textarea>`)}
        <div class="field">
          <label class="switch" style="margin-top:22px">
            <input type="checkbox" name="enabled" ${!node || node.enabled ? 'checked' : ''}>
            <span class="track"></span>
            <span class="label">Нода включена</span>
          </label>
        </div>
      </div>
    </form>`;
}

function syncVisibility(form) {
  const transport = formValue(form, 'transport', 'tcp');
  const security = formValue(form, 'security', 'reality');
  const protocol = formValue(form, 'protocol', 'vless');
  const show = (group, visible) => {
    form.querySelectorAll(`[data-group="${group}"]`).forEach((el) => {
      el.classList.toggle('hidden', !visible);
    });
  };
  show('tls-like', security !== 'none');
  show('reality', security === 'reality');
  show('tls', security === 'tls');
  show('path', ['ws', 'xhttp', 'h2'].includes(transport));
  show('grpc', transport === 'grpc');
  show('flow', protocol === 'vless' && transport === 'tcp' && security !== 'none');
}

export function openNodeForm(node = null, onSaved = null) {
  const isEdit = Boolean(node);
  const modal = openModal({
    title: isEdit ? `Сервер · ${node.name}` : 'Новый сервер',
    wide: true,
    body: nodeFormHtml(node),
    footer: `
      <button class="btn" data-act="cancel">Отмена</button>
      <button class="btn btn-primary" data-act="save">${isEdit ? 'Сохранить' : 'Создать сервер'}</button>`,
    onMount(root) {
      const form = root.querySelector('#node-form');
      syncVisibility(form);
      formField(form, 'transport').addEventListener('change', () => syncVisibility(form));
      formField(form, 'security').addEventListener('change', () => syncVisibility(form));
      formField(form, 'protocol').addEventListener('change', () => syncVisibility(form));
      form.querySelector('[name="name"]').focus();
    },
  });

  modal.addEventListener('click', async (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    if (el.dataset.act === 'cancel') { closeLayer(); return; }
    if (el.dataset.act === 'gen-keys') {
      if (!node) return;
      try {
        const keys = await api(`/api/nodes/${node.id}/reality-keys`, { method: 'POST' });
        formField(modal, 'private_key').value = keys.private_key;
        formField(modal, 'public_key').value = keys.public_key;
        toast('Reality-ключи сгенерированы');
      } catch (err) { toast(err.message, 'err'); }
      return;
    }
    if (el.dataset.act !== 'save') return;

    const form = modal.querySelector('#node-form');
    if (!form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form).entries());
    data.enabled = formField(form, 'enabled').checked;
    data.port = Number(data.port || 443);
    data.sort = Number(data.sort || 0);
    try {
      let saved;
      if (isEdit) {
        saved = await api(`/api/nodes/${node.id}`, { method: 'PATCH', body: data });
        toast('Сервер обновлён');
      } else {
        saved = await api('/api/nodes', { method: 'POST', body: data });
        toast('Сервер создан');
        if (saved.security === 'reality' && !saved.private_key) {
          try {
            const keys = await api(`/api/nodes/${saved.id}/reality-keys`, { method: 'POST' });
            saved.private_key = keys.private_key;
            saved.public_key = keys.public_key;
            toast('Reality-ключи сгенерированы автоматически');
          } catch (err) {
            toast(err.message, 'err');
          }
        }
      }
      closeLayer();
      if (onSaved) await onSaved();
      if (!isEdit) openNodeConnect(saved.id);
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

/* ---------------------------------------------------------------- установка */

function commandBlock(text, hint = '') {
  return `
    <div class="cmd-block">
      <pre class="code-block cmd-code">${esc(text)}</pre>
      <button class="btn btn-sm" data-act="copy-cmd">${icon('copy')}Копировать</button>
    </div>
    ${hint ? `<div class="hint" style="margin-top:6px">${hint}</div>` : ''}`;
}

export async function openNodeConnect(nodeId) {
  let data;
  try {
    data = await api(`/api/nodes/${nodeId}/connect`);
  } catch (err) {
    toast(err.message, 'err');
    return;
  }
  const commands = {
    systemd: { label: 'Одна команда', text: data.one_liner },
    docker: { label: 'Docker', text: data.docker },
    compose: { label: 'docker-compose', text: data.compose },
  };
  let current = 'systemd';

  const modal = openModal({
    title: `Подключить сервер · ${data.node.name}`,
    wide: true,
    body: `
      <div class="banner" style="border-color:var(--line-strong);background:rgba(124,92,255,.07);color:var(--text-dim)">
        ${icon('info')}
        <div>Команда ставит Xray и агент на чистый сервер (Ubuntu / Debian / CentOS / Alpine) и подключает его к панели.
        Запускать от <b>root</b>. Панель должна быть доступна с нового сервера по этому адресу.</div>
      </div>
      ${data.https ? '' : `<div class="banner" style="border-color:rgba(210,153,34,.5);background:rgba(210,153,34,.08);color:#e3b341">
        ${icon('alert')}
        <div>Панель открыта по HTTP. Для установки нод выдайте ей HTTPS-домен,
        иначе токен ноды пойдёт по сети открытым текстом.</div>
      </div>`}
      <div class="segmented" style="margin:14px 0 10px" id="connect-tabs">
        ${Object.entries(commands).map(([key, item]) => `
          <button type="button" class="${key === current ? 'active' : ''}" data-tab="${key}">${item.label}</button>`).join('')}
      </div>
      <div id="connect-cmd">${commandBlock(commands[current].text)}</div>
      <div class="kv" style="margin-top:14px"><span>Адрес панели</span><b class="mono">${esc(data.panel_url)}</b></div>
      <div class="kv"><span>Токен установки</span><b class="mono" style="font-size:11.5px">${esc(data.install_token)}</b></div>
      <div class="kv"><span>Порт ноды</span><b>${data.port}</b></div>
      <div class="hint" style="margin-top:10px">
        Ссылка установки одноразовая по смыслу: после подключения перевыпустите её,
        чтобы старая команда перестала работать. Конфиг и статистику агент получает по отдельному токену.
      </div>`,
    footer: `
      <button class="btn" data-act="rotate-install">${icon('refresh')}Перевыпустить ссылку</button>
      <button class="btn" data-act="config">${icon('terminal')}Конфиг</button>
      <button class="btn btn-primary" data-act="done">Готово</button>`,
  });

  modal.addEventListener('click', async (ev) => {
    const tab = ev.target.closest('[data-tab]');
    if (tab) {
      current = tab.dataset.tab;
      modal.querySelectorAll('[data-tab]').forEach((el) => el.classList.toggle('active', el === tab));
      modal.querySelector('#connect-cmd').innerHTML = commandBlock(commands[current].text);
      return;
    }
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    try {
      if (el.dataset.act === 'copy-cmd') {
        await copy(commands[current].text, 'Команда скопирована');
      } else if (el.dataset.act === 'done') {
        closeLayer();
        const node = await api(`/api/nodes/${nodeId}`).catch(() => null);
        if (node) openNodeConfig(nodeId);
      } else if (el.dataset.act === 'config') {
        closeLayer();
        openNodeConfig(nodeId);
      } else if (el.dataset.act === 'rotate-install') {
        const ok = await confirmDialog({
          title: 'Перевыпустить ссылку установки?',
          text: 'Старая команда перестанет работать. Уже подключённый сервер продолжит обновляться — его токен не меняется.',
          confirmText: 'Перевыпустить',
        });
        if (!ok) return;
        const fresh = await api(`/api/nodes/${nodeId}/install-token`, { method: 'POST' });
        commands.systemd.text = fresh.one_liner;
        commands.docker.text = fresh.docker;
        commands.compose.text = fresh.compose;
        modal.querySelector('#connect-cmd').innerHTML = commandBlock(commands[current].text);
        modal.querySelectorAll('.kv b')[1].textContent = fresh.install_token;
        toast('Ссылка установки обновлена');
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

/* ------------------------------------------------------------ конфиг ноды */

async function openNodeConfig(nodeId) {
  let data;
  try {
    data = await api(`/api/nodes/${nodeId}`);
  } catch (err) {
    toast(err.message, 'err');
    return;
  }
  const configText = JSON.stringify(data.config, null, 2);
  const token = data.agent_token || '';
  const baseUrl = data.base_url || window.location.origin;
  const envSnippet = [
    'services:',
    '  node:',
    '    image: ghcr.io/dfxray/node:latest',
    '    environment:',
    `      DFX_PANEL_URL: ${baseUrl}`,
    `      DFX_NODE_TOKEN: ${token}`,
    '    ports:',
    `      - "${data.port}:${data.port}"`,
  ].join('\n');

  const modal = openModal({
    title: `Конфиг ноды · ${data.name}`,
    wide: true,
    body: `
      <div class="chips" style="margin-bottom:14px">
        ${protoChips(data)}
        <span class="chip mint">${data.users_count} клиентов</span>
        <span class="chip${data.cfg_revision && data.cfg_revision === data.config_revision ? ' mint' : ''}">
          ${data.cfg_revision && data.cfg_revision === data.config_revision ? 'конфиг применён' : 'конфиг не применён'}
        </span>
        ${data.agent_version ? `<span class="chip chip-quiet">агент ${esc(data.agent_version)}</span>` : ''}
      </div>
      ${data.last_error ? `<div class="banner" style="border-color:rgba(248,81,73,.5);background:rgba(248,81,73,.08);color:#ff8b84">
        ${icon('alert')}<div>Последняя ошибка агента: <code class="mono">${esc(data.last_error)}</code></div>
      </div>` : ''}
      <div class="banner" style="border-color:var(--line-strong);background:rgba(124,92,255,.06);color:var(--text-dim)">
        ${icon('info')}
        <div>Агент сам забирает этот конфиг по токену и присылает статистику.
        Кнопка «Подключить» в карточке сервера выдаёт команду установки для чистого VPS.</div>
      </div>
      <div class="field" style="margin-bottom:12px">
        <label>Токен агента</label>
        <div class="sub-url-row">
          <input class="input mono" value="${esc(token)}" readonly onclick="this.select()">
          <button class="icon-btn" data-act="copy-token" title="Копировать">${icon('copy')}</button>
          <button class="icon-btn" data-act="rotate-token" title="Перевыпустить">${icon('refresh')}</button>
        </div>
      </div>
      <div class="field" style="margin-bottom:12px">
        <label>Фрагмент docker-compose.yml</label>
        <div class="code-block" style="max-height:170px">${esc(envSnippet)}</div>
      </div>
      <div class="field">
        <label>config.json (сгенерирован автоматически)</label>
        <div class="code-block">${esc(configText)}</div>
      </div>`,
    footer: `
      <button class="btn" data-act="copy-config">${icon('copy')}Копировать JSON</button>
      <button class="btn btn-primary" data-act="download">${icon('download')}Скачать config.json</button>`,
  });

  modal.addEventListener('click', async (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    try {
      if (el.dataset.act === 'copy-config') await copy(configText, 'Конфиг скопирован');
      if (el.dataset.act === 'copy-token') await copy(token, 'Токен скопирован');
      if (el.dataset.act === 'download') download(`xray-${data.id}.json`, configText);
      if (el.dataset.act === 'rotate-token') {
        const ok = await confirmDialog({
          title: 'Перевыпустить токен?',
          text: 'Агент ноды потеряет доступ, пока вы не обновите токен в его окружении.',
          confirmText: 'Перевыпустить', danger: true,
        });
        if (!ok) return;
        await api(`/api/nodes/${data.id}/rotate-token`, { method: 'POST' });
        toast('Токен обновлён');
        closeLayer();
        openNodeConfig(data.id);
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

/* ---------------------------------------------------------------- страница */

let query = { text: '', status: 'all' };

function agentsTable(nodes) {
  const rows = nodes.map((node) => {
    const [label, tone] = HEALTH[node.health] || HEALTH.unknown;
    const mem = node.mem_total ? `${Math.round((node.mem_used / node.mem_total) * 100)}%` : '—';
    return `
      <tr>
        <td>
          <div class="cell-main">${esc(node.name)}</div>
          <div class="cell-sub mono">${esc(node.address)}:${node.port}</div>
        </td>
        <td><span class="status ${tone}"><span class="dot"></span>${esc(label)}</span></td>
        <td>${node.agent_version ? esc(node.agent_version) : '—'}</td>
        <td>${node.xray_running === null ? '—' : node.xray_running
          ? '<span class="chip mint">работает</span>' : '<span class="chip">остановлен</span>'}</td>
        <td>${node.uptime_seconds ? esc(uptimeText(node.uptime_seconds)) : '—'}</td>
        <td class="num">${node.load1 ? Number(node.load1).toFixed(2) : '—'}</td>
        <td class="num">${mem}</td>
        <td class="mono" style="font-size:11.5px">${node.cfg_revision ? esc(node.cfg_revision) : '—'}</td>
        <td>${node.last_seen ? esc(relTime(node.last_seen)) : '—'}</td>
      </tr>`;
  }).join('');
  return `
    <div class="table-wrap">
      <table class="data fixed">
        <colgroup>
          <col style="width:23%"><col style="width:12%"><col style="width:8%"><col style="width:11%">
          <col style="width:10%"><col style="width:7%"><col style="width:8%"><col style="width:12%"><col style="width:9%">
        </colgroup>
        <thead><tr>
          <th>Сервер</th><th>Статус</th><th>Агент</th><th>Xray</th><th>Uptime</th>
          <th class="num">LA1</th><th class="num">Память</th><th>Ревизия</th><th>Heartbeat</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

export async function render(container, ctx) {
  const { setActions, navigate } = ctx;
  const agentsView = new URLSearchParams((window.location.hash.split('?')[1] || '')).get('tab') === 'agents';
  const actions = setActions(
    `<button class="btn btn-primary" data-act="new">${icon('plus')}Добавить сервер</button>`,
  );
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="new"]')) openNodeForm(null, () => render(container, ctx));
  });

  container.innerHTML = '<div class="grid grid-3">'
    + Array.from({ length: 3 }).map(() => '<div class="skeleton" style="height:230px"></div>').join('')
    + '</div>';

  const response = await api('/api/nodes');
  const nodes = response.items;
  const summary = response.summary;
  const wantNew = new URLSearchParams((window.location.hash.split('?')[1] || '')).get('new') === '1';
  if (wantNew) {
    window.history.replaceState(null, '', `${window.location.pathname}#/nodes`);
    openNodeForm(null, () => render(container, ctx));
  }

  if (agentsView) {
    container.innerHTML = `
      <div class="toolbar">
        <span class="muted" style="font-size:12.5px">
          Агентов: <b style="color:var(--text-dim)">${summary.total}</b> ·
          на связи <b style="color:var(--mint)">${summary.online}</b>
          ${summary.degraded ? `· <b style="color:#e3b341">${summary.degraded} с ошибкой</b>` : ''}
          ${summary.offline ? `· <b style="color:#ff8b84">${summary.offline} не в сети</b>` : ''}
        </span>
        <div class="spacer"></div>
        <button class="btn btn-sm" data-act="refresh">${icon('refresh')}Обновить</button>
        <button class="btn btn-sm" data-act="to-nodes">${icon('server')}К серверам</button>
      </div>
      ${nodes.length ? agentsTable(nodes) : `<div class="empty">${icon('terminal')}<b>Агентов пока нет</b>
        <p>Агент ставится командой из карточки сервера — раздел «Узлы».</p></div>`}
      <div class="hint" style="margin-top:12px">
        Агент опрашивает панель каждые 30 секунд: heartbeat обновляет статус, версию Xray,
        uptime, LA1 и память, а также подтверждает ревизию применённого конфига.
      </div>`;
    bind(container, 'click', async (ev) => {
      const el = ev.target.closest('[data-act]');
      if (!el) return;
      if (el.dataset.act === 'to-nodes') navigate('#/nodes');
      if (el.dataset.act === 'refresh') await render(container, ctx);
    });
    return;
  }

  const matches = (node) => {
    if (query.text) {
      const haystack = `${node.name} ${node.address} ${node.region}`.toLowerCase();
      if (!haystack.includes(query.text.toLowerCase())) return false;
    }
    if (query.status === 'online') return node.status === 'online';
    if (query.status === 'offline') return node.health === 'offline';
    if (query.status === 'degraded') return node.health === 'degraded';
    if (query.status === 'disabled') return !node.enabled;
    return true;
  };
  const visible = nodes.filter(matches);

  const filters = [
    ['all', 'Все', nodes.length],
    ['online', 'Онлайн', summary.online],
    ['offline', 'Не в сети', summary.offline || 0],
    ['degraded', 'С ошибкой', summary.degraded || 0],
    ['disabled', 'Выключены', nodes.filter((n) => !n.enabled).length],
  ];

  container.innerHTML = `
    <div class="toolbar toolbar-wrap">
      <label class="search-field">
        ${icon('search')}
        <input class="input" id="node-search" placeholder="Поиск по названию, адресу, региону…" value="${esc(query.text)}">
      </label>
      <div class="segmented">
        ${filters.map(([key, label, count]) => `
          <button type="button" class="${query.status === key ? 'active' : ''}" data-filter="${key}">
            ${label}${count ? ` · ${count}` : ''}
          </button>`).join('')}
      </div>
      <div class="spacer"></div>
      <button class="btn btn-sm" data-act="refresh">${icon('refresh')}Обновить</button>
    </div>
    <div class="muted" style="font-size:12.5px;margin:-2px 0 14px">
      Серверов: <b style="color:var(--text-dim)">${summary.total}</b> ·
      онлайн <b style="color:var(--mint)">${summary.online}</b>
      ${summary.degraded ? `· <b style="color:#e3b341">${summary.degraded} с ошибкой</b>` : ''}
      ${summary.offline ? `· <b style="color:#ff8b84">${summary.offline} не в сети</b>` : ''}
      · суммарный трафик <b style="color:var(--text-dim)">${fmtBytes(summary.up_bytes + summary.down_bytes)}</b>
    </div>
    ${visible.length ? `<div class="grid grid-3">${visible.map(cardHtml).join('')}</div>` : `
      <div class="empty">
        ${icon('server')}
        <b>${nodes.length ? 'Ничего не найдено' : 'Серверов пока нет'}</b>
        <p>${nodes.length ? 'Измените фильтр или поисковый запрос.' : 'Создайте первый сервер: панель сгенерирует для него конфиг и команду установки.'}</p>
        <button class="btn btn-primary" data-act="new" style="margin-top:14px">${icon('plus')}Добавить сервер</button>
      </div>`}
    <div class="card" style="margin-top:18px">
      <div class="card-head"><h3>Как добавить ещё один сервер</h3>
        <span class="muted" style="font-size:12px">мультисервер</span></div>
      <div class="card-body" style="font-size:13px;color:var(--text-dim);line-height:1.75">
        <ol style="margin:0;padding-left:20px">
          <li>Создайте сервер: название, адрес, порт и протокол. Reality-ключи сгенерируются сами.</li>
          <li>Откройте «Подключить» и скопируйте команду — она поставит Xray и агент на чистый VPS
            и зарегистрирует сервер в панели.</li>
          <li>Клиенты и лимиты общие: агент раз в 30 секунд сверяет конфиг, перезапускает Xray при
            изменениях и присылает трафик. Сервер можно ограничить отдельными клиентами в их карточке.</li>
        </ol>
      </div>
    </div>`;

  const search = container.querySelector('#node-search');
  let timer = 0;
  search.addEventListener('input', () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      query.text = search.value.trim();
      const pos = search.selectionStart;
      render(container, ctx).then(() => {
        const el = container.querySelector('#node-search');
        if (el) {
          el.focus();
          el.setSelectionRange(pos, pos);
        }
      });
    }, 220);
  });

  bind(container, 'click', async (ev) => {
    const filter = ev.target.closest('[data-filter]');
    if (filter) {
      query.status = filter.dataset.filter;
      await render(container, ctx);
      return;
    }
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    const id = Number(el.dataset.id || 0);
    const act = el.dataset.act;
    const node = nodes.find((n) => n.id === id);
    try {
      if (act === 'new') {
        openNodeForm(null, () => render(container, ctx));
      } else if (act === 'edit') {
        const full = await api(`/api/nodes/${id}`);
        openNodeForm(full, () => render(container, ctx));
      } else if (act === 'connect') {
        openNodeConnect(id);
      } else if (act === 'config') {
        openNodeConfig(id);
      } else if (act === 'toggle') {
        await api(`/api/nodes/${id}`, { method: 'PATCH', body: { enabled: !(node && node.enabled) } });
        toast(node && node.enabled ? 'Сервер выключен' : 'Сервер включён');
        await render(container, ctx);
      } else if (act === 'probe') {
        el.disabled = true;
        el.innerHTML = icon('refresh');
        const result = await api(`/api/nodes/${id}/probe`, { method: 'POST' });
        toast(result.ok ? `Порт открыт · ${result.latency_ms} мс` : `Недоступен: ${result.error}`, result.ok ? 'ok' : 'err');
        await render(container, ctx);
      } else if (act === 'delete') {
        const ok = await confirmDialog({
          title: 'Удалить сервер?',
          text: `<b>${esc(node ? node.name : '')}</b> исчезнет из панели, его статистика тоже. `
            + 'Сам Xray на сервере продолжит работать — остановите его вручную или удалите агент.',
          confirmText: 'Удалить', danger: true,
        });
        if (!ok) return;
        await api(`/api/nodes/${id}`, { method: 'DELETE' });
        toast('Сервер удалён');
        await render(container, ctx);
      } else if (act === 'refresh') {
        await render(container, ctx);
        toast('Статусы обновлены');
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}
