/* Маршрутизация: правила Xray и DNS-пресет. */

import {
  api, esc, formChecked, formValue, icon, toast,
} from '../core.js';

function sw(name, label, checked, hint = '') {
  return `<div class="field">
    <label class="switch">
      <input type="checkbox" name="${name}" ${checked ? 'checked' : ''}>
      <span class="track"></span><span class="label">${label}</span>
    </label>
    ${hint ? `<div class="hint">${hint}</div>` : ''}
  </div>`;
}

const DNS_OPTIONS = [
  ['cloudflare', 'Cloudflare 1.1.1.1'],
  ['google', 'Google 8.8.8.8'],
  ['quad9', 'Quad9 9.9.9.9'],
  ['system', 'Системный'],
];

export async function render(container, ctx) {
  const { setActions } = ctx;
  setActions('');
  container.innerHTML = '<div class="skeleton" style="height:320px"></div>';
  const settings = await api('/api/settings');
  const outbounds = await api('/api/outbounds').catch(() => ({ items: [] }));
  const tags = [
    ['direct', 'direct'],
    ['block', 'block'],
    ...(outbounds.items || []).map((item) => [item.tag, `${item.name} (${item.tag})`]),
  ];

  const rules = [{ type: 'field', inboundTag: ['api'], outboundTag: 'api' }];
  if (settings.block_bittorrent) rules.push({ type: 'field', protocol: ['bittorrent'], outboundTag: 'block' });
  if (settings.block_ads) rules.push({ type: 'field', domain: ['geosite:category-ads-all'], outboundTag: 'block' });
  if (settings.block_private) rules.push({ type: 'field', ip: ['geoip:private'], outboundTag: 'block' });
  if (settings.route_ru_direct) {
    rules.push({ type: 'field', domain: ['geosite:category-ru'], outboundTag: 'direct' });
    rules.push({ type: 'field', ip: ['geoip:ru'], outboundTag: 'direct' });
  }
  const preview = JSON.stringify(
    { routing: { domainStrategy: 'IPIfNonMatch', rules } },
    null,
    2,
  );

  container.innerHTML = `
    <form class="card" id="routing-form">
      <div class="card-head">
        <div><h3>Правила маршрутизации</h3>
          <div class="hint">Применяются к конфигам нод при следующем опросе агента.</div></div>
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
              ${DNS_OPTIONS.map(([value, label]) => `<option value="${value}" ${settings.dns_preset === value ? 'selected' : ''}>${esc(label)}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label>Основной исходящий</label>
            <select class="select" name="route_default_outbound">
              <option value="">первый в списке</option>
              ${tags.map(([value, label]) => `<option value="${esc(value)}" ${settings.route_default_outbound === value ? 'selected' : ''}>${esc(label)}</option>`).join('')}
            </select>
            <div class="hint">Какой outbound использовать по умолчанию.</div>
          </div>
          <div class="field">
            <label>Период хранения статистики, дней</label>
            <input class="input" name="traffic_retention_days" type="number" min="7" max="3650" value="${settings.traffic_retention_days}">
            <div class="hint">Старые срезы трафика удаляются при обслуживании.</div>
          </div>
        </div>
        <div style="margin-top:16px"><button class="btn btn-primary" type="submit">${icon('check')}Сохранить</button></div>
      </div>
    </form>
    <div class="card" style="margin-top:16px">
      <div class="card-head"><h3>Как это выглядит в конфиге</h3></div>
      <div class="card-body">
        <pre class="code-block">${esc(preview)}</pre>
      </div>
    </div>`;

  container.querySelector('#routing-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    try {
      await api('/api/settings', {
        method: 'PATCH',
        body: {
          block_bittorrent: formChecked(form, 'block_bittorrent'),
          block_ads: formChecked(form, 'block_ads'),
          block_private: formChecked(form, 'block_private'),
          route_ru_direct: formChecked(form, 'route_ru_direct'),
          dns_preset: formValue(form, 'dns_preset', 'cloudflare'),
          route_default_outbound: formValue(form, 'route_default_outbound', ''),
          traffic_retention_days: Number(formValue(form, 'traffic_retention_days', '90') || 90),
        },
      });
      toast('Маршрутизация сохранена');
      render(container, ctx);
    } catch (err) { toast(err.message, 'err'); }
  });
}
