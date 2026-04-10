(function () {
  let loaded = false;
  let patientCache = [];

  const MOCK_DETAIL = {
    identifier: 'P-DEMO-001',
    sessions: ['Session #4021 (Completed)', 'Session #4018 (Completed)'],
    reports: ['Report #101 clinical_summary', 'Report #98 fhir_export'],
    annotations: ['Improved stance in final 20s', 'Minor right-side sway observed'],
    metrics: {
      stability_score: 84.2,
      symmetry_index: 92.4,
      cop_x: 0.53,
      cop_y: 0.48,
    },
  };

  function row(p) {
    return `<tr data-patient-id="${p.patient_id}" class="cursor-pointer hover:bg-surface-container-low/50 transition-colors">
      <td class="px-8 py-4"><div class="font-bold text-primary">${(p.first_name || '') + ' ' + (p.last_name || '')}</div></td>
      <td class="px-6 py-4"><span class="font-mono text-sm text-secondary">${p.external_id}</span></td>
      <td class="px-6 py-4">${p.date_of_birth || '-'}</td>
      <td class="px-6 py-4">${p.sex || '-'}</td>
    </tr>`;
  }

  function setList(id, items, emptyText) {
    const el = document.getElementById(id);
    if (!el) return;
    const list = (items && items.length) ? items : [emptyText];
    el.innerHTML = list.map((item) => `<li>${item}</li>`).join('');
  }

  function setMetrics(metrics) {
    const el = document.getElementById('patient-metrics');
    if (!el) return;
    const entries = Object.entries(metrics || {});
    if (!entries.length) {
      el.textContent = 'No metric summary available';
      return;
    }
    el.innerHTML = entries.map(([k, v]) => `<div class="flex items-center justify-between py-0.5"><span class="text-on-surface">${k}</span><span class="font-mono">${v}</span></div>`).join('');
  }

  function renderMockDetail() {
    document.getElementById('patient-detail-id').textContent = MOCK_DETAIL.identifier;
    setList('patient-session-history', MOCK_DETAIL.sessions, 'No sessions');
    setList('patient-reports-history', MOCK_DETAIL.reports, 'No reports');
    setList('patient-annotation-history', MOCK_DETAIL.annotations, 'No annotations');
    setMetrics(MOCK_DETAIL.metrics);
  }

  async function loadPatientDetail(patientId) {
    const patient = patientCache.find((p) => p.patient_id === patientId);
    document.getElementById('patient-detail-id').textContent = patient?.external_id || `Patient #${patientId}`;
    try {
      const [reportsRes, annotationsRes] = await Promise.all([
        window.WBSUI.api(`/api/reports/?patient_id=${patientId}`),
        window.WBSUI.api(`/api/annotations/?patient_id=${patientId}`),
      ]);
      const reports = reportsRes.items || [];
      const annotations = annotationsRes.items || [];
      const uniqueSessions = Array.from(new Set(reports.map((r) => r.session_id).filter(Boolean)));

      setList(
        'patient-session-history',
        uniqueSessions.slice(0, 6).map((sid) => `Session #${sid}`),
        'No linked sessions',
      );
      setList(
        'patient-reports-history',
        reports.slice(0, 6).map((r) => `Report #${r.report_id} ${r.report_type}`),
        'No reports',
      );
      setList(
        'patient-annotation-history',
        annotations.slice(0, 6).map((a) => `${a.author || 'clinician'}: ${a.body}`),
        'No annotations',
      );

      if (uniqueSessions.length) {
        const metricsRes = await window.WBSUI.api(`/api/sessions/${uniqueSessions[0]}/metrics/?metric_name=stability_score,symmetry_index,cop_x,cop_y,total_load&limit=30`);
        const metricSummary = {};
        Object.entries(metricsRes.series || {}).forEach(([name, series]) => {
          if (!series.length) return;
          const avg = series.reduce((s, row) => s + (Number(row.value) || 0), 0) / series.length;
          metricSummary[name] = avg.toFixed(2);
        });
        setMetrics(metricSummary);
      } else {
        setMetrics({});
      }
    } catch (_e) {
      renderMockDetail();
    }
  }

  function bindRowClicks() {
    document.querySelectorAll('#patients-tbody tr[data-patient-id]').forEach((tr) => {
      tr.addEventListener('click', () => {
        const id = Number(tr.dataset.patientId);
        if (!id) return;
        loadPatientDetail(id);
      });
    });
  }

  async function loadList() {
    if (loaded) return;
    const tbody = document.getElementById('patients-tbody');
    tbody.innerHTML = '<tr><td colspan="4" class="px-6 py-4">Loading...</td></tr>';
    try {
      const data = await window.WBSUI.api('/api/patients/');
      patientCache = data.items || [];
      tbody.innerHTML = data.items.length ? data.items.map(row).join('') : '<tr><td colspan="4" class="px-6 py-4">No patients yet</td></tr>';
      bindRowClicks();
      if (data.items.length) {
        await loadPatientDetail(data.items[0].patient_id);
      } else {
        renderMockDetail();
      }
      loaded = true;
    } catch (e) {
      if (e.status === 401) return;
      tbody.innerHTML = `<tr><td colspan="4" class="px-6 py-4 text-error">${e.message}</td></tr>`;
      renderMockDetail();
    }
  }

  async function onCreate(e) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const payload = Object.fromEntries(fd.entries());
    if (!payload.date_of_birth) delete payload.date_of_birth;
    const msg = document.getElementById('patient-msg');
    try {
      await window.WBSUI.api('/api/patients/', { method: 'POST', body: payload });
      msg.textContent = 'Patient created';
      msg.className = 'text-xs mt-2 text-secondary';
      e.currentTarget.reset();
      loaded = false;
      await loadList();
    } catch (err) {
      msg.textContent = err.message;
      msg.className = 'text-xs mt-2 text-error';
    }
  }

  function init() {
    const form = document.getElementById('patient-create-form');
    if (form) form.addEventListener('submit', onCreate);
    renderMockDetail();
    window.WBSUI.ready.then(loadList);
  }

  document.addEventListener('DOMContentLoaded', init);
  window.addEventListener('wbs-auth-changed', loadList);
})();
