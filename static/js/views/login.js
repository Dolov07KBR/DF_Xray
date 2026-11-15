/* Экран входа в панель. */

import { api, icon } from '../core.js';

export function renderLogin(root, { onSuccess }) {
  root.innerHTML = `
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-brand">
          <div class="brand-mark">DF</div>
          <div>
            <div class="brand-name">DF_Xray<small>Panel</small></div>
          </div>
        </div>
        <h1>Вход в панель</h1>
        <p class="login-sub">Управление Xray: пользователи, подписки и ноды.</p>
        <div class="login-error" id="login-error"></div>
        <form id="login-form" autocomplete="on">
          <div class="field" style="margin-bottom:13px">
            <label for="login-user">Имя администратора</label>
            <input class="input" id="login-user" name="username" autocomplete="username" required autofocus>
          </div>
          <div class="field" style="margin-bottom:20px">
            <label for="login-pass">Пароль</label>
            <input class="input" id="login-pass" name="password" type="password" autocomplete="current-password" required>
          </div>
          <button class="btn btn-primary" type="submit" style="width:100%;height:40px" id="login-submit">
            Войти ${icon('chevron')}
          </button>
        </form>
        <div class="login-foot">
          DF_Xray Panel · GPL-3.0 · Xray-core
        </div>
      </div>
    </div>`;

  const form = root.querySelector('#login-form');
  const errorBox = root.querySelector('#login-error');
  const submit = root.querySelector('#login-submit');
  let challenge = '';

  const fail = (message) => {
    errorBox.textContent = message || 'Не удалось войти';
    errorBox.classList.add('show');
    submit.disabled = false;
    submit.innerHTML = `Войти ${icon('chevron')}`;
  };

  const askCode = (data) => {
    challenge = data.challenge || '';
    const name = data.username || form.username.value.trim();
    form.innerHTML = `
      <div class="field" style="margin-bottom:13px">
        <label for="login-code">Код из приложения-аутентификатора</label>
        <input class="input mono" id="login-code" name="code" inputmode="numeric" autocomplete="one-time-code"
               placeholder="123 456" required autofocus>
        <div class="hint">Можно ввести резервный код в формате <code class="mono">xxxx-xxxx</code>.</div>
      </div>
      <button class="btn btn-primary" type="submit" style="width:100%;height:40px" id="login-submit">Подтвердить ${icon('chevron')}</button>
      <button class="btn btn-ghost" type="button" id="login-back" style="width:100%;margin-top:10px">Другой аккаунт</button>`;
    root.querySelector('#login-back').addEventListener('click', () => renderLogin(root, { onSuccess }));
    root.querySelector('#login-code').focus();
    const codeForm = root.querySelector('#login-form');
    codeForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const box = root.querySelector('#login-error');
      const btn = root.querySelector('#login-submit');
      box.classList.remove('show');
      btn.disabled = true;
      btn.textContent = 'Проверяю…';
      try {
        const result = await api('/api/auth/login', {
          method: 'POST',
          body: { username: name, challenge, code: codeForm.code.value.trim() },
        });
        await onSuccess(result);
      } catch (err) {
        box.textContent = err.message || 'Неверный код';
        box.classList.add('show');
        btn.disabled = false;
        btn.innerHTML = `Подтвердить ${icon('chevron')}`;
        codeForm.code.select();
      }
    });
  };

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errorBox.classList.remove('show');
    submit.disabled = true;
    submit.textContent = 'Проверяю…';
    try {
      const result = await api('/api/auth/login', {
        method: 'POST',
        body: {
          username: form.username.value.trim(),
          password: form.password.value,
        },
      });
      if (result && result.totp_required) {
        askCode(result);
        return;
      }
      await onSuccess(result);
    } catch (err) {
      fail(err.message);
    }
  });
}
