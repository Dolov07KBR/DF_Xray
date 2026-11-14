/* Ноды: карточки, конструктор конфига, проверка доступности, Reality-ключи. */

import {
  api, bind, closeLayer, confirmDialog, copy, download, esc, fmtBytes, formField,
  formValue, icon, openModal, protoChips, relTime, statusBadge, toast,
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

function cardHtml(node) {
  const traffic = node.up_bytes + node.down_bytes;
  return `
    <div class="card node-card" data-id="${node.id}">
      <div class="nc-head">
        <div style="flex:1;min-width:0">
          <h3>${esc(node.name)}</h3>
          <div class="nc-addr">${esc(node.address)}:${node.port}</div>
        </div>
        ${statusBadge(node.status)}
      </div>
      <div class="chips">${protoChips(node)}${node.enabled ? '' : '<span class="chip">выключена</span>'}</div>
      <div class="nc-stats">
        <div class="nc-stat"><span>Клиенты</span><b>${node.users_count ?? 0}</b></div>
        <div class="nc-stat"><span>Трафик</span><b>${fmtBytes(traffic)}</b></div>
        <div class="nc-stat"><span>На связи</span><b style="font-size:11.5px">${esc(relTime(node.last_seen))}</b></div>
      </div>
      <div class="nc-foot">
        <button class="btn btn-sm btn-primary" data-act="config" data-id="${node.id}">${icon('terminal')}Конфиг</button>
        <button class="btn btn-sm" data-act="probe" data-id="${node.id}">${icon('wifi')}Проверить</button>
        <div class="spacer"></div>
        <button class="icon-btn" data-act="edit" data-id="${node.id}" title="Изменить">${icon('edit')}</button>
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
          ${field('Сертификат (путь в контейнере)', `<input class="input mono" name="cert_file" value="${value('cert_file', '/etc/xray/cert/fullchain.pem')}">`)}
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
        ${field('Заметка', `<textarea class="textarea" name="note" rows="2">${value('note')}</textarea>`, '', )}
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
    title: isEdit ? `Нода · ${node.name}` : 'Новая нода',
    wide: true,
    body: nodeFormHtml(node),
    footer: `
      <button class="btn" data-act="cancel">Отмена</button>
      <button class="btn btn-primary" data-act="save">${isEdit ? 'Сохранить' : 'Создать ноду'}</button>`,
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
        toast('Нода обновлена');
      } else {
        saved = await api('/api/nodes', { method: 'POST', body: data });
        toast('Нода создана');
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
      if (!isEdit) openNodeConfig(saved.id);
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

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
        <span class="chip">agent token</span>
      </div>
      <div class="banner" style="border-color:var(--line-strong);background:rgba(124,92,255,.06);color:var(--text-dim)">
        ${icon('info')}
        <div>Агент ноды сам заберёт конфиг по токену и будет присылать статистику.
        Добавьте ноду в <code class="mono">docker-compose.yml</code> с этими переменными.</div>
      </div>
      <div class="field" style="margin-bottom:12px">
        <label>Токен ноды</label>
        <div class="sub-url-row">
          <input class="input mono" value="${esc(token)}" readonly onclick="this.select()">
          <button class="icon-btn" data-act="copy-token" title="Копировать">${icon('copy')}</button>
          <button class="icon-btn" data-act="rotate-token" title="Перевыпустить">${icon('refresh')}</button>
        </div>
      </div>
      <div class="field" style="margin-bottom:12px">
        <label>Фрагмент docker-compose.yml</label>
        <div class="code-block" id="env-code" style="max-height:170px">${esc(envSnippet)}</div>
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
        const fresh = await api(`/api/nodes/${data.id}/rotate-token`, { method: 'POST' });
        toast('Токен обновлён');
        closeLayer();
        openNodeConfig(data.id);
        void fresh;
      }
    } catch (err) {
      toast(err.message, 'err');
    }
  });
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  const actions = setActions(
    `<button class="btn btn-primary" data-act="new">${icon('plus')}Добавить ноду</button>`,
  );
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="new"]')) openNodeForm(null, () => render(container, ctx));
  });

  container.innerHTML = '<div class="grid grid-3">'
    + Array.from({ length: 3 }).map(() => '<div class="skeleton" style="height:210px"></div>').join('')
    + '</div>';

  const response = await api('/api/nodes');
  const nodes = response.items;

  container.innerHTML = `
    <div class="toolbar">
      <span class="muted" style="font-size:12.5px">
        Всего нод: <b style="color:var(--text-dim)">${response.summary.total}</b> ·
        онлайн <b style="color:var(--mint)">${response.summary.online}</b> ·
        суммарный трафик <b style="color:var(--text-dim)">${fmtBytes(response.summary.up_bytes + response.summary.down_bytes)}</b>
      </span>
      <div class="spacer"></div>
      <button class="btn btn-sm" data-act="refresh">${icon('refresh')}Обновить статусы</button>
    </div>
    ${nodes.length ? `<div class="grid grid-3">${nodes.map(cardHtml).join('')}</div>` : `
      <div class="empty">
        ${icon('server')}
        <b>Нод пока нет</b>
        <p>Создайте первую ноду: панель сгенерирует для неё config.json, а агент поднимет Xray.</p>
        <button class="btn btn-primary" data-act="new" style="margin-top:14px">${icon('plus')}Добавить ноду</button>
      </div>`}
    <div class="card" style="margin-top:18px">
      <div class="card-head"><h3>Как подключить ноду</h3></div>
      <div class="card-body" style="font-size:13px;color:var(--text-dim);line-height:1.75">
        <ol style="margin:0;padding-left:20px">
          <li>Создайте ноду и скопируйте её токен (кнопка «Конфиг»).</li>
          <li>На сервере ноды запустите контейнер <code class="mono">ghcr.io/dfxray/node</code> с переменными
            <code class="mono">DFX_PANEL_URL</code> и <code class="mono">DFX_NODE_TOKEN</code>.</li>
          <li>Агент раз в ${30} секунд забирает конфиг, проверяет его через <code class="mono">xray -test</code>
            и перезапускает Xray при изменениях, а также отдаёт статистику по трафику.</li>
        </ol>
      </div>
    </div>`;

  bind(container, 'click', async (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    const id = Number(el.dataset.id || 0);
    const act = el.dataset.act;
    try {
      if (act === 'new') {
        openNodeForm(null, () => render(container, ctx));
      } else if (act === 'edit') {
        const node = await api(`/api/nodes/${id}`);
        openNodeForm(node, () => render(container, ctx));
      } else if (act === 'config') {
        openNodeConfig(id);
      } else if (act === 'probe') {
        el.disabled = true;
        el.innerHTML = `${icon('refresh')}Проверяю…`;
        const result = await api(`/api/nodes/${id}/probe`, { method: 'POST' });
        toast(result.ok ? `Порт открыт · ${result.latency_ms} мс` : `Недоступна: ${result.error}`, result.ok ? 'ok' : 'err');
        await render(container, ctx);
      } else if (act === 'delete') {
        const node = nodes.find((n) => n.id === id);
        const ok = await confirmDialog({
          title: 'Удалить ноду?',
          text: `<b>${esc(node ? node.name : '')}</b> будет удалена из панели. Агент ноды потеряет доступ.`,
          confirmText: 'Удалить', danger: true,
        });
        if (!ok) return;
        await api(`/api/nodes/${id}`, { method: 'DELETE' });
        toast('Нода удалена');
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
