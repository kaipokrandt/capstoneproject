(function () {
  const state = { csrfToken: null, me: null };
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });

  function qs(sel) { return document.querySelector(sel); }

  function setNav() {
    const page = document.body.dataset.page;
    document.querySelectorAll('.app-nav').forEach((a) => {
      if (a.dataset.nav === page) {
        a.classList.add('bg-[#ffffff]', 'text-[#002045]', 'shadow-sm');
      } else {
        a.classList.add('text-[#43474e]', 'hover:bg-[#eceef0]');
      }
    });
  }

  async function api(path, opts) {
    const options = opts || {};
    const method = options.method || 'GET';
    const headers = options.headers || {};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = state.csrfToken || '';
    }
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
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  async function refreshCsrf() {
    const data = await api('/api/auth/csrf/');
    state.csrfToken = data.csrfToken;
  }

  async function refreshMe() {
    try {
      state.me = await api('/api/auth/me/');
    } catch (e) {
      if (e.status === 401) {
        state.me = { authenticated: false };
      } else {
        throw e;
      }
    }
  }

  function setAuthPill() {
    const el = qs('#auth-pill');
    if (!el) return;
    if (state.me?.authenticated) {
      el.textContent = 'Signed in: ' + state.me.username;
    } else {
      el.textContent = 'Not signed in';
    }
  }

  async function init() {
    setNav();
    await refreshCsrf();
    await refreshMe();
    setAuthPill();
    if (!state.me?.authenticated) {
      window.location.href = '/app/login/?next=' + encodeURIComponent(window.location.pathname);
      return;
    }
    resolveReady();
    // Notify page modules that auth is confirmed so they can fetch data.
    window.dispatchEvent(new CustomEvent('wbs-auth-changed'));
    const logout = qs('#logout-btn');
    if (logout) {
      logout.addEventListener('click', async () => {
        try { await api('/api/auth/logout/', { method: 'POST', body: {} }); } catch (_e) {}
        window.location.href = '/app/login/';
      });
    }
  }

  window.WBSUI = { api, state, init, ready };
  document.addEventListener('DOMContentLoaded', init);
})();
