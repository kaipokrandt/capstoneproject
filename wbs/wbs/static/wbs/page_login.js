(function () {
  async function api(path, opts) {
    const options = opts || {};
    const method = options.method || 'GET';
    const headers = options.headers || {};
    const res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const contentType = res.headers.get('content-type') || '';
    const payload = contentType.includes('application/json') ? await res.json() : null;
    if (!res.ok) {
      const err = new Error(payload?.detail || ('HTTP ' + res.status));
      err.status = res.status;
      throw err;
    }
    return payload;
  }

  async function init() {
    let csrf = '';
    try {
      const tokenResp = await api('/api/auth/csrf/');
      csrf = tokenResp.csrfToken;
    } catch (_e) {
      document.getElementById('login-error').textContent = 'Unable to initialize secure login.';
      return;
    }

    const form = document.getElementById('login-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const clinicalId = document.getElementById('clinical-id').value.trim();
      const password = document.getElementById('password').value;
      const error = document.getElementById('login-error');
      error.textContent = '';
      try {
        await api('/api/auth/login/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrf,
          },
          body: {
            username: clinicalId,
            password,
          },
        });
        const next = new URLSearchParams(window.location.search).get('next') || '/app/dashboard/';
        window.location.href = next;
      } catch (err) {
        error.textContent = err.message || 'Login failed.';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
