(function () {
  let deltaChart = null;
  let riskChart = null;
  let copBehaviorChart = null;

  const MOCK_PAYLOAD = {
    session_ids: [1001, 1002, 1003],
    comparison: [
      {
        session_id: 1001, patient_id: 2001, device_id: 3001, raw_frame_count: 980, risk_label: 'Moderate',
        metrics: { cop_x: { avg: 0.42 }, cop_y: { avg: 0.57 }, total_load: { avg: 860 } },
      },
      {
        session_id: 1002, patient_id: 2001, device_id: 3001, raw_frame_count: 1020, risk_label: 'Low',
        metrics: { cop_x: { avg: 0.50 }, cop_y: { avg: 0.49 }, total_load: { avg: 920 } },
      },
      {
        session_id: 1003, patient_id: 2001, device_id: 3001, raw_frame_count: 995, risk_label: 'Low',
        metrics: { cop_x: { avg: 0.54 }, cop_y: { avg: 0.46 }, total_load: { avg: 940 } },
      },
    ],
    delta_from_first: {
      1002: { stability_score: { avg_delta: 0.18 }, symmetry_index: { avg_delta: 0.08 } },
      1003: { stability_score: { avg_delta: 0.22 }, symmetry_index: { avg_delta: 0.11 } },
    },
  };

  function riskScore(label) {
    const value = (label || '').toLowerCase();
    if (value === 'low') return 1;
    if (value === 'moderate') return 2;
    if (value === 'high') return 3;
    return 0;
  }

  function riskShiftText(rows) {
    if (!rows || rows.length < 2) return '-';
    const start = riskScore(rows[0].risk_label);
    const end = riskScore(rows[rows.length - 1].risk_label);
    if (!start || !end) return 'No trend';
    if (end < start) return 'Improved';
    if (end > start) return 'Worsened';
    return 'Stable';
  }

  function extractDeltaSeries(delta) {
    const labels = Object.keys(delta || {});
    const values = labels.map((sid) => {
      const metrics = Object.values(delta[sid] || {});
      if (!metrics.length) return 0;
      const avg = metrics.reduce((sum, m) => sum + (Number(m?.avg_delta) || 0), 0) / metrics.length;
      return Number(avg.toFixed(3));
    });
    return { labels, values };
  }

  function renderTable(rows) {
    const tbody = document.getElementById('compare-tbody');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="py-3">No comparison rows</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((r) => `<tr class="border-b border-outline-variant/10"><td class="py-3">${r.session_id}</td><td>${r.patient_id || '-'}</td><td>${r.device_id || '-'}</td><td>${r.raw_frame_count}</td><td>${r.risk_label || '-'}</td></tr>`).join('');
  }

  function renderDeltaChart(delta) {
    const { labels, values } = extractDeltaSeries(delta);
    const ctx = document.getElementById('delta-chart');
    if (!deltaChart) {
      deltaChart = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Average Delta', data: values, backgroundColor: '#13696a' }] },
        options: { animation: false, responsive: true },
      });
    } else {
      deltaChart.data.labels = labels;
      deltaChart.data.datasets[0].data = values;
      deltaChart.update();
    }
  }

  function renderRiskChart(rows) {
    const labels = rows.map((r) => String(r.session_id));
    const values = rows.map((r) => riskScore(r.risk_label));
    const ctx = document.getElementById('risk-chart');
    if (!riskChart) {
      riskChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Risk Index',
            data: values,
            borderColor: '#002045',
            backgroundColor: 'rgba(0, 32, 69, 0.08)',
            tension: 0.3,
            fill: true,
            pointRadius: 4,
          }],
        },
        options: {
          animation: false,
          responsive: true,
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
      riskChart.update();
    }
  }

  function renderCopBehavior(rows) {
    const labels = rows.map((r) => String(r.session_id));
    const copX = rows.map((r) => Number(r.metrics?.cop_x?.avg || 0));
    const copY = rows.map((r) => Number(r.metrics?.cop_y?.avg || 0));
    const ctx = document.getElementById('cop-behavior-chart');
    if (!copBehaviorChart) {
      copBehaviorChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [
            { label: 'CoP X (avg)', data: copX, borderColor: '#13696a', tension: 0.25 },
            { label: 'CoP Y (avg)', data: copY, borderColor: '#002045', tension: 0.25 },
          ],
        },
        options: { animation: false, responsive: true },
      });
    } else {
      copBehaviorChart.data.labels = labels;
      copBehaviorChart.data.datasets[0].data = copX;
      copBehaviorChart.data.datasets[1].data = copY;
      copBehaviorChart.update();
    }
  }

  function drawMiniHeatmap(canvasId, cells) {
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
      const alpha = Math.min(1, Math.max(0.15, v / maxV));
      ctx.fillStyle = `rgba(19,105,106,${alpha})`;
      ctx.fillRect(x * w + 3, y * h + 3, w - 6, h - 6);
    });
  }

  function renderPressureDistribution(rows) {
    const baseline = rows[0] || null;
    const followup = rows[rows.length - 1] || null;
    const baseLoad = Number(baseline?.metrics?.total_load?.avg || 800);
    const followLoad = Number(followup?.metrics?.total_load?.avg || 900);
    drawMiniHeatmap('compare-heatmap-baseline', [baseLoad * 0.28, baseLoad * 0.22, baseLoad * 0.24, baseLoad * 0.26]);
    drawMiniHeatmap('compare-heatmap-followup', [followLoad * 0.24, followLoad * 0.26, followLoad * 0.23, followLoad * 0.27]);
  }

  function renderSummary(data, sourceLabel) {
    const rows = data.comparison || [];
    const { values } = extractDeltaSeries(data.delta_from_first || {});
    const avgDelta = values.length ? (values.reduce((a, b) => a + b, 0) / values.length).toFixed(3) : '0.000';
    const syncLabel = `${sourceLabel} at ${new Date().toLocaleTimeString()}`;
    document.getElementById('compare-kpi-sessions').textContent = String(rows.length || 0);
    document.getElementById('compare-kpi-delta').textContent = avgDelta;
    document.getElementById('compare-kpi-risk').textContent = riskShiftText(rows);
    document.getElementById('compare-kpi-sync').textContent = syncLabel;
  }

  function renderAll(data, sourceLabel) {
    renderTable(data.comparison || []);
    renderDeltaChart(data.delta_from_first || {});
    renderRiskChart(data.comparison || []);
    renderCopBehavior(data.comparison || []);
    renderPressureDistribution(data.comparison || []);
    renderSummary(data, sourceLabel);
  }

  async function loadLiveComparisonIfAvailable() {
    try {
      const reports = await window.WBSUI.api('/api/reports/');
      const sessions = Array.from(
        new Set(
          (reports.items || [])
            .map((r) => r.session_id)
            .filter((s) => s !== null && s !== undefined),
        ),
      );
      if (sessions.length < 2) return false;
      const ids = encodeURIComponent(sessions.slice(0, 4).join(','));
      const data = await window.WBSUI.api(`/api/sessions/compare/?session_ids=${ids}&metric_name=total_load,cop_x,cop_y,stability_score,symmetry_index`);
      renderAll(data, 'Live data');
      document.getElementById('compare-msg').textContent = `Compared ${data.session_ids.length} sessions from live data`;
      document.getElementById('compare-msg').className = 'text-xs mt-2 text-secondary';
      return true;
    } catch (err) {
      return false;
    }
  }

  function bind() {
    renderAll(MOCK_PAYLOAD, 'Mock data');
    document.getElementById('compare-msg').textContent = 'Showing mock comparison data while loading live sessions';
    document.getElementById('compare-msg').className = 'text-xs mt-2 text-on-surface-variant';

    window.WBSUI.ready
      .then(loadLiveComparisonIfAvailable)
      .then((loaded) => {
        if (!loaded) {
          document.getElementById('compare-msg').textContent = 'Showing mock comparison data (no sufficient live sessions yet)';
          document.getElementById('compare-msg').className = 'text-xs mt-2 text-on-surface-variant';
        }
      });

    document.getElementById('compare-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const ids = encodeURIComponent(fd.get('session_ids'));
      const metrics = String(fd.get('metric_name') || '').trim();
      const msg = document.getElementById('compare-msg');
      try {
        const required = 'total_load,cop_x,cop_y,stability_score,symmetry_index';
        const metricParam = metrics ? `${metrics},${required}` : required;
        const data = await window.WBSUI.api(`/api/sessions/compare/?session_ids=${ids}&metric_name=${encodeURIComponent(metricParam)}`);
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
