/* Хосты: домены-маски (SNI / dest) из входящих и проверка их сканером. */

import {
  api, bind, copy, esc, icon, openModal, toast,
} from '../core.js';
import { openRealityScanner } from './scanner.js';

function rowHtml(host) {
  const nodes = host.nodes || [];
  return `
    <tr data-host="${esc(host.host)}">
      <td class="mono">${esc(host.host)}</td>
      <td>${nodes.map((node) => `<span class="chip chip-quiet">${esc(node.name)}</span>`).join('') || '<span class="muted">—</span>'}</td>
      <td>${(host.protocols || []).map((p) => `<span class="chip chip-proto">${esc(p.toUpperCase())}</span>`).join('')}</td>
      <td>${(host.securities || []).map((s) => `<span class="chip chip-quiet">${esc(s === 'reality' ? 'Reality' : s.toUpperCase())}</span>`).join('')}</td>
      <td class="num">${(host.ports || []).join(', ') || '—'}</td>
      <td>${host.reality ? '<span class="scan-status ok">Reality</span>' : '<span class="muted">—</span>'}</td>
      <td class="right nowrap">
        <button class="btn btn-sm" data-act="scan" data-host="${esc(host.host)}">${icon('radar')}Проверить</button>
        <button class="icon-btn" data-act="copy" data-host="${esc(host.host)}" title="Копировать">${icon('copy')}</button>
        <button class="icon-btn" data-act="apply" data-host="${esc(host.host)}" title="Применить к ноде">${icon('bolt')}</button>
      </td>
    </tr>`;
}

function openApplyDialog(host, nodes) {
  const modal = openModal({
    title: 'Применить цель',
    body: `
      <p class="hint" style="margin-top:0">Хост <b class="mono">${esc(host)}</b> будет записан как SNI и dest выбранной ноды.</p>
      <div class="field">
        <label>Нода</label>
        <select class="select" id="apply-node">
          ${nodes.map((node) => `<option value="${node.id}">${esc(node.name)} · ${esc(node.address)}:${node.port}</option>`).join('')}
        </select>
      </div>`,
    footer: `
      <button class="btn" data-cancel>Отмена</button>
      <button class="btn btn-primary" data-ok>Применить</button>`,
  });
  modal.querySelector('[data-cancel]').addEventListener('click', () => modal.querySelector('[data-close]').click());
  modal.querySelector('[data-ok]').addEventListener('click', async () => {
    const nodeId = Number(modal.querySelector('#apply-node').value);
    try {
      await api('/api/reality/apply', { method: 'POST', body: { node_id: nodeId, host, port: 443 } });
      toast('Цель применена');
      modal.querySelector('[data-close]').click();
    } catch (err) { toast(err.message, 'err'); }
  });
}

export async function render(container, ctx) {
  const { setActions } = ctx;
  const actions = setActions(`<button class="btn" data-act="scan">${icon('radar')}Сканер целей</button>`);
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="scan"]')) openRealityScanner();
  });

  container.innerHTML = '<div class="skeleton" style="height:280px"></div>';
  const [hostsData, nodesData] = await Promise.all([api('/api/hosts'), api('/api/nodes')]);
  const hosts = hostsData.items || [];
  const nodes = nodesData.items || [];

  container.innerHTML = `
    <div class="toolbar">
      <span class="muted" style="font-size:12.5px">Доменов-масок: <b>${hosts.length}</b></span>
      <div class="spacer"></div>
      <span class="muted" style="font-size:12px">Хосты берутся из SNI и dest входящих</span>
    </div>
    <div class="card">
      ${hosts.length ? `
        <div class="table-wrap">
          <table class="data">
            <thead><tr>
              <th>Домен</th><th>Ноды</th><th>Протоколы</th><th>Безопасность</th>
              <th class="num">Порты</th><th>Reality</th><th></th>
            </tr></thead>
            <tbody>${hosts.map(rowHtml).join('')}</tbody>
          </table>
        </div>` : `
        <div class="empty">
          ${icon('globe')}
          <b>Хостов нет</b>
          <p>Укажите SNI или dest у входящего — домен появится здесь.</p>
        </div>`}
    </div>`;

  bind(container, 'click', (ev) => {
    const scan = ev.target.closest('[data-act="scan"]');
    if (scan && scan.dataset.host) {
      openRealityScanner({ targets: scan.dataset.host, autoStart: true });
      return;
    }
    const copyBtn = ev.target.closest('[data-act="copy"]');
    if (copyBtn) {
      copy(copyBtn.dataset.host);
      toast('Домен скопирован');
      return;
    }
    const apply = ev.target.closest('[data-act="apply"]');
    if (apply) {
      if (!nodes.length) {
        toast('Сначала создайте ноду', 'err');
        return;
      }
      openApplyDialog(apply.dataset.host, nodes);
    }
  });
}
