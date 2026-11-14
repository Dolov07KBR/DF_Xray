/* Дашборд: сводка, график трафика, ноды, истекающие подписки, топ и журнал. */

import {
  api, bind, areaChart, auditIcon, auditLabel, auditText, esc, fmtBytes, fmtDate, icon,
  relTime, sparkline, state, statusBadge, usageBar,
} from '../core.js';

function statCard({ label, value, unit = '', iconName, tone = '', foot = '', spark = '' }) {
  return `
    <div class="card stat">
      <div class="stat-top">
        <div class="stat-ico ${tone}">${icon(iconName)}</div>
        <div class="stat-label">${esc(label)}</div>
        ${spark ? `<div class="stat-spark">${spark}</div>` : ''}
      </div>
      <div class="stat-value">${value}${unit ? `<small>${esc(unit)}</small>` : ''}</div>
      <div class="stat-foot">${foot}</div>
    </div>`;
}

export async function render(container, { setActions, navigate }) {
  const actions = setActions(`
    <button class="btn" data-act="goto-users">${icon('users')}Пользователи</button>
    <button class="btn btn-primary" data-act="new-user">${icon('plus')}Новый пользователь</button>
  `);
  actions.addEventListener('click', (ev) => {
    const el = ev.target.closest('[data-act]');
    if (!el) return;
    if (el.dataset.act === 'new-user') window.dispatchEvent(new CustomEvent('dfx:new-user'));
    if (el.dataset.act === 'goto-users') navigate('#/users');
  });
  container.innerHTML = `
    <div class="grid grid-4 section">
      ${[1, 2, 3, 4].map(() => '<div class="skeleton" style="height:118px"></div>').join('')}
    </div>
    <div class="grid grid-main section">
      <div class="skeleton" style="height:320px"></div>
      <div class="skeleton" style="height:320px"></div>
    </div>
    <div class="skeleton" style="height:240px"></div>`;

  const data = await api('/api/dashboard');
  const { counts, nodes, traffic } = data;
  const series = traffic.series || [];
  const spark = sparkline(series.map((p) => p.total));
  const activeShare = counts.total ? Math.round((counts.active / counts.total) * 100) : 0;
  const expiring = data.expiring || [];

  const banner = state.bootstrapPassword
    ? `<div class="banner">${icon('alert')}
        <div><b>Пароль администратора по умолчанию.</b>
        Смените его в разделе <a href="#/settings">Настройки → Безопасность</a>, чтобы закрыть панель от чужих.</div>
      </div>`
    : '';

  const chart = areaChart(series, { height: 250 });

  const nodesHtml = (nodes.items || [])
    .slice(0, 5)
    .map((node) => `
      <div class="audit-item">
        <div class="ico">${icon('server')}</div>
        <div class="body">
          <b>${esc(node.name)}</b>
          <span class="mono">${esc(node.address)}:${node.port} · ${esc(node.transport)}/${esc(node.security)}</span>
        </div>
        <div style="text-align:right">
          ${statusBadge(node.status)}
          <span class="muted" style="display:block;font-size:11px;margin-top:3px">${fmtBytes(node.up_bytes + node.down_bytes)}</span>
        </div>
      </div>`)
    .join('') || `<div class="empty"><b>Нод пока нет</b><p>Добавьте первую ноду в разделе «Ноды».</p></div>`;

  const expiringHtml = expiring.length
    ? `<table class="data"><tbody>${expiring.map((user) => `
        <tr>
          <td><div class="cell-user">
            <div class="avatar">${esc(user.username.slice(0, 2).toUpperCase())}</div>
            <div class="meta"><b>${esc(user.username)}</b><span>${esc(user.email || '—')}</span></div>
          </div></td>
          <td style="text-align:right"><span class="chip ${user.days_left <= 2 ? 'accent' : ''}">${esc(fmtDate(user.expires_at))}</span></td>
          <td style="text-align:right;color:var(--muted);font-size:11.5px">${esc(user.days_left)} дн</td>
        </tr>`).join('')}</tbody></table>`
    : `<div class="empty" style="border:0;padding:24px"><b>Нет подписок на грани</b><p>Ближайшие 7 дней свободны.</p></div>`;

  const topHtml = (data.top || []).length
    ? `<div class="top-list">${data.top.map((user, index) => {
      const max = Math.max(...data.top.map((u) => u.used_bytes), 1);
      return `
        <div class="top-item">
          <div class="avatar" style="background:${index === 0 ? 'var(--grad)' : '#1c2536'};color:${index === 0 ? '#fff' : '#aab4c8'}">${esc(user.username.slice(0, 2).toUpperCase())}</div>
          <div class="name">${esc(user.username)}</div>
          <div class="bar"><i style="width:${Math.max((user.used_bytes / max) * 100, 2).toFixed(1)}%"></i></div>
          <div class="val">${fmtBytes(user.used_bytes)}</div>
        </div>`;
    }).join('')}</div>`
    : `<div class="empty" style="border:0;padding:24px"><b>Пока нет трафика</b></div>`;

  const auditHtml = (data.audit || []).map((item) => `
    <div class="audit-item">
      <div class="ico">${icon(auditIcon(item.action))}</div>
      <div class="body">
        <b>${esc(auditLabel(item.action))}</b>
        <span>${auditText(item)}</span>
      </div>
      <div class="when">${relTime(item.created_at)}</div>
    </div>`).join('') || `<div class="empty" style="border:0;padding:24px"><b>Журнал пуст</b></div>`;

  container.innerHTML = `
    ${banner}
    <div class="grid grid-4 section">
      ${statCard({
        label: 'Пользователи',
        value: String(counts.total),
        iconName: 'users',
        tone: 'blue',
        foot: `<span class="status active" style="padding:1px 7px"><span class="dot"></span>${counts.active} активных</span>
               <span class="muted">${activeShare}% базы</span>`,
      })}
      ${statCard({
        label: 'Трафик за 30 дней',
        value: fmtBytes(traffic.last_30_days).split(' ')[0],
        unit: fmtBytes(traffic.last_30_days).split(' ')[1],
        iconName: 'activity',
        tone: 'mint',
        spark,
        foot: `<span class="muted">сегодня</span><b style="color:var(--text-dim)">${fmtBytes(traffic.today)}</b>`,
      })}
      ${statCard({
        label: 'Ноды',
        value: `${nodes.online}<small>/${nodes.total}</small>`,
        iconName: 'server',
        foot: nodes.online
          ? `<span class="muted">онлайн · трафик</span><b style="color:var(--text-dim)">${fmtBytes((nodes.items || []).reduce((acc, n) => acc + n.up_bytes + n.down_bytes, 0))}</b>`
          : '<span class="muted">нет нод онлайн</span>',
      })}
      ${statCard({
        label: 'Истекают скоро',
        value: String(expiring.length),
        iconName: 'clock',
        tone: 'amber',
        foot: `<span class="muted">в ближайшие 7 дней</span>`,
      })}
    </div>

    <div class="grid grid-main section">
      <div class="card">
        <div class="card-head">
          <div>
            <h3>Трафик по дням</h3>
            <div class="hint">Суммарно по всем нодам за 14 дней</div>
          </div>
          <div class="spacer"></div>
          <div class="chart-legend">
            <span><i style="background:#2ee6a8"></i>Отдача</span>
            <span><i style="background:#7c5cff"></i>Загрузка</span>
          </div>
        </div>
        <div class="card-body" id="chart-host">${chart.html}</div>
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Ноды</h3>
          <div class="spacer"></div>
          <button class="btn btn-ghost btn-sm" data-act="goto-nodes">Все ${icon('chevron')}</button>
        </div>
        <div class="card-body tight" style="padding:6px 16px 10px">${nodesHtml}</div>
      </div>
    </div>

    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-head"><h3>Истекают скоро</h3><div class="spacer"></div>
          <span class="chip">7 дней</span></div>
        <div class="table-wrap">${expiringHtml}</div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Топ по трафику</h3><div class="spacer"></div>
          <button class="btn btn-ghost btn-sm" data-act="goto-users">Все ${icon('chevron')}</button></div>
        <div class="card-body tight" style="padding:8px 18px 14px">${topHtml}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h3>Последние события</h3><div class="spacer"></div>
        <button class="btn btn-ghost btn-sm" data-act="goto-audit">Журнал ${icon('chevron')}</button></div>
      <div class="card-body tight" style="padding:6px 18px 10px">${auditHtml}</div>
    </div>
  `;

  chart.mount(container.querySelector('#chart-host'));

  bind(container, 'click', (ev) => {
    const btn = ev.target.closest('[data-act]');
    if (!btn) return;
    if (btn.dataset.act === 'goto-nodes') navigate('#/nodes');
    if (btn.dataset.act === 'goto-users') navigate('#/users');
    if (btn.dataset.act === 'goto-audit') navigate('#/audit');
    if (btn.dataset.act === 'new-user') window.dispatchEvent(new CustomEvent('dfx:new-user'));
  });
}
