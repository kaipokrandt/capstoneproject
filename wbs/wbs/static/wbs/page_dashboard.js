(function () {
  let loaded = false;

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '-';
  }

  function tabify(name) {
    const tabs = ['overview', 'activity', 'checks'];
    tabs.forEach((t) => {
      const btn = document.getElementById(`tab-${t}`);
      const panel = document.getElementById(`panel-${t}`);
      if (btn) btn.className = t === name ? 'ca-btn-primary text-sm' : 'ca-btn-secondary text-sm';
      if (panel) panel.classList.toggle('hidden', t !== name);
    });
  }

  async function load() {
    if (loaded) return;
    try {
      const o = await window.WBSUI.api('/api/overview/');
      const kpis = document.querySelectorAll('#kpis .text-3xl');
      if (kpis.length === 4 && o.counts) {
        kpis[0].textContent = o.counts.patients;
        kpis[1].textContent = o.counts.devices;
        kpis[2].textContent = o.counts.sessions;
        kpis[3].textContent = o.counts.reports;
      }

      setText('status-health', (o.health || 'unknown').toUpperCase());
      setText('status-auth', o.authenticated ? 'SIGNED IN' : 'SIGNED OUT');
      setText('status-time', o.timestamp || '-');
      if (o.user) {
        setText('status-user', `${o.user.username || '-'} (${o.user.email || 'no email'})`);
      } else {
        setText('status-user', 'No active user');
      }

      setText('status-latest-session', o.latest?.session_id ?? 'none');
      setText('status-latest-report', o.latest?.report_id ?? 'none');

      setText('check-api', 'OK');
      setText('check-auth', o.authenticated ? 'OK' : 'FAIL');
      const dataReady = (o.counts?.patients || 0) + (o.counts?.devices || 0) + (o.counts?.sessions || 0) > 0;
      setText('check-data', dataReady ? 'OK' : 'EMPTY');

      loaded = true;
    } catch (e) {
      if (e.status === 401) return;
      const err = document.getElementById('status-error');
      if (err) {
        err.textContent = e.message;
        err.classList.remove('hidden');
      }
    }
  }

  function bindTabs() {
    ['overview', 'activity', 'checks'].forEach((t) => {
      const b = document.getElementById(`tab-${t}`);
      if (b) b.addEventListener('click', () => tabify(t));
    });
    tabify('overview');
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindTabs();
    window.WBSUI.ready.then(load);
  });
  window.addEventListener('wbs-auth-changed', load);
})();
