/* Конфигурации Xray: просмотр JSON по ноде и управление Reality-ключами. */

import {
  api, bind, closeLayer, confirmDialog, copy, esc, icon, openModal, toast,
} from '../core.js';
import { openRealityScanner } from './scanner.js';

let selectedNode = 0;

function tabFromHash() {
  const query = (window.location.hash.split('?')[1] || '');
  const params = new URLSearchParams(query);
  return params.get('tab') === 'reality' ? 'reality' : 'config';
}

function configHtml(node, configText, meta) {
  return `
    <div class="toolbar">
      <div class="field-inline">
        <label>Нода</label>
        <select class="select" id="xray-node" style="min-width:230px">
          ${meta.nodes.map((item) => `<option value="${item.id}" ${item.id === node.id ? 'selected' : ''}>${esc(item.name)}</option>`).join('')}
        </select>
      </div>
      <div class="spacer"></div>
      <button class="btn btn-sm" data-act="copy-config">${icon('copy')}Копировать</button>
      <a class="btn btn-sm" href="/api/nodes/${node.id}/config?download=1" download>${icon('download')}Скачать</a>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h3>${esc(node.name)}</h3>
          <div class="hint">${esc(node.address)}:${node.port} · ${esc(node.protocol)} / ${esc(node.transport)} / ${esc(node.security)}</div></div>
        <span class="chip chip-quiet">${meta.users} клиентов</span>
      </div>
      <div class="card-body" style="padding:0">
        <pre class="code-block" id="xray-config" style="max-height:520px;overflow:auto;margin:0;border-radius:0 0 var(--radius) var(--radius)">${esc(configText)}</pre>
      </div>
    </div>
    <p class="hint" style="margin-top:12px">Конфиг генерируется на лету из данных панели и отдаётся агенту ноды по токену.</p>`;
}

function realityHtml(nodes) {
  const rows = nodes.map((node) => `
    <tr data-id="${node.id}">
      <td>
        <div class="cell-main">${esc(node.name)}</div>
        <div class="cell-sub mono">${esc(node.address)}:${node.port}</div>
      </td>
      <td class="mono">${esc(node.sni || '—')}</td>
      <td class="mono trunc" title="${esc(node.dest || '')}">${esc(node.dest || '—')}</td>
      <td class="mono trunc" title="${esc(node.public_key || '')}">${esc(node.public_key || '—')}</td>
      <td class="mono">${esc(node.short_id || '—')}</td>
      <td class="right nowrap">
        <button class="btn btn-sm" data-act="scan" data-id="${node.id}">${icon('radar')}Цель</button>
        <button class="btn btn-sm" data-act="keys" data-id="${node.id}">${icon('key')}Ключи</button>
      </td>
    </tr>`).join('');
  return `
    <div class="card">
      <div class="table-wrap">
        <table class="data">
          <thead><tr>
            <th>Нода</th><th>SNI</th><th>Dest</th><th>Публичный ключ</th><th>Short ID</th><th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
    <p class="hint" style="margin-top:12px;line-height:1.7">
      Пара x25519 генерируется на сервере. Новые ключи применяются к входящему сразу:
      агент перезапустит Xray при следующем опросе.
    </p>`;
}

export async function render(container, ctx) {
  const { setActions, navigate } = ctx;
  setActions('');
  const tab = tabFromHash();
  container.innerHTML = '<div class="skeleton" style="height:360px"></div>';
  const data = await api('/api/nodes');
  const nodes = data.items || [];

  if (!nodes.length) {
    container.innerHTML = `<div class="empty">${icon('terminal')}<b>Нод пока нет</b><p>Создайте ноду, чтобы увидеть её конфиг.</p></div>`;
    return;
  }

  const tabs = `
    <div class="tabs">
      <button class="${tab === 'config' ? 'active' : ''}" data-tab="config">${icon('terminal')}Конфиг ноды</button>
      <button class="${tab === 'reality' ? 'active' : ''}" data-tab="reality">${icon('key')}Reality-ключи</button>
    </div>`;

  const current = nodes.find((item) => item.id === selectedNode) || nodes[0];
  if (tab === 'reality') {
    container.innerHTML = tabs + realityHtml(nodes);
  } else {
    const details = await api(`/api/nodes/${current.id}`);
    const text = JSON.stringify(details.config || {}, null, 2);
    container.innerHTML = tabs + configHtml(current, text, { nodes, users: details.users_count || 0 });
  }

  const onNodeChange = async (ev) => {
    selectedNode = Number(ev.target.value);
    await render(container, ctx);
  };

  const onTab = (ev) => {
    const tabBtn = ev.target.closest('[data-tab]');
    if (tabBtn) navigate(`#/xray?tab=${tabBtn.dataset.tab}`);
  };

  bind(container, 'click', async (ev) => {
    onTab(ev);
    const copyBtn = ev.target.closest('[data-act="copy-config"]');
    if (copyBtn) {
      const select = container.querySelector('#xray-node');
      const nodeId = select ? Number(select.value) : current.id;
      const details = await api(`/api/nodes/${nodeId}`);
      copy(JSON.stringify(details.config || {}, null, 2));
      toast('Конфиг скопирован');
      return;
    }
    const scan = ev.target.closest('[data-act="scan"]');
    if (scan) {
      const node = nodes.find((item) => String(item.id) === scan.dataset.id);
      openRealityScanner({ node, targets: node.sni || '' });
      return;
    }
    const keys = ev.target.closest('[data-act="keys"]');
    if (keys) {
      const node = nodes.find((item) => String(item.id) === keys.dataset.id);
      const ok = await confirmDialog({
        title: 'Перегенерировать Reality-ключи?',
        text: `Новая пара x25519 для «${node.name}». Клиентам понадобятся обновлённые ссылки.`,
        confirmText: 'Сгенерировать',
      });
      if (!ok) return;
      try {
        const result = await api(`/api/nodes/${node.id}/reality-keys`, { method: 'POST' });
        showKeys(node, result);
        await render(container, ctx);
      } catch (err) { toast(err.message, 'err'); }
    }
  });

  const select = container.querySelector('#xray-node');
  if (select) select.addEventListener('change', onNodeChange);
}

function showKeys(node, keys) {
  const modal = openModal({
    title: 'Reality-ключи обновлены',
    body: `
      <div class="kv"><span>Нода</span><b>${esc(node.name)}</b></div>
      <div class="kv"><span>Публичный ключ</span><b class="mono">${esc(keys.public_key)}</b></div>
      <div class="kv"><span>Приватный ключ</span><b class="mono">${esc(keys.private_key)}</b></div>
      <p class="hint" style="margin-top:12px">Приватный ключ остаётся на сервере, в клиентские ссылки попадает только публичный.</p>`,
    footer: `
      <button class="btn" data-copy>${icon('copy')}Копировать публичный</button>
      <button class="btn btn-primary" data-close>Готово</button>`,
  });
  modal.querySelector('[data-copy]').addEventListener('click', () => {
    copy(keys.public_key);
    toast('Публичный ключ скопирован');
  });
  modal.querySelector('[data-close]').addEventListener('click', () => closeLayer());
}
