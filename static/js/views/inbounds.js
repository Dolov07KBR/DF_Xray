/* Входящие: протоколы, транспорт и маскировка по каждой ноде. */

import {
  api, bind, esc, icon, state, statusBadge,
} from '../core.js';
import { openNodeForm } from './nodes.js';
import { openRealityScanner } from './scanner.js';

const PROTOCOL_TITLES = { vless: 'VLESS', vmess: 'VMess', trojan: 'Trojan' };
const TRANSPORT_TITLES = { tcp: 'TCP', ws: 'WebSocket', grpc: 'gRPC', xhttp: 'XHTTP', h2: 'HTTP/2' };
const SECURITY_TITLES = { reality: 'Reality', tls: 'TLS', none: 'Без шифрования' };

function inboundRow(node) {
  const target = node.security === 'reality'
    ? (node.dest || node.sni || '—')
    : (node.sni || '—');
  const flow = node.flow ? `<span class="chip chip-quiet">${esc(node.flow)}</span>` : '';
  return `
    <tr data-id="${node.id}">
      <td>
        <div class="cell-main">${esc(node.name)}</div>
        <div class="cell-sub mono">${esc(node.address)}:${node.port}</div>
      </td>
      <td><span class="chip chip-proto">${PROTOCOL_TITLES[node.protocol] || esc(node.protocol)}</span>${flow}</td>
      <td>${esc(TRANSPORT_TITLES[node.transport] || node.transport)}</td>
      <td>${esc(SECURITY_TITLES[node.security] || node.security)}</td>
      <td class="num">${node.port}</td>
      <td class="mono trunc" title="${esc(target)}">${esc(target)}</td>
      <td class="num">${node.users_count ?? 0}</td>
      <td>${statusBadge(node.status)}</td>
      <td class="right nowrap">
        ${node.security === 'reality'
          ? `<button class="icon-btn" data-act="scan" data-id="${node.id}" title="Подобрать цель сканером">${icon('radar')}</button>`
          : ''}
        <button class="icon-btn" data-act="edit" data-id="${node.id}" title="Изменить входящий">${icon('edit')}</button>
      </td>
    </tr>`;
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  const actions = setActions(`
    <button class="btn" data-act="scanner">${icon('radar')}Сканер целей</button>
    <button class="btn btn-primary" data-act="new">${icon('plus')}Новый входящий</button>`);
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="new"]')) openNodeForm();
    if (ev.target.closest('[data-act="scanner"]')) openRealityScanner();
  });

  container.innerHTML = '<div class="skeleton" style="height:320px"></div>';
  const data = await api('/api/nodes');
  const nodes = data.items || [];
  state.nodes = nodes;

  if (!nodes.length) {
    container.innerHTML = `
      <div class="empty">
        ${icon('inbox')}
        <b>Входящих пока нет</b>
        <p>Создайте первый входящий — он же узел с адресом и протоколом.</p>
        <button class="btn btn-primary" style="margin-top:14px" data-act="new">${icon('plus')}Новый входящий</button>
      </div>`;
    bind(container, 'click', (ev) => {
      if (ev.target.closest('[data-act="new"]')) openNodeForm();
    });
    return;
  }

  const totals = nodes.reduce((acc, node) => {
    acc[node.protocol] = (acc[node.protocol] || 0) + 1;
    return acc;
  }, {});

  container.innerHTML = `
    <div class="toolbar">
      <div class="chips">
        ${Object.entries(totals).map(([key, value]) =>
          `<span class="chip chip-quiet">${PROTOCOL_TITLES[key] || esc(key)} · ${value}</span>`).join('')}
        <span class="chip chip-quiet">Reality · ${nodes.filter((n) => n.security === 'reality').length}</span>
      </div>
      <div class="spacer"></div>
      <span class="muted" style="font-size:12.5px">всего входящих: <b>${nodes.length}</b></span>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table class="data fixed">
          <colgroup>
            <col style="width:20%"><col style="width:12%"><col style="width:9%">
            <col style="width:13%"><col style="width:5%"><col style="width:15%">
            <col style="width:8%"><col style="width:8%"><col style="width:10%">
          </colgroup>
          <thead><tr>
            <th>Входящий</th><th>Протокол</th><th>Транспорт</th><th>Безопасность</th>
            <th class="num">Порт</th><th>Цель / SNI</th><th class="num">Клиенты</th>
            <th>Статус</th><th></th>
          </tr></thead>
          <tbody>${nodes.map(inboundRow).join('')}</tbody>
        </table>
      </div>
    </div>
    <p class="hint" style="margin-top:12px;line-height:1.7">
      Для Reality цель (SNI и dest) можно подобрать сканером: он проверит TLS, ALPN и сертификат домена.
    </p>`;

  bind(container, 'click', async (ev) => {
    const scan = ev.target.closest('[data-act="scan"]');
    if (scan) {
      const node = nodes.find((item) => String(item.id) === scan.dataset.id);
      openRealityScanner({
        node,
        targets: node ? (node.sni || '') : '',
        onApply: () => api('/api/nodes').then((res) => {
          state.nodes = res.items;
          render(container, ctx);
        }),
      });
      return;
    }
    const edit = ev.target.closest('[data-act="edit"]');
    if (edit) {
      const node = nodes.find((item) => String(item.id) === edit.dataset.id);
      openNodeForm(node, () => render(container, ctx));
    }
  });
}
