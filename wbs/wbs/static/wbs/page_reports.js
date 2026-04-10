(function () {
  let loaded = false;
  const MOCK_PREVIEW = {
    report_id: 999,
    session_id: 4021,
    report_type: 'clinical_summary',
    payload: {
      session: { patient_id: 17, device_id: 4, risk_label: 'low', risk_score: 21.4 },
      counts: { raw_frames: 960, computed_metrics: 3840 },
      metrics_summary: { stability_score: { avg: 86.2 }, symmetry_index: { avg: 91.7 }, cop_x: { avg: 0.53 } },
    },
    clinician_notes: 'Prototype mock preview for demo readiness.',
  };

  function setPreview(report) {
    const payload = report.payload || {};
    const session = payload.session || {};
    const counts = payload.counts || {};
    const metrics = payload.metrics_summary || {};
    const summaryRows = Object.entries(metrics).slice(0, 6).map(([name, s]) => {
      const avg = s?.avg !== undefined ? Number(s.avg).toFixed(2) : '-';
      return `<tr><td class="pr-4 py-1">${name}</td><td class="font-mono">${avg}</td></tr>`;
    }).join('');
    const el = document.getElementById('report-preview');
    el.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <div><span class="ca-title-kicker block">Report ID</span><span class="text-on-surface font-semibold">#${report.report_id}</span></div>
        <div><span class="ca-title-kicker block">Session</span><span class="text-on-surface font-semibold">#${report.session_id}</span></div>
        <div><span class="ca-title-kicker block">Type</span><span class="text-on-surface font-semibold">${report.report_type}</span></div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <div><span class="ca-title-kicker block">Patient</span><span class="text-on-surface">${session.patient_id ?? '-'}</span></div>
        <div><span class="ca-title-kicker block">Device</span><span class="text-on-surface">${session.device_id ?? '-'}</span></div>
        <div><span class="ca-title-kicker block">Risk</span><span class="text-on-surface">${session.risk_label || '-'} (${session.risk_score ?? '-'})</span></div>
      </div>
      <p class="text-xs mb-2">Frames: ${counts.raw_frames ?? '-'} | Computed Metrics: ${counts.computed_metrics ?? '-'}</p>
      <table class="text-xs mb-2">${summaryRows || '<tr><td>No metric summary</td></tr>'}</table>
      <p class="text-xs text-on-surface-variant">Notes: ${report.clinician_notes || 'None'}</p>
    `;
  }

  function bindPreviewButtons() {
    document.querySelectorAll('.report-preview-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const reportId = Number(btn.dataset.reportId);
        if (!reportId) return;
        try {
          const detail = await window.WBSUI.api(`/api/reports/${reportId}/`);
          setPreview(detail);
        } catch (_e) {
          setPreview(MOCK_PREVIEW);
        }
      });
    });
  }

  async function loadReports() {
    if (loaded) return;
    const tbody = document.getElementById('reports-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="py-3">Loading...</td></tr>';
    try {
      const data = await window.WBSUI.api('/api/reports/');
      if (!data.items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="py-3">No reports yet</td></tr>';
        setPreview(MOCK_PREVIEW);
        loaded = true;
        return;
      }
      tbody.innerHTML = data.items.map((r) => `<tr class="border-b border-outline-variant/10"><td class="py-3">${r.report_id}</td><td>${r.session_id}</td><td>${r.report_type}</td><td><a class="text-primary underline" href="/api/reports/${r.report_id}/download/" target="_blank">Download PDF</a></td><td><button class="report-preview-btn text-secondary underline" data-report-id="${r.report_id}">Preview</button></td></tr>`).join('');
      bindPreviewButtons();
      setPreview(data.items[0]);
      loaded = true;
    } catch (err) {
      if (err.status === 401) return;
      tbody.innerHTML = `<tr><td colspan="5" class="py-3 text-error">${err.message}</td></tr>`;
      setPreview(MOCK_PREVIEW);
    }
  }

  function downloadJson(filename, payload) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(href);
  }

  function bind() {
    document.getElementById('report-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const msg = document.getElementById('report-msg');
      try {
        await window.WBSUI.api('/api/reports/generate/', {
          method: 'POST',
          body: { session_id: Number(fd.get('session_id')), report_type: fd.get('report_type') || 'clinical_summary', clinician_notes: '' },
        });
        msg.textContent = 'Report generated';
        msg.className = 'text-xs mt-2 text-secondary';
        loaded = false;
        await loadReports();
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-error';
      }
    });

    document.getElementById('fhir-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const sid = Number(fd.get('session_id'));
      const msg = document.getElementById('fhir-msg');
      try {
        const out = await window.WBSUI.api(`/api/fhir/export/session/${sid}/`, { method: 'POST', body: {} });
        msg.textContent = `FHIR export generated report ${out.report_id}`;
        msg.className = 'text-xs mt-2 text-on-primary';
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-on-error';
      }
    });

    document.getElementById('json-export-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const sid = Number(fd.get('session_id'));
      const metricName = encodeURIComponent(fd.get('metric_name') || 'cop_x,cop_y,total_load');
      const msg = document.getElementById('json-msg');
      try {
        const metrics = await window.WBSUI.api(`/api/sessions/${sid}/metrics/?metric_name=${metricName}&limit=500`);
        downloadJson(`session_${sid}_metrics.json`, metrics);
        msg.textContent = `Downloaded JSON metrics for session ${sid}`;
        msg.className = 'text-xs mt-2 text-secondary';
      } catch (err) {
        const mock = {
          session_id: sid || MOCK_PREVIEW.session_id,
          count: 3,
          metric_names: ['cop_x', 'cop_y', 'stability_score'],
          series: {
            cop_x: [{ ts_us: 1, value: 0.52, unit: 'grid_x' }],
            cop_y: [{ ts_us: 1, value: 0.47, unit: 'grid_y' }],
            stability_score: [{ ts_us: 1, value: 86.2, unit: 'score' }],
          },
          mock_seed: true,
        };
        downloadJson(`session_${mock.session_id}_metrics_mock.json`, mock);
        msg.textContent = 'Live export unavailable. Downloaded mock metrics JSON instead.';
        msg.className = 'text-xs mt-2 text-on-surface-variant';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => { bind(); setPreview(MOCK_PREVIEW); window.WBSUI.ready.then(loadReports); });
  window.addEventListener('wbs-auth-changed', loadReports);
})();
