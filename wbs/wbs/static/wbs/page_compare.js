(function () {
  let deltaChart = null;
  let riskChart = null;
  let copBehaviorChart = null;

  const PALETTE = ['#0f766e', '#1d4ed8', '#d97706', '#9333ea', '#dc2626', '#0891b2', '#16a34a'];
  const METRIC_PRIORITY = ['stability_score', 'symmetry_index', 'total_load', 'cop_x', 'cop_y'];
  const METRIC_LABELS = {
    stability_score: 'Postural Stability Score',
    symmetry_index: 'Pressure Symmetry',
    total_load: 'Load Balance',
    cop_x: 'Medial-Lateral Stability',
    cop_y: 'Anterior-Posterior Stability',
  };
  const METRIC_DIRECTION = {
    stability_score: 'higher',
    symmetry_index: 'higher',
    total_load: 'higher',
    cop_x: 'lower',
    cop_y: 'lower',
  };

  const REQUIRED_METRICS = 'total_load,cop_x,cop_y,stability_score,symmetry_index';

  const MOCK_PAYLOAD = {
    session_ids: [1001, 1002, 1003],
    comparison: [
      {
        session_id: 1001,
        patient_id: 2001,
        device_id: 3001,
        started_at_us: 1712700000000000,
        ended_at_us: 1712700030000000,
        source: '30 sec stance',
        raw_frame_count: 980,
        risk_label: 'Moderate',
        risk_score: 58.0,
        metrics: {
          cop_x: { avg: 0.42, unit: 'grid_x' },
          cop_y: { avg: 0.57, unit: 'grid_y' },
          total_load: { avg: 860, unit: 'counts' },
          stability_score: { avg: 71.0, unit: 'score' },
          symmetry_index: { avg: 84.2, unit: '%' },
        },
      },
      {
        session_id: 1002,
        patient_id: 2001,
        device_id: 3001,
        started_at_us: 1712786400000000,
        ended_at_us: 1712786430000000,
        source: '30 sec stance',
        raw_frame_count: 1020,
        risk_label: 'Low',
        risk_score: 38.0,
        metrics: {
          cop_x: { avg: 0.50, unit: 'grid_x' },
          cop_y: { avg: 0.49, unit: 'grid_y' },
          total_load: { avg: 920, unit: 'counts' },
          stability_score: { avg: 77.4, unit: 'score' },
          symmetry_index: { avg: 89.0, unit: '%' },
        },
      },
      {
        session_id: 1003,
        patient_id: 2001,
        device_id: 3001,
        started_at_us: 1712872800000000,
        ended_at_us: 1712872830000000,
        source: '30 sec stance',
        raw_frame_count: 995,
        risk_label: 'Low',
        risk_score: 31.0,
        metrics: {
          cop_x: { avg: 0.54, unit: 'grid_x' },
          cop_y: { avg: 0.46, unit: 'grid_y' },
          total_load: { avg: 940, unit: 'counts' },
          stability_score: { avg: 80.3, unit: 'score' },
          symmetry_index: { avg: 91.1, unit: '%' },
        },
      },
    ],
    delta_from_first: {
      1002: {
        stability_score: { avg_delta: 6.4 },
        symmetry_index: { avg_delta: 4.8 },
        total_load: { avg_delta: 60.0 },
        cop_x: { avg_delta: 0.08 },
        cop_y: { avg_delta: -0.08 },
      },
      1003: {
        stability_score: { avg_delta: 9.3 },
        symmetry_index: { avg_delta: 6.9 },
        total_load: { avg_delta: 80.0 },
        cop_x: { avg_delta: 0.12 },
        cop_y: { avg_delta: -0.11 },
      },
    },
  };

  function safeNum(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function fmtPercent(value) {
    if (!Number.isFinite(value)) return '-';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(1)}%`;
  }

  function fmtDateFromUs(us) {
    const n = Number(us);
    if (!Number.isFinite(n) || n <= 0) return '-';
    const dt = new Date(Math.floor(n / 1000));
    if (Number.isNaN(dt.getTime())) return '-';
    return dt.toLocaleDateString();
  }

  function fmtDuration(startUs, endUs) {
    const s = Number(startUs);
    const e = Number(endUs);
    if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return '-';
    return `${Math.round((e - s) / 1_000_000)} sec`;
  }

  function metricDisplayName(name) {
    return METRIC_LABELS[name] || String(name || '').replaceAll('_', ' ');
  }

  function normalizeRows(data) {
    const byId = Object.fromEntries((data.comparison || []).map((r) => [String(r.session_id), r]));
    return (data.session_ids || []).map((sid) => byId[String(sid)]).filter(Boolean);
  }

  function riskScore(row) {
    const fromScore = safeNum(row?.risk_score, null);
    if (Number.isFinite(fromScore)) {
      if (fromScore >= 70) return 3;
      if (fromScore >= 40) return 2;
      return 1;
    }
    const value = String(row?.risk_label || '').toLowerCase();
    if (value === 'high') return 3;
    if (value === 'moderate') return 2;
    if (value === 'low') return 1;
    return 0;
  }

  function riskColor(value) {
    if (value === 1) return '#16a34a';
    if (value === 2) return '#d97706';
    if (value === 3) return '#dc2626';
    return '#64748b';
  }

  function riskShiftText(rows) {
    if (!rows || rows.length < 2) return 'Insufficient data';
    const start = riskScore(rows[0]);
    const end = riskScore(rows[rows.length - 1]);
    if (!start || !end) return 'Insufficient data';
    if (end < start) return 'Improved';
    if (end > start) return 'Worsened';
    return 'Stable';
  }

  function buildDeltaMatrix(data) {
    const rows = normalizeRows(data);
    const labels = rows.map((r) => String(r.session_id));
    const delta = data.delta_from_first || {};

    let metricNames = Array.from(
      new Set(
        Object.values(delta)
          .flatMap((entry) => Object.keys(entry || {})),
      ),
    );

    if (!metricNames.length && rows.length >= 2) {
      const sets = rows.map((row) => new Set(Object.keys(row.metrics || {})));
      const intersection = sets.slice(1).reduce((acc, set) => new Set(Array.from(acc).filter((k) => set.has(k))), sets[0] || new Set());
      metricNames = Array.from(intersection);
    }

    const matrix = {};
    metricNames.forEach((name) => {
      matrix[name] = labels.map(() => null);
      if (matrix[name].length) matrix[name][0] = 0;
    });

    labels.forEach((sid, i) => {
      if (i === 0) return;
      const rowDelta = delta[sid] || {};
      metricNames.forEach((name) => {
        const v = rowDelta[name]?.avg_delta;
        matrix[name][i] = Number.isFinite(Number(v)) ? Number(v) : null;
      });
    });

    if (rows.length >= 2) {
      const baseline = rows[0];
      metricNames.forEach((name) => {
        const baseAvg = safeNum(baseline.metrics?.[name]?.avg, null);
        if (!Number.isFinite(baseAvg)) return;
        rows.forEach((row, i) => {
          if (i === 0) {
            matrix[name][0] = 0;
            return;
          }
          if (Number.isFinite(matrix[name][i])) return;
          const curAvg = safeNum(row.metrics?.[name]?.avg, null);
          matrix[name][i] = Number.isFinite(curAvg) ? (curAvg - baseAvg) : null;
        });
      });
    }

    return { labels, metricNames, matrix, rows };
  }

  function choosePrimaryMetric(metricNames) {
    return METRIC_PRIORITY.find((name) => metricNames.includes(name)) || metricNames[0] || null;
  }

  function computeNormalized(primaryMetric, rows) {
    if (!primaryMetric || rows.length < 2) return null;
    const baseline = safeNum(rows[0]?.metrics?.[primaryMetric]?.avg, null);
    const latest = safeNum(rows[rows.length - 1]?.metrics?.[primaryMetric]?.avg, null);
    if (!Number.isFinite(baseline) || !Number.isFinite(latest) || baseline === 0) return null;

    const rawPct = ((latest - baseline) / Math.abs(baseline)) * 100;
    const direction = METRIC_DIRECTION[primaryMetric] || 'higher';
    return direction === 'lower' ? -rawPct : rawPct;
  }

  function overallText(normPct, riskShift) {
    if (!Number.isFinite(normPct)) {
      if (riskShift === 'Improved') return 'Improving';
      if (riskShift === 'Worsened') return 'Needs Review';
      return 'Stable';
    }
    if (normPct > 5 || riskShift === 'Improved') return 'Improving';
    if (normPct < -5 || riskShift === 'Worsened') return 'Needs Review';
    return 'Stable';
  }

  function buildSummaryBullets(primaryMetric, normPct, riskShift, rows) {
    const bullets = [];
    const metricLabel = primaryMetric ? metricDisplayName(primaryMetric) : 'Primary metric';

    if (Number.isFinite(normPct)) {
      const trendWord = normPct >= 0 ? 'improved' : 'declined';
      bullets.push(`${metricLabel} ${trendWord} by ${Math.abs(normPct).toFixed(1)}% versus baseline.`);
    } else {
      bullets.push(`${metricLabel} trend needs more complete data for normalization.`);
    }

    if (riskShift === 'Improved') bullets.push('Risk category improved compared with baseline session.');
    if (riskShift === 'Worsened') bullets.push('Risk category worsened; recommend clinical review.');
    if (riskShift === 'Stable') bullets.push('Risk category remained stable across selected sessions.');
    if (riskShift === 'Insufficient data') bullets.push('Risk trend requires more session metadata.');

    if (rows.length >= 2) {
      bullets.push(`Compared ${rows.length} sessions from ${fmtDateFromUs(rows[0].started_at_us)} to ${fmtDateFromUs(rows[rows.length - 1].started_at_us)}.`);
    }

    return bullets.slice(0, 4);
  }

  function selectedSessionIdsFromPicker() {
    return Array.from(document.querySelectorAll('.session-pick:checked')).map((el) => Number(el.value)).filter((n) => Number.isFinite(n));
  }

  function selectedPatientId() {
    const el = document.getElementById('compare-patient-select');
    if (!el) return null;
    const n = Number(el.value);
    return Number.isFinite(n) ? n : null;
  }

  async function populatePatientSelector() {
    const select = document.getElementById('compare-patient-select');
    if (!select) return;
    try {
      const patients = await window.WBSUI.api('/api/patients/');
      const options = ['<option value="">All Patients</option>'].concat(
        (patients.items || []).map((p) => {
          const name = `${p.first_name || ''} ${p.last_name || ''}`.trim() || p.external_id;
          return `<option value="${p.patient_id}">${name} (${p.external_id})</option>`;
        }),
      );
      select.innerHTML = options.join('');
    } catch (_e) {
      select.innerHTML = '<option value="">All Patients</option>';
    }
  }

  function renderPickerItems(items) {
    const wrap = document.getElementById('session-picker');
    if (!wrap) return;
    if (!items.length) {
      wrap.innerHTML = '<p class="text-sm text-on-surface-variant">No session history available for picker.</p>';
      return;
    }

    wrap.innerHTML = items.map((item, i) => `
      <label class="ca-subtle p-3 cursor-pointer flex gap-3 items-start">
        <input class="session-pick mt-0.5" type="checkbox" value="${item.session_id}" ${i < 2 ? 'checked' : ''}/>
        <div>
          <p class="text-sm font-semibold text-primary">Session #${item.session_id}</p>
          <p class="text-xs text-on-surface-variant">${item.date} · ${item.riskLabel} · ${item.assessment}</p>
        </div>
      </label>
    `).join('');

    const checks = wrap.querySelectorAll('.session-pick');
    checks.forEach((c) => c.addEventListener('change', updatePickerMeta));
    updatePickerMeta();
  }

  function updatePickerMeta() {
    const n = selectedSessionIdsFromPicker().length;
    const meta = document.getElementById('picker-meta');
    if (meta) meta.textContent = `${n} selected`;
  }

  async function populateSessionPicker(patientId) {
    try {
      const path = patientId ? `/api/sessions/?patient_id=${patientId}` : '/api/sessions/';
      const sessions = await window.WBSUI.api(path);
      const items = (sessions.items || []).map((s) => ({
        session_id: s.session_id,
        date: fmtDateFromUs(s.started_at_us),
        riskLabel: String(s.risk_label || 'Unknown').toUpperCase(),
        assessment: String(s.source || 'Assessment'),
      }));

      const seen = new Set();
      const uniq = [];
      items.forEach((it) => {
        if (seen.has(it.session_id)) return;
        seen.add(it.session_id);
        uniq.push(it);
      });

      renderPickerItems(uniq);
    } catch (_e) {
      renderPickerItems(MOCK_PAYLOAD.comparison.map((r) => ({
        session_id: r.session_id,
        date: fmtDateFromUs(r.started_at_us),
        riskLabel: String(r.risk_label || 'Unknown').toUpperCase(),
        assessment: String(r.source || 'Assessment'),
      })));
    }
  }

  function renderTable(rows) {
    const tbody = document.getElementById('compare-tbody');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="py-3">No comparison rows</td></tr>';
      return;
    }

    const baselineRisk = safeNum(rows[0]?.risk_score, null);
    tbody.innerHTML = rows.map((r, i) => {
      const rs = safeNum(r.risk_score, null);
      let improvement = i === 0 ? 'Baseline' : '-';
      if (Number.isFinite(baselineRisk) && Number.isFinite(rs)) {
        const d = baselineRisk - rs;
        if (d > 3) improvement = 'Improved';
        else if (d < -3) improvement = 'Worsened';
        else improvement = 'Stable';
      }
      return `<tr class="border-b border-outline-variant/10"><td class="py-3">${r.session_id}</td><td>${fmtDateFromUs(r.started_at_us)}</td><td>${fmtDuration(r.started_at_us, r.ended_at_us)}</td><td>${r.source || 'Assessment'}</td><td>${r.risk_label || '-'}</td><td>${improvement}</td></tr>`;
    }).join('');
  }

  function renderDeltaChart(data) {
    const { labels, metricNames, matrix } = buildDeltaMatrix(data);
    const datasets = metricNames.length
      ? metricNames.map((name, i) => ({
          label: metricDisplayName(name),
          data: matrix[name],
          borderColor: PALETTE[i % PALETTE.length],
          backgroundColor: PALETTE[i % PALETTE.length] + '33',
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          spanGaps: true,
          fill: false,
        }))
      : [{
          label: 'No shared metric deltas',
          data: labels.map(() => 0),
          borderColor: '#64748b',
          backgroundColor: '#64748b33',
          borderDash: [4, 4],
          pointRadius: 0,
        }];

    const cfg = {
      type: 'line',
      data: { labels, datasets },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: 'top' } },
        scales: {
          y: {
            ticks: { color: '#334155' },
            grid: { color: 'rgba(51,65,85,0.15)' },
          },
          x: {
            ticks: { color: '#334155' },
            grid: { color: 'rgba(51,65,85,0.08)' },
          },
        },
      },
    };

    const ctx = document.getElementById('delta-chart');
    if (!deltaChart) {
      deltaChart = new Chart(ctx, cfg);
    } else {
      deltaChart.data = cfg.data;
      deltaChart.options = cfg.options;
      deltaChart.update();
    }
  }

  function renderRiskChart(rows) {
    const labels = rows.map((r) => String(r.session_id));
    const values = rows.map((r) => riskScore(r));
    const pointColors = values.map((v) => riskColor(v));
    const ctx = document.getElementById('risk-chart');
    if (!riskChart) {
      riskChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Risk Category',
            data: values,
            borderColor: '#334155',
            backgroundColor: 'rgba(51,65,85,0.10)',
            tension: 0.25,
            fill: true,
            pointRadius: 5,
            pointBackgroundColor: pointColors,
            pointBorderColor: '#ffffff',
            pointBorderWidth: 1,
          }],
        },
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              min: 0,
              max: 3,
              ticks: {
                stepSize: 1,
                callback: function (value) {
                  if (value === 1) return 'Low';
                  if (value === 2) return 'Moderate';
                  if (value === 3) return 'High';
                  return '';
                },
              },
            },
          },
        },
      });
    } else {
      riskChart.data.labels = labels;
      riskChart.data.datasets[0].data = values;
      riskChart.data.datasets[0].pointBackgroundColor = pointColors;
      riskChart.update();
    }
  }

  function renderCopBehavior(rows) {
    const labels = rows.map((r) => String(r.session_id));
    const copX = rows.map((r) => safeNum(r.metrics?.cop_x?.avg, null));
    const copY = rows.map((r) => safeNum(r.metrics?.cop_y?.avg, null));
    const ctx = document.getElementById('cop-behavior-chart');
    if (!copBehaviorChart) {
      copBehaviorChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            { label: 'Medial-Lateral Sway', data: copX, borderColor: '#1d4ed8', backgroundColor: '#1d4ed833', tension: 0.25, spanGaps: true },
            { label: 'Anterior-Posterior Sway', data: copY, borderColor: '#d97706', backgroundColor: '#d9770633', tension: 0.25, spanGaps: true },
          ],
        },
        options: { animation: false, responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } } },
      });
    } else {
      copBehaviorChart.data.labels = labels;
      copBehaviorChart.data.datasets[0].data = copX;
      copBehaviorChart.data.datasets[1].data = copY;
      copBehaviorChart.update();
    }
  }

  function heatColor(alpha, rgb) {
    return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
  }

  function drawMiniHeatmap(canvasId, cells, rgbBase) {
    const c = document.getElementById(canvasId);
    if (!c) return;
    const ctx = c.getContext('2d');
    const w = c.width / 2;
    const h = c.height / 2;
    ctx.clearRect(0, 0, c.width, c.height);
    const maxV = Math.max(...cells, 1);
    cells.forEach((v, i) => {
      const x = i % 2;
      const y = Math.floor(i / 2);
      const ratio = Math.min(1, Math.max(0.18, v / maxV));
      ctx.fillStyle = heatColor(ratio, rgbBase);
      ctx.fillRect(x * w + 3, y * h + 3, w - 6, h - 6);
    });

    ctx.strokeStyle = 'rgba(15,23,42,0.3)';
    ctx.strokeRect(1, 1, c.width - 2, c.height - 2);
  }

  function renderPressureDistribution(rows) {
    const baseline = rows[0] || null;
    const followup = rows[rows.length - 1] || null;
    const baseLoad = safeNum(baseline?.metrics?.total_load?.avg, 800);
    const followLoad = safeNum(followup?.metrics?.total_load?.avg, 900);
    drawMiniHeatmap('compare-heatmap-baseline', [baseLoad * 0.28, baseLoad * 0.22, baseLoad * 0.24, baseLoad * 0.26], [29, 78, 216]);
    drawMiniHeatmap('compare-heatmap-followup', [followLoad * 0.24, followLoad * 0.26, followLoad * 0.23, followLoad * 0.27], [217, 119, 6]);
  }

  function renderSummary(data, sourceLabel) {
    const rows = normalizeRows(data);
    const { metricNames } = buildDeltaMatrix(data);
    const primaryMetric = choosePrimaryMetric(metricNames);
    const normPct = computeNormalized(primaryMetric, rows);
    const riskShift = riskShiftText(rows);
    const overall = overallText(normPct, riskShift);

    const syncLabel = `Last synced: ${sourceLabel} at ${new Date().toLocaleTimeString()}`;
    const syncEl = document.getElementById('compare-kpi-sync');
    if (syncEl) syncEl.textContent = syncLabel;

    document.getElementById('summary-overall').textContent = overall;
    document.getElementById('summary-risk').textContent = riskShift;
    document.getElementById('summary-normalized').textContent = Number.isFinite(normPct) && primaryMetric
      ? `${fmtPercent(normPct)} (${metricDisplayName(primaryMetric)})`
      : 'Insufficient data';

    const bullets = buildSummaryBullets(primaryMetric, normPct, riskShift, rows);
    document.getElementById('summary-bullets').innerHTML = bullets.map((b) => `<li>${b}</li>`).join('');
  }

  function renderAll(data, sourceLabel) {
    const rows = normalizeRows(data);
    renderTable(rows);
    renderDeltaChart(data);
    renderRiskChart(rows);
    renderCopBehavior(rows);
    renderPressureDistribution(rows);
    renderSummary(data, sourceLabel);
  }

  async function fetchComparison(sessionIds, metricInput) {
    const ids = encodeURIComponent(sessionIds.join(','));
    const extra = String(metricInput || '').trim();
    const metricParam = extra ? `${extra},${REQUIRED_METRICS}` : REQUIRED_METRICS;
    return window.WBSUI.api(`/api/sessions/compare/?session_ids=${ids}&metric_name=${encodeURIComponent(metricParam)}`);
  }

  async function loadLiveComparisonIfAvailable(patientId) {
    try {
      const selected = selectedSessionIdsFromPicker();
      const path = patientId ? `/api/sessions/?patient_id=${patientId}` : '/api/sessions/';
      const sessions = await window.WBSUI.api(path);
      const fallbackIds = Array.from(new Set((sessions.items || []).map((s) => Number(s.session_id)).filter((n) => Number.isFinite(n))));
      const ids = (selected.length >= 2 ? selected : fallbackIds).slice(0, 6);
      if (ids.length < 2) return false;
      const data = await fetchComparison(ids, '');
      renderAll(data, 'Live data');
      document.getElementById('compare-msg').textContent = `Compared ${data.session_ids.length} sessions from live data`;
      document.getElementById('compare-msg').className = 'text-xs mt-2 text-secondary';
      return true;
    } catch (_err) {
      return false;
    }
  }

  function bind() {
    renderAll(MOCK_PAYLOAD, 'Mock data');
    renderPickerItems(MOCK_PAYLOAD.comparison.map((r) => ({
      session_id: r.session_id,
      date: fmtDateFromUs(r.started_at_us),
      riskLabel: String(r.risk_label || 'Unknown').toUpperCase(),
      assessment: String(r.source || 'Assessment'),
    })));
    document.getElementById('compare-msg').textContent = 'Showing mock comparison data while loading live sessions';
    document.getElementById('compare-msg').className = 'text-xs mt-2 text-on-surface-variant';

    window.WBSUI.ready
      .then(populatePatientSelector)
      .then(() => populateSessionPicker(selectedPatientId()))
      .then(() => loadLiveComparisonIfAvailable(selectedPatientId()))
      .then((loaded) => {
        if (!loaded) {
          document.getElementById('compare-msg').textContent = 'Showing mock comparison data (no sufficient live sessions yet)';
          document.getElementById('compare-msg').className = 'text-xs mt-2 text-on-surface-variant';
        }
      });

    document.getElementById('compare-patient-select')?.addEventListener('change', async () => {
      const patientId = selectedPatientId();
      await populateSessionPicker(patientId);
      const loaded = await loadLiveComparisonIfAvailable(patientId);
      if (!loaded) {
        const msg = document.getElementById('compare-msg');
        msg.textContent = patientId ? 'No sufficient sessions for selected patient. Showing mock data.' : 'No sufficient sessions available. Showing mock data.';
        msg.className = 'text-xs mt-2 text-on-surface-variant';
        renderAll(MOCK_PAYLOAD, 'Mock data');
      }
    });

    document.getElementById('compare-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pickerIds = selectedSessionIdsFromPicker();
      const sessionIds = pickerIds.slice(0, 8);
      const msg = document.getElementById('compare-msg');

      if (sessionIds.length < 2) {
        msg.textContent = 'Select at least 2 sessions from the session picker.';
        msg.className = 'text-xs mt-2 text-error';
        return;
      }

      try {
        const data = await fetchComparison(sessionIds, '');
        renderAll(data, 'Live data');
        msg.textContent = `Compared ${data.session_ids.length} sessions`;
        msg.className = 'text-xs mt-2 text-secondary';
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-error';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', bind);
})();
