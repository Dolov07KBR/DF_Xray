/* Группы клиентов: объединение пользователей для фильтров и массовых действий. */

import {
  api, bind, closeLayer, confirmDialog, esc, fmtBytes, formValue, icon, openModal, toast,
} from '../core.js';

const COLORS = ['#7c5cff', '#4f8cff', '#3fb950', '#d29922', '#f85149', '#a371f7', '#2dd4bf'];

function groupCard(group) {
  return `
    <div class="card group-card" data-id="${group.id}" style="--group-color:${esc(group.color || COLORS[0])}">
      <div class="gc-head">
        <span class="gc-dot"></span>
        <div style="flex:1;min-width:0">
          <h3>${esc(group.name)}</h3>
          <div class="muted" style="font-size:12px">${esc(group.note || 'Без описания')}</div>
        </div>
        <button class="icon-btn" data-act="edit" data-id="${group.id}" title="Изменить">${icon('edit')}</button>
        <button class="icon-btn" data-act="delete" data-id="${group.id}" title="Удалить">${icon('trash')}</button>
      </div>
      <div class="gc-stats">
        <div><span>Клиентов</span><b>${group.users_count}</b></div>
        <div><span>Трафик</span><b>${fmtBytes(group.used_bytes)}</b></div>
      </div>
      <div class="gc-foot">
        <button class="btn btn-sm" data-act="open" data-id="${group.id}">${icon('users')}Клиенты группы</button>
      </div>
    </div>`;
}

function openGroupForm(group = null, onSaved = null) {
  const modal = openModal({
    title: group ? 'Изменить группу' : 'Новая группа',
    body: `
      <form id="group-form" autocomplete="off">
        <div class="form-grid">
          <div class="field full">
            <label>Название *</label>
            <input class="input" name="name" required value="${esc(group ? group.name : '')}" placeholder="Например: Семья">
          </div>
          <div class="field full">
            <label>Цвет</label>
            <div class="color-picker">
              ${COLORS.map((color) => `
                <label class="color-swatch" style="--swatch:${color}">
                  <input type="radio" name="color" value="${color}" ${((group && group.color) || COLORS[0]) === color ? 'checked' : ''}>
                  <span></span>
                </label>`).join('')}
            </div>
          </div>
          <div class="field full">
            <label>Описание</label>
            <input class="input" name="note" value="${esc(group ? group.note : '')}" placeholder="Кому выдаём доступ">
          </div>
        </div>
      </form>`,
    footer: `
      <button class="btn" data-cancel>Отмена</button>
      <button class="btn btn-primary" data-save>${group ? 'Сохранить' : 'Создать'}</button>`,
  });

  modal.querySelector('[data-cancel]').addEventListener('click', () => closeLayer());
  modal.querySelector('[data-save]').addEventListener('click', async () => {
    const form = modal.querySelector('#group-form');
    const name = formValue(form, 'name').trim();
    if (!name) {
      toast('Укажите название группы', 'err');
      return;
    }
    const checked = form.querySelector('input[name="color"]:checked');
    const body = { name, note: formValue(form, 'note').trim(), color: checked ? checked.value : COLORS[0] };
    try {
      if (group) await api(`/api/groups/${group.id}`, { method: 'PATCH', body });
      else await api('/api/groups', { method: 'POST', body });
      toast(group ? 'Группа обновлена' : 'Группа создана');
      closeLayer();
      if (onSaved) onSaved();
    } catch (err) {
      toast(err.message, 'err');
    }
  });
  const input = modal.querySelector('input[name="name"]');
  if (input) input.focus();
}

export async function render(container, ctx) {
  const { setActions, navigate } = ctx;
  const actions = setActions(`<button class="btn btn-primary" data-act="new">${icon('plus')}Новая группа</button>`);
  actions.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-act="new"]')) openGroupForm(null, () => render(container, ctx));
  });

  container.innerHTML = '<div class="skeleton" style="height:260px"></div>';
  const data = await api('/api/groups');
  const groups = data.items || [];

  if (!groups.length) {
    container.innerHTML = `
      <div class="empty">
        ${icon('layers')}
        <b>Групп пока нет</b>
        <p>Объедините клиентов в группы, чтобы фильтровать их и выдавать доступы пачкой.</p>
        <button class="btn btn-primary" style="margin-top:14px" data-act="new">${icon('plus')}Новая группа</button>
      </div>`;
    bind(container, 'click', (ev) => {
      if (ev.target.closest('[data-act="new"]')) openGroupForm(null, () => render(container, ctx));
    });
    return;
  }

  container.innerHTML = `
    <div class="group-grid">${groups.map(groupCard).join('')}</div>
    <p class="hint" style="margin-top:12px">Группа не влияет на доступ: она нужна для фильтров и быстрых действий с клиентами.</p>`;

  bind(container, 'click', async (ev) => {
    const edit = ev.target.closest('[data-act="edit"]');
    const remove = ev.target.closest('[data-act="delete"]');
    const open = ev.target.closest('[data-act="open"]');
    if (edit) {
      const group = groups.find((item) => String(item.id) === edit.dataset.id);
      openGroupForm(group, () => render(container, ctx));
    } else if (remove) {
      const group = groups.find((item) => String(item.id) === remove.dataset.id);
      const ok = await confirmDialog({
        title: `Удалить группу «${group.name}»?`,
        text: 'Клиенты останутся в панели — они просто выйдут из группы.',
        confirmText: 'Удалить',
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/api/groups/${group.id}`, { method: 'DELETE' });
        toast('Группа удалена');
        render(container, ctx);
      } catch (err) { toast(err.message, 'err'); }
    } else if (open) {
      navigate(`#/users?group=${open.dataset.id}`);
    }
  });
}
