/* Сканер целей REALITY: TLS-проба домена или диапазона IP. */

import { api, closeLayer, esc, icon, openModal, toast } from '../core.js';

const STATUS_TITLES = {
  ok: 'Подходит',
  weak: 'Сомнительно',
  fail: 'Недоступно',
  pending: 'В очереди',
};

function statusCell(item) {
  const status = item.status || 'fail';
  return `<span class="scan-status ${status}" title="${esc(item.reason || '')}">${STATUS_TITLES[status] || status}</span>`;
}

function rowHtml(item, index, node) {
  const latency = item.latency_ms ? `${item.latency_ms} мс` : '—';
  return `
    <tr data-index="${index}">
      <td class="mono">${esc(item.target || '')}</td>
      <td>${statusCell(item)}</td>
      <td class="mono">${esc(item.tls || '—')}</td>
      <td class="mono">${esc(item.alpn || '—')}</td>
      <td class="mono">${esc(item.kex || '—')}</td>
      <td class="mono trunc" title="${esc(item.cert || '')}">${esc(item.cert || '—')}</td>
      <td class="mono trunc" title="${esc(item.chain || '')}">${esc(item.chain || '—')}</td>
      <td class="num ${item.latency_ms > 800 ? 'warn' : ''}">${latency}</td>
      <td class="right">${
        item.status === 'fail'
          ? '<span class="muted">—</span>'
          : `<button class="link-btn" data-pick="${index}" ${node ? '' : 'disabled title="Откройте сканер из узла, чтобы применить цель"'}>Выбрать</button>`
      }</td>
    </tr>`;
}

export function openRealityScanner({ node = null, targets = '', autoStart = false, onApply = null } = {}) {
  const view = {
    jobId: null,
    timer: null,
    results: [],
    total: 0,
    running: false,
    filter: 'all',
    query: '',
    notified: false,
  };

  const modal = openModal({
    title: 'Сканер целей REALITY',
    wide: true,
    body: `
      <p class="hint" style="margin:-4px 0 14px;line-height:1.6">
        Проверьте домен или просканируйте диапазон IP / CIDR, чтобы обнаружить новые цели REALITY
        по их сертификатам. Оставьте поле пустым для проверки обычных кандидатов.
      </p>
      <div class="scan-bar">
        <input class="input mono" id="scan-input" spellcheck="false"
               value="${esc(targets)}"
               placeholder="IP, CIDR или домен — пусто для обычных кандидатов">
        <button class="btn btn-primary" data-act="scan">${icon('radar')}Сканировать</button>
      </div>
      <div class="scan-meta" id="scan-meta"></div>
      <div class="scan-table-wrap" id="scan-wrap">
        <table class="data scan-table">
          <colgroup>
            <col style="width:14%"><col style="width:10%"><col style="width:7%">
            <col style="width:6%"><col style="width:12%"><col style="width:14%">
            <col style="width:16%"><col style="width:10%"><col style="width:11%">
          </colgroup>
          <thead>
            <tr>
              <th>Цель</th><th>Статус</th><th>TLS</th><th>ALPN</th>
              <th>Обмен ключами</th><th>Сертификат</th>
              <th>Цепочка сертификата</th><th class="right">Задержка</th><th></th>
            </tr>
          </thead>
          <tbody id="scan-body">
            <tr class="scan-placeholder"><td colspan="9" class="muted">
              Нажмите «Сканировать», чтобы проверить цели.
            </td></tr>
          </tbody>
        </table>
      </div>`,
    footer: `
      <span class="muted" id="scan-note" style="margin-right:auto;font-size:12px"></span>
      <button class="btn" data-act="again">Пересканировать</button>
      <button class="btn btn-primary" data-close>Закрыть</button>`,
    onClose: () => stopPolling(),
  });
  modal.classList.add('xwide');

  const input = modal.querySelector('#scan-input');
  const body = modal.querySelector('#scan-body');
  const meta = modal.querySelector('#scan-meta');
  const note = modal.querySelector('#scan-note');
  const scanBtn = modal.querySelector('[data-act="scan"]');

  function stopPolling() {
    if (view.timer) clearInterval(view.timer);
    view.timer = null;
    view.running = false;
  }

  function applyFilter(items) {
    const query = view.query.trim().toLowerCase();
    return items.filter((item) => {
      if (view.filter !== 'all' && (item.status || 'fail') !== view.filter) return false;
      if (!query) return true;
      return `${item.target} ${item.cert} ${item.chain}`.toLowerCase().includes(query);
    });
  }

  function renderRows() {
    const items = applyFilter(view.results);
    if (!items.length) {
      const text = view.running
        ? 'Сканирую… первые результаты появятся через пару секунд.'
        : 'Ничего не найдено по заданным условиям.';
      body.innerHTML = `<tr class="scan-placeholder"><td colspan="9" class="muted">${text}</td></tr>`;
      return;
    }
    body.innerHTML = items.map((item) => rowHtml(item, view.results.indexOf(item), node)).join('');
  }

  function renderMeta() {
    const counts = { ok: 0, weak: 0, fail: 0 };
    view.results.forEach((item) => {
      const status = item.status || 'fail';
      counts[status] = (counts[status] || 0) + 1;
    });
    const done = view.results.length;
    const total = view.total || done;
    const chips = [
      ['all', `Все · ${done}`],
      ['ok', `Подходит · ${counts.ok}`],
      ['weak', `Сомнительно · ${counts.weak}`],
      ['fail', `Недоступно · ${counts.fail}`],
    ];
    meta.innerHTML = `
      <div class="scan-filters">
        ${chips.map(([key, label]) => `<button class="chip-btn ${view.filter === key ? 'active' : ''}" data-filter="${key}">${label}</button>`).join('')}
      </div>
      <div class="scan-progress">
        ${view.running ? '<span class="spinner"></span>' : icon('check')}
        <span>${done} из ${total}</span>
      </div>`;
    if (view.running) {
      note.innerHTML = `<button class="link-btn" data-act="cancel">Остановить скан</button>`;
    } else if (done) {
      note.textContent = `Проверено целей: ${done}`;
    } else {
      note.textContent = '';
    }
  }

  async function poll() {
    if (!view.jobId) return;
    try {
      const data = await api(`/api/reality/scan/${view.jobId}`);
      view.results = data.results || [];
      view.total = data.total || view.results.length;
      if (data.status !== 'running') stopPolling();
      renderRows();
      renderMeta();
      if (data.status === 'done' && !view.notified) {
        view.notified = true;
        toast(`Скан завершён: подходит ${(data.counts || {}).ok || 0}`);
      }
    } catch (err) {
      stopPolling();
      toast(err.message, 'err');
    }
  }

  async function startScan() {
    if (view.running) return;
    const raw = input.value.trim();
    view.results = [];
    view.total = 0;
    view.filter = 'all';
    view.query = '';
    view.running = true;
    view.notified = false;
    scanBtn.disabled = true;
    body.innerHTML = '<tr class="scan-placeholder"><td colspan="9" class="muted">Сканирую…</td></tr>';
    renderMeta();
    try {
      const job = await api('/api/reality/scan', {
        method: 'POST',
        body: { targets: raw, port: 443, timeout: 5, workers: 16 },
      });
      view.jobId = job.job_id;
      view.total = job.total;
      renderMeta();
      view.timer = setInterval(poll, 900);
      await poll();
    } catch (err) {
      view.running = false;
      toast(err.message, 'err');
    } finally {
      scanBtn.disabled = false;
    }
  }

  async function pick(index) {
    const item = view.results[index];
    if (!item || !node) return;
    try {
      const updated = await api('/api/reality/apply', {
        method: 'POST',
        body: { node_id: node.id, host: item.host || item.target.split(':')[0], port: item.port || 443 },
      });
      toast(`Цель ${item.host || item.target} применена к ноде «${node.name}»`);
      if (onApply) onApply(updated);
      closeLayer();
    } catch (err) {
      toast(err.message, 'err');
    }
  }

  modal.addEventListener('click', (ev) => {
    const scan = ev.target.closest('[data-act="scan"]');
    if (scan) { startScan(); return; }
    const again = ev.target.closest('[data-act="again"]');
    if (again) { startScan(); return; }
    const cancel = ev.target.closest('[data-act="cancel"]');
    if (cancel) {
      if (view.jobId) api(`/api/reality/scan/${view.jobId}/cancel`, { method: 'POST' }).catch(() => {});
      return;
    }
    const filter = ev.target.closest('[data-filter]');
    if (filter) {
      view.filter = filter.dataset.filter;
      renderRows();
      renderMeta();
      return;
    }
    const pickBtn = ev.target.closest('[data-pick]');
    if (pickBtn) pick(Number(pickBtn.dataset.pick));
  });

  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      startScan();
    }
  });

  if (autoStart) startScan();
  return modal;
}
