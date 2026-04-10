(function () {
  let loaded = false;
  let patientCache = [];
  let reportCache = [];
  let selectedPatientId = null;

  const METRIC_LABELS = {
    cop_x: 'CoP Lateral Stability',
    cop_y: 'CoP Anterior Stability',
    total_load: 'Load Balance',
    stability_score: 'Postural Stability Score',
    symmetry_index: 'Pressure Symmetry',
  };

  const REPORT_TYPE_LABELS = {
    clinical_summary: 'Balance Assessment Report',
    fhir_export: 'EMR Export Bundle',
  };

  const MOCK_DETAIL = {
    identifier: 'P-DEMO-001',
    summaryMeta: 'Last visit: Apr 5, 2026 | Sessions: 5',
    risk: 'Moderate',
    sessions: [
      'Session #4021 · Apr 5, 2026 · 30 sec stance · Flag: Stable',
      'Session #4018 · Apr 2, 2026 · 30 sec stance · Flag: Needs Review',
    ],
    reports: ['Balance Assessment Report · Report #101', 'EMR Export Bundle · Report #98'],
    annotations: ['2026-04-05 · clinician · Session #4021 · Improved stance in final 20s'],
    metrics: {
      'Postural Stability Score': '84.20',
      'Pressure Symmetry': '92.40%',
      'CoP Lateral Stability': '0.53 grid_x',
      'CoP Anterior Stability': '0.48 grid_y',
    },
  };

  function fmtDate(value) {
    if (!value) return 'No recent session';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return String(value);
    return dt.toLocaleDateString();
  }

  function fmtDateTime(value) {
    if (!value) return '-';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return String(value);
    return dt.toLocaleString();
  }

  function usToDate(us) {
    const n = Number(us);
    if (!Number.isFinite(n)) return null;
    return new Date(Math.floor(n / 1000));
  }

  function fmtDurationSec(startUs, endUs) {
    const s = Number(startUs);
    const e = Number(endUs);
    if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return '-';
    return `${Math.round((e - s) / 1_000_000)} sec`;
  }

  function reportDisplayType(reportType) {
    return REPORT_TYPE_LABELS[reportType] || String(reportType || 'Clinical Report').replaceAll('_', ' ');
  }

  function riskBandFromScore(score) {
    const n = Number(score);
    if (!Number.isFinite(n)) return 'Unknown';
    if (n >= 70) return 'High';
    if (n >= 40) return 'Moderate';
    return 'Low';
  }

  function getPatientReports(patientId) {
    return reportCache.filter((r) => {
      if (Number(r.patient_id) === Number(patientId)) return true;
      if (Number(r.payload?.session?.patient_id) === Number(patientId)) return true;
      return false;
    });
  }

  function patientStats(patientId) {
    const reports = getPatientReports(patientId);
    const sessions = Array.from(new Set(reports.map((r) => Number(r.session_id)).filter((x) => Number.isFinite(x))));
    const latest = reports[0] || null;
    const lastSession = latest?.generated_at || null;

    const scores = reports
      .map((r) => Number(r.payload?.session?.risk_score))
      .filter((x) => Number.isFinite(x));
    const lastScore = scores.length ? scores[0] : null;
    const prevScore = scores.length > 1 ? scores[1] : null;

    let trend = 'No Trend';
    if (Number.isFinite(lastScore) && Number.isFinite(prevScore)) {
      if (lastScore < prevScore - 1) trend = 'Improving';
      else if (lastScore > prevScore + 1) trend = 'Needs Review';
      else trend = 'Stable';
    }

    const status = riskBandFromScore(lastScore);
    return {
      reports,
      sessionCount: sessions.length,
      sessions,
      lastSession,
      trend,
      status,
      lastScore,
      latest,
    };
  }

  function trendClass(trend) {
    if (trend === 'Improving') return 'ca-status-ok';
    if (trend === 'Needs Review') return 'ca-status-danger';
    return 'text-on-surface-variant';
  }

  function statusClass(status) {
    if (status === 'Low') return 'ca-status-ok';
    if (status === 'Moderate') return 'ca-status-warn';
    if (status === 'High') return 'ca-status-danger';
    return 'text-on-surface-variant';
  }

  function row(patient) {
    const stats = patientStats(patient.patient_id);
    const fullName = `${patient.first_name || ''} ${patient.last_name || ''}`.trim() || patient.external_id;
    return `<tr data-patient-id="${patient.patient_id}" class="cursor-pointer hover:bg-surface-container-low/50 transition-colors">
      <td class="px-8 py-4"><div class="font-bold text-primary">${fullName}</div></td>
      <td class="px-6 py-4"><span class="font-mono text-sm text-secondary">${patient.external_id}</span></td>
      <td class="px-6 py-4 text-sm text-on-surface-variant">${fmtDate(stats.lastSession)}</td>
      <td class="px-6 py-4 text-sm">${stats.sessionCount}</td>
      <td class="px-6 py-4 text-sm font-semibold ${trendClass(stats.trend)}">${stats.trend}</td>
      <td class="px-6 py-4 text-sm font-semibold ${statusClass(stats.status)}">${stats.status}</td>
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

  function setRiskPill(status, score) {
    const el = document.getElementById('patient-risk-pill');
    if (!el) return;
    const scoreText = Number.isFinite(Number(score)) ? ` (${Number(score).toFixed(1)})` : '';
    el.textContent = `Risk: ${status}${scoreText}`;
    const klass = statusClass(status);
    el.className = `text-[11px] px-2 py-1 rounded-full bg-surface-container ${klass}`;
  }

  function wireActions(patientId) {
    const start = document.getElementById('action-start-session');
    const compare = document.getElementById('action-compare');
    const viewSessions = document.getElementById('action-view-sessions');
    const report = document.getElementById('action-generate-report');

    if (start) {
      start.onclick = function (e) {
        e.preventDefault();
        localStorage.setItem('selected_patient_id', String(patientId));
        window.location.href = '/app/sessions/live/';
      };
    }
    if (compare) compare.href = '/app/sessions/compare/';
    if (viewSessions) viewSessions.href = '/app/sessions/compare/';
    if (report) report.href = '/app/reports/';
  }

  function highlightSelectedRow() {
    document.querySelectorAll('#patients-tbody tr[data-patient-id]').forEach((tr) => {
      const active = Number(tr.dataset.patientId) === Number(selectedPatientId);
      tr.classList.toggle('bg-surface-container-low', active);
    });
  }

  async function loadPatientDetail(patientId) {
    selectedPatientId = patientId;
    highlightSelectedRow();

    const patient = patientCache.find((p) => Number(p.patient_id) === Number(patientId));
    const stats = patientStats(patientId);
    document.getElementById('patient-detail-id').textContent = patient?.external_id || `Patient #${patientId}`;
    document.getElementById('patient-summary-meta').textContent = `Last visit: ${fmtDate(stats.lastSession)} | Sessions: ${stats.sessionCount}`;
    setRiskPill(stats.status, stats.lastScore);
    wireActions(patientId);

    try {
      const annotationsRes = await window.WBSUI.api(`/api/annotations/?patient_id=${patientId}`);
      const annotations = annotationsRes.items || [];

      const timelineRows = (stats.reports || []).slice(0, 6).map((r) => {
        const startUs = r.payload?.session?.started_at_us;
        const endUs = r.payload?.session?.ended_at_us;
        const flag = riskBandFromScore(r.payload?.session?.risk_score);
        const when = r.generated_at || (usToDate(endUs)?.toISOString() || null);
        const source = r.payload?.session?.source || 'stance test';
        return `Session #${r.session_id} · ${fmtDate(when)} · ${fmtDurationSec(startUs, endUs)} · ${source} · Flag: ${flag}`;
      });
      setList('patient-session-history', timelineRows, 'No sessions linked yet');

      const reportRows = (stats.reports || []).slice(0, 6).map((r) => `${reportDisplayType(r.report_type)} · Report #${r.report_id}`);
      setList('patient-reports-history', reportRows, 'No reports');

      const annotationRows = annotations.slice(0, 6).map((a) => `${fmtDateTime(a.created_at)} · ${a.author || 'clinician'} · Session #${a.session_id || '-'} · ${a.body}`);
      setList('patient-annotation-history', annotationRows, 'No annotations');

      if (stats.sessions.length) {
        const sessionId = stats.sessions[0];
        const metricsRes = await window.WBSUI.api(`/api/sessions/${sessionId}/metrics/?metric_name=stability_score,symmetry_index,cop_x,cop_y,total_load&limit=40`);
        const metricSummary = {};
        Object.entries(metricsRes.series || {}).forEach(([name, series]) => {
          if (!series.length) return;
          const avg = series.reduce((s, row) => s + (Number(row.value) || 0), 0) / series.length;
          const label = METRIC_LABELS[name] || name;
          const unit = series[0]?.unit ? ` ${series[0].unit}` : '';
          metricSummary[label] = `${avg.toFixed(2)}${unit}`;
        });
        setMetrics(metricSummary);
        document.getElementById('patient-metrics-context').textContent = `Based on Session #${sessionId} recent metric samples.`;
      } else {
        setMetrics({});
        document.getElementById('patient-metrics-context').textContent = 'No linked sessions for metric summary yet.';
      }
    } catch (_e) {
      renderMockDetail();
    }
  }

  function renderMockDetail() {
    document.getElementById('patient-detail-id').textContent = MOCK_DETAIL.identifier;
    document.getElementById('patient-summary-meta').textContent = MOCK_DETAIL.summaryMeta;
    setRiskPill(MOCK_DETAIL.risk, 52);
    setList('patient-session-history', MOCK_DETAIL.sessions, 'No sessions');
    setList('patient-reports-history', MOCK_DETAIL.reports, 'No reports');
    setList('patient-annotation-history', MOCK_DETAIL.annotations, 'No annotations');
    setMetrics(MOCK_DETAIL.metrics);
    document.getElementById('patient-metrics-context').textContent = 'Based on latest available session metrics.';
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

  function applySearchAndSort() {
    const query = String(document.getElementById('patient-search-query')?.value || '').trim().toLowerCase();
    const dob = String(document.getElementById('patient-search-dob')?.value || '').trim();
    const sort = String(document.getElementById('patient-sort')?.value || 'recent');

    let rows = [...patientCache];
    if (query) {
      rows = rows.filter((p) => {
        const hay = `${p.external_id || ''} ${p.first_name || ''} ${p.last_name || ''}`.toLowerCase();
        return hay.includes(query);
      });
    }
    if (dob) rows = rows.filter((p) => String(p.date_of_birth || '') === dob);

    if (sort === 'sessions_desc') {
      rows.sort((a, b) => patientStats(b.patient_id).sessionCount - patientStats(a.patient_id).sessionCount);
    } else if (sort === 'name_asc') {
      rows.sort((a, b) => (`${a.first_name || ''} ${a.last_name || ''}`).localeCompare(`${b.first_name || ''} ${b.last_name || ''}`));
    } else {
      rows.sort((a, b) => {
        const ta = new Date(patientStats(a.patient_id).lastSession || 0).getTime();
        const tb = new Date(patientStats(b.patient_id).lastSession || 0).getTime();
        return tb - ta;
      });
    }

    const tbody = document.getElementById('patients-tbody');
    tbody.innerHTML = rows.length ? rows.map(row).join('') : '<tr><td colspan="6" class="px-6 py-4">No matching patients</td></tr>';
    bindRowClicks();
    highlightSelectedRow();

    const meta = document.getElementById('patient-search-meta');
    if (meta) meta.textContent = `${rows.length} result${rows.length === 1 ? '' : 's'}`;

    if (rows.length && !selectedPatientId) {
      loadPatientDetail(rows[0].patient_id);
    }
  }

  async function loadData() {
    if (loaded) return;
    const tbody = document.getElementById('patients-tbody');
    tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-4">Loading...</td></tr>';
    try {
      const [patientsRes, reportsRes] = await Promise.all([
        window.WBSUI.api('/api/patients/'),
        window.WBSUI.api('/api/reports/'),
      ]);
      patientCache = patientsRes.items || [];
      reportCache = reportsRes.items || [];
      loaded = true;

      if (!patientCache.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-4">No patients yet</td></tr>';
        renderMockDetail();
        const meta = document.getElementById('patient-search-meta');
        if (meta) meta.textContent = '0 results';
        return;
      }

      applySearchAndSort();
      await loadPatientDetail(patientCache[0].patient_id);
    } catch (e) {
      if (e.status === 401) return;
      tbody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-error">${e.message}</td></tr>`;
      renderMockDetail();
      const meta = document.getElementById('patient-search-meta');
      if (meta) meta.textContent = '0 results';
    }
  }

  async function onCreate(e) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const payload = Object.fromEntries(fd.entries());
    if (!payload.date_of_birth) delete payload.date_of_birth;
    const msg = document.getElementById('patient-msg');

    const duplicate = patientCache.find((p) => String(p.external_id || '').toLowerCase() === String(payload.external_id || '').toLowerCase());
    if (duplicate) {
      msg.textContent = 'Duplicate warning: this Clinical ID already exists.';
      msg.className = 'text-xs mt-2 ca-status-warn';
      return;
    }

    try {
      await window.WBSUI.api('/api/patients/', { method: 'POST', body: payload });
      msg.textContent = 'Patient created';
      msg.className = 'text-xs mt-2 text-secondary';
      e.currentTarget.reset();
      loaded = false;
      await loadData();
    } catch (err) {
      msg.textContent = err.message;
      msg.className = 'text-xs mt-2 text-error';
    }
  }

  function init() {
    const form = document.getElementById('patient-create-form');
    if (form) form.addEventListener('submit', onCreate);

    const searchForm = document.getElementById('patient-search-form');
    if (searchForm) {
      searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        applySearchAndSort();
      });
    }

    const searchQuery = document.getElementById('patient-search-query');
    const searchDob = document.getElementById('patient-search-dob');
    const sortSel = document.getElementById('patient-sort');
    if (searchQuery) searchQuery.addEventListener('input', applySearchAndSort);
    if (searchDob) searchDob.addEventListener('input', applySearchAndSort);
    if (sortSel) sortSel.addEventListener('change', applySearchAndSort);

    renderMockDetail();
    window.WBSUI.ready.then(loadData);
  }

  document.addEventListener('DOMContentLoaded', init);
  window.addEventListener('wbs-auth-changed', loadData);
})();
