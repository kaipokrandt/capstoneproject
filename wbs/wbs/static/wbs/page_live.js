(function () {
  const SENSOR_EDIT_KEY = 'S';
  const SENSOR_LAYOUT_STORAGE_KEY = 'wbs_sensor_layout_v1';

  const DEFAULT_SENSOR_LAYOUT = {
    left: [
      { x: 0.565234030210846,  y: 0.71671970101936,    w: 0.9  },
      { x: 0.3291048740877326, y: 0.69614555339837525,  w: 0.95 },
      { x: 0.5933446440350261, y: 0.57270066767246713,  w: 0.9  },
      { x: 0.4387362680020352, y: 0.55212652005148244,  w: 0.9  },
      { x: 0.2897500147338804, y: 0.5315523724304978,   w: 0.95 },
      { x: 0.1463858842305616, y: 0.5071205721305785,   w: 0.9  },
      { x: 0.4921464342679775, y: 0.4556852030781168,   w: 0.88 },
      { x: 0.41343671556027306,y: 0.4441122450413129,   w: 0.92 },
      { x: 0.30380532164597046,y: 0.4312534027781975,   w: 0.88 },
      { x: 0.19136286634924984,y: 0.4132510236098359,   w: 0.9  },
      { x: 0.7114092220965827, y: 0.0686340509583424,   w: 0.96 },
      { x: 0.5708561529756819, y: 0.0609187456004732,   w: 0.9  },
    ],
    right: [
      { x: 0.38707760044028616,y: 0.7613504191737368,   w: 0.9  },
      { x: 0.5730544854155201, y: 0.7445935399410891,   w: 0.95 },
      { x: 0.42089157952669237,y: 0.5860476825860376,   w: 0.9  },
      { x: 0.5945253728095258, y: 0.5676741836607522,   w: 0.9  },
      { x: 0.7377047930297224, y: 0.5419896454110286,   w: 0.95 },
      { x: 0.8556172567404725, y: 0.5111681995113604,   w: 0.9  },
      { x: 0.5299542617298294, y: 0.4616337307873493,   w: 0.88 },
      { x: 0.6394444066040973, y: 0.4487914616624875,   w: 0.92 },
      { x: 0.7405122326418832, y: 0.4320965118001673,   w: 0.88 },
      { x: 0.8331577398431868, y: 0.4141173350253609,   w: 0.9  },
      { x: 0.4625757110379721, y: 0.0699445224790659,   w: 0.96 },
      { x: 0.31658885120561486,y: 0.071228749391552,    w: 0.9  },
    ],
  };

  const state = {
    running: false,
    sessionId: null,
    startedAtMs: null,
    targetSec: 30,
    selectedPatientId: null,
    selectedDeviceId: null,
    timerTick: null,
    frameTimer: null,
    liveKeyHandler: null,
    sensorEditMode: false,
    sensorLayout: JSON.parse(JSON.stringify(DEFAULT_SENSOR_LAYOUT)),
    draggingSensor: null,
    // metrics history
    metricsHistory: [],   // [{t, copX, copY, sway, asym}]
    charts: {},           // {cop, sway, asym}
    fallBannerTimer: null,
    lastFallTs: 0,        // ms — throttle banner re-show
    fallAlertActive: false,
    fallTriggeredAt: null,
  };

  // ── Helpers ──────────────────────────────────────────────────────────────

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function writeMsg(text, err) {
    const el = document.getElementById('live-msg');
    if (!el) return;
    el.textContent = text;
    el.className = err ? 'text-xs mt-2 text-error' : 'text-xs mt-2 text-secondary';
  }

  function setOverlayVisible(visible) {
    const ov = document.getElementById('stale-overlay');
    if (ov) ov.classList.toggle('hidden', !visible);
  }

  function showFallBanner() {
    const now = Date.now();
    if (now - state.lastFallTs < 4000) return;
    state.lastFallTs = now;
    state.fallAlertActive = true;
    state.fallTriggeredAt = new Date();

    // stop assessment
    if (state.running) {
      state.running = false;
      clearInterval(state.timerTick);
      clearInterval(state.frameTimer);
      setText('completion-status', 'Fall detected — stopped');
      setText('measure-status', 'Assessment stopped due to fall event.');
      document.getElementById('btn-assessment-toggle').textContent = 'Start Assessment';
      window.WBSUI.api(`/api/sessions/${state.sessionId}/end/`, {
        method: 'POST', body: { risk_label: 'fall_detected', risk_score: 100 },
      }).catch(() => {});
    }

    // banner
    const banner = document.getElementById('fall-alert-banner');
    if (banner) banner.classList.remove('hidden');

    // modal
    const modal = document.getElementById('fall-alert-modal');
    if (modal) { modal.classList.remove('hidden'); modal.setAttribute('aria-hidden', 'false'); }
    document.body.style.overflow = 'hidden';

    const patientEl = document.getElementById('live-patient');
    const patientLabel = patientEl?.textContent || 'Unknown patient';
    setText('fall-alert-context', `${patientLabel} · Session #${state.sessionId || '-'} · IMU jerk threshold exceeded.`);
    setText('fall-alert-time', `Triggered at: ${state.fallTriggeredAt.toLocaleString()}`);
    document.getElementById('fall-alert-ack')?.focus();
  }

  function resetFallAlertUi() {
    state.fallAlertActive = false;
    state.fallTriggeredAt = null;
    const banner = document.getElementById('fall-alert-banner');
    if (banner) banner.classList.add('hidden');
    const modal = document.getElementById('fall-alert-modal');
    if (modal) { modal.classList.add('hidden'); modal.setAttribute('aria-hidden', 'true'); }
    document.body.style.overflow = '';
  }

  // ── CoP compute ──────────────────────────────────────────────────────────

  function computeCoP(vals, sensors) {
    let wx = 0, wy = 0, total = 0;
    sensors.forEach((s, i) => {
      const v = vals[i] || 0;
      wx += s.x * v;
      wy += s.y * v;
      total += v;
    });
    if (total === 0) return { x: 0.5, y: 0.5 };
    return { x: wx / total, y: wy / total };
  }

  // ── Charts ────────────────────────────────────────────────────────────────

  function initCharts() {
    if (!window.Chart) return;
    destroyCharts();

    const gridColor  = 'rgba(255,255,255,0.15)';
    const labelColor = 'rgba(255,255,255,0.55)';
    const titleColor = 'rgba(255,255,255,0.75)';

    const axisX = (title) => ({
      title: { display: true, text: title, color: titleColor, font: { size: 11 } },
      ticks: { color: labelColor, maxTicksLimit: 6, font: { size: 10 } },
      grid:  { color: gridColor, lineWidth: 1 },
    });
    const axisY = (title) => ({
      title: { display: true, text: title, color: titleColor, font: { size: 11 } },
      ticks: { color: labelColor, font: { size: 10 } },
      grid:  { color: gridColor, lineWidth: 1 },
    });

    const commonScales = {
      x: axisX('Time (s)'),
      y: axisY('Value'),
    };

    const copCtx = document.getElementById('chart-cop')?.getContext('2d');
    if (copCtx) {
      state.charts.cop = new Chart(copCtx, {
        type: 'scatter',
        data: { datasets: [{
          label: 'CoP Trace',
          data: [],
          borderColor: 'rgba(96,165,250,0.8)',
          backgroundColor: 'rgba(96,165,250,0.15)',
          pointRadius: 3,
          showLine: true,
          tension: 0.3,
        }]},
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { min: 0, max: 1, ...axisX('Medial ← → Lateral'), border: { display: true } },
            y: { min: 0, max: 1, ...axisY('Heel → Toe'), border: { display: true } },
          },
        },
      });
    }

    const swayCtx = document.getElementById('chart-sway')?.getContext('2d');
    if (swayCtx) {
      state.charts.sway = new Chart(swayCtx, {
        type: 'line',
        data: { labels: [], datasets: [{
          label: 'Sway (CoP displacement)',
          data: [],
          borderColor: 'rgba(245,158,11,0.9)',
          backgroundColor: 'rgba(245,158,11,0.1)',
          pointRadius: 0,
          tension: 0.3,
          fill: true,
        }]},
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: axisX('Time (s)'),
            y: { min: 0, ...axisY('Displacement') },
          },
        },
      });
    }

    const asymCtx = document.getElementById('chart-asym')?.getContext('2d');
    if (asymCtx) {
      state.charts.asym = new Chart(asymCtx, {
        type: 'line',
        data: { labels: [], datasets: [{
          label: 'Asymmetry %',
          data: [],
          borderColor: 'rgba(220,38,38,0.9)',
          backgroundColor: 'rgba(220,38,38,0.1)',
          pointRadius: 0,
          tension: 0.3,
          fill: true,
        }]},
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: axisX('Time (s)'), y: { min: 0, max: 100, ...axisY('Asymmetry (%)') } },
        },
      });
    }
  }

  function destroyCharts() {
    ['cop', 'sway', 'asym'].forEach((k) => {
      if (state.charts[k]) { state.charts[k].destroy(); state.charts[k] = null; }
    });
  }

  function updateCharts(vals) {
    if (!window.Chart || !state.running) return;
    const t = ((Date.now() - state.startedAtMs) / 1000).toFixed(1);
    const allSensors = [...state.sensorLayout.left, ...state.sensorLayout.right];
    const cop = computeCoP(vals, allSensors);

    const half = Math.floor(vals.length / 2);
    const leftSum  = vals.slice(0, half).reduce((a, b) => a + b, 0);
    const rightSum = vals.slice(half).reduce((a, b) => a + b, 0);
    const total = leftSum + rightSum || 1;
    const asym = Math.round(Math.abs(leftSum - rightSum) / total * 100);

    const prev = state.metricsHistory[state.metricsHistory.length - 1];
    const sway = prev
      ? Math.sqrt(Math.pow(cop.x - prev.copX, 2) + Math.pow(cop.y - prev.copY, 2)) * 100
      : 0;

    state.metricsHistory.push({ t: +t, copX: cop.x, copY: cop.y, sway, asym });

    const MAX_POINTS = 300;
    if (state.metricsHistory.length > MAX_POINTS) state.metricsHistory.shift();

    const history = state.metricsHistory;

    if (state.charts.cop) {
      state.charts.cop.data.datasets[0].data = history.map((p) => ({ x: p.copX, y: 1 - p.copY }));
      state.charts.cop.update('none');
    }
    if (state.charts.sway) {
      state.charts.sway.data.labels = history.map((p) => p.t + 's');
      state.charts.sway.data.datasets[0].data = history.map((p) => +p.sway.toFixed(3));
      state.charts.sway.update('none');
    }
    if (state.charts.asym) {
      state.charts.asym.data.labels = history.map((p) => p.t + 's');
      state.charts.asym.data.datasets[0].data = history.map((p) => p.asym);
      state.charts.asym.update('none');
    }
  }

  // ── ADC decode ────────────────────────────────────────────────────────────

  const ADC_MAP = [0, 1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13];

  function decodeAdcValues(adc_base64, gw, gh) {
    try {
      const raw = atob(adc_base64);
      const total = gw * gh;
      const grid = [];
      for (let i = 0; i < total; i++) {
        const lo = raw.charCodeAt(i * 2);
        const hi = raw.charCodeAt(i * 2 + 1);
        let v = lo | (hi << 8);
        if (v > 32767) v -= 65536;
        grid.push(Math.max(0, v));
      }
      return ADC_MAP.map((idx) => grid[idx] ?? 0);
    } catch (_e) {
      return new Array(12).fill(0);
    }
  }

  // ── Frame polling ─────────────────────────────────────────────────────────

  async function fetchLatestFrame() {
    if (!state.running) return;
    try {
      const f = await window.WBSUI.api('/api/live-frame/');
      const vals = decodeAdcValues(f.adc_base64, f.gw, f.gh);
      drawHeatmap('heatmap-left', vals, false);
      drawHeatmap('heatmap-right', vals.map((v) => v * 0.4), true);
      updateSymmetryFromVals(vals);
      updateCharts(vals);
      setText('live-battery', `Battery: ${f.battery_pct}%`);
      if (f.flags & 1) showFallBanner();
      setOverlayVisible(false);
    } catch (_e) { /* 404 = no data, overlay stays */ }
  }

  // ── Timer & progress ──────────────────────────────────────────────────────

  function tickTimer() {
    if (!state.startedAtMs) return;
    const sec = Math.max(0, Math.floor((Date.now() - state.startedAtMs) / 1000));
    const mm = String(Math.floor(sec / 60)).padStart(2, '0');
    const ss = String(sec % 60).padStart(2, '0');
    setText('live-timer', `${mm}:${ss}`);

    const pct = Math.min(100, Math.round((sec / state.targetSec) * 100));
    const bar = document.getElementById('assessment-progress');
    if (bar) bar.style.width = `${pct}%`;

    if (state.running) {
      setText('completion-status', `${Math.max(0, state.targetSec - sec)}s remaining`);
      // Auto-end when timer expires
      if (sec >= state.targetSec) {
        endAssessment();
      }
    }
  }

  // ── Symmetry ──────────────────────────────────────────────────────────────

  function updateSymmetryFromVals(vals) {
    const half = Math.floor(vals.length / 2);
    const left  = vals.slice(0, half).reduce((a, b) => a + b, 0);
    const right = vals.slice(half).reduce((a, b) => a + b, 0);
    const total = left + right || 1;
    const leftPct  = Math.round((left / total) * 100);
    const symmetry = 100 - Math.abs(50 - leftPct) * 2;

    const fill = document.getElementById('symmetry-fill');
    if (fill) fill.style.width = `${leftPct}%`;
    setText('symmetry-pct', `${symmetry}%`);

    let band, cls;
    if (symmetry >= 90)      { band = 'Within normal range';       cls = 'text-xs ca-status-ok mt-2'; }
    else if (symmetry >= 80) { band = 'Borderline symmetry range'; cls = 'text-xs ca-status-warn mt-2'; }
    else                     { band = 'Concerning asymmetry';      cls = 'text-xs ca-status-danger mt-2'; }
    setText('symmetry-band', band);
    const el = document.getElementById('symmetry-band');
    if (el) el.className = cls;
  }

  // ── Heatmap ───────────────────────────────────────────────────────────────

  function sensorColor(ratio) {
    if (ratio > 0.72) return 'rgba(220, 38, 38, 0.92)';
    if (ratio > 0.46) return 'rgba(245, 158, 11, 0.92)';
    return 'rgba(96, 165, 250, 0.9)';
  }

  function drawHeatmap(canvasId, values, isRight) {
    const layerId = isRight ? 'sensor-layer-right' : 'sensor-layer-left';
    const layer = document.getElementById(layerId);
    if (!layer) return;
    const sensors = isRight ? state.sensorLayout.right : state.sensorLayout.left;

    if (layer.children.length !== sensors.length) {
      layer.innerHTML = '';
      sensors.forEach((_s, i) => {
        const dot = document.createElement('div');
        dot.className = 'ca-sensor-dot';
        dot.dataset.idx = String(i);
        dot.addEventListener('mousedown', (e) => {
          if (!state.sensorEditMode) return;
          e.preventDefault();
          state.draggingSensor = { layerId, index: i, isRight };
          dot.classList.add('active');
          window.addEventListener('mousemove', onSensorDragMove, { passive: false });
          window.addEventListener('mouseup', onSensorDragEnd);
        });
        dot.addEventListener('touchstart', (e) => {
          if (!state.sensorEditMode) return;
          e.preventDefault();
          state.draggingSensor = { layerId, index: i, isRight };
          dot.classList.add('active');
          window.addEventListener('touchmove', onSensorDragMove, { passive: false });
          window.addEventListener('touchend', onSensorDragEnd);
        }, { passive: false });
        layer.appendChild(dot);
      });
    }

    const safeVals = Array.isArray(values) ? values : [];
    const maxVal   = Math.max(1, ...safeVals.map((v) => Number(v) || 0));
    sensors.forEach((sensor, idx) => {
      const dot   = layer.children[idx];
      if (!dot) return;
      const raw   = Number(safeVals[idx] || 0);
      const ratio = Math.max(0.08, Math.min(1, raw / maxVal));
      const sizePx = state.sensorEditMode ? 22 : Math.round(14 + ratio * 22);
      dot.style.left            = `${sensor.x * 100}%`;
      dot.style.top             = `${sensor.y * 100}%`;
      dot.style.width           = `${sizePx}px`;
      dot.style.height          = `${sizePx}px`;
      dot.style.backgroundColor = sensorColor(ratio);
      dot.style.opacity         = state.sensorEditMode ? '1' : `${0.55 + ratio * 0.45}`;
      dot.style.boxShadow       = state.sensorEditMode
        ? '0 0 0 2px rgba(59,130,246,0.45)'
        : `0 0 0 ${Math.round(4 + ratio * 10)}px ${sensorColor(ratio).replace('0.92', '0.12').replace('0.9', '0.12')}`;
      dot.classList.toggle('editing', state.sensorEditMode);

      // edit-mode label
      let label = dot.querySelector('.ca-sensor-dot-label');
      if (state.sensorEditMode && !label) {
        label = document.createElement('span');
        label.className = 'ca-sensor-dot-label';
        label.textContent = String(idx + 1);
        dot.appendChild(label);
      }
      if (!state.sensorEditMode && label) label.remove();
    });
  }

  // ── Sensor edit drag ──────────────────────────────────────────────────────

  function onSensorDragMove(e) {
    if (!state.draggingSensor) return;
    const point = e.touches?.[0] || e;
    if (!point) return;
    e.preventDefault();
    const d     = state.draggingSensor;
    const layer = document.getElementById(d.layerId);
    if (!layer) return;
    const rect  = layer.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    const x     = clamp((point.clientX - rect.left) / rect.width,  0.05, 0.95);
    const y     = clamp((point.clientY - rect.top)  / rect.height, 0.05, 0.95);
    const sensors = d.isRight ? state.sensorLayout.right : state.sensorLayout.left;
    if (sensors[d.index]) { sensors[d.index].x = x; sensors[d.index].y = y; }
    drawHeatmap('heatmap-left',  new Array(state.sensorLayout.left.length).fill(0),  false);
    drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
  }

  function onSensorDragEnd() {
    if (!state.draggingSensor) return;
    const layer = document.getElementById(state.draggingSensor.layerId);
    if (layer) layer.children[state.draggingSensor.index]?.classList.remove('active');
    state.draggingSensor = null;
    window.removeEventListener('mousemove',  onSensorDragMove);
    window.removeEventListener('mouseup',    onSensorDragEnd);
    window.removeEventListener('touchmove',  onSensorDragMove);
    window.removeEventListener('touchend',   onSensorDragEnd);
  }

  function applySensorEditUi() {
    const editing  = state.sensorEditMode;
    const toggle   = document.getElementById('sensor-edit-toggle');
    const saveBtn  = document.getElementById('sensor-edit-save');
    const resetBtn = document.getElementById('sensor-edit-reset');
    if (toggle)   toggle.textContent = editing ? 'Exit Edit Mode (Shift+S)' : 'Edit Sensors (Shift+S)';
    if (saveBtn)  saveBtn.classList.toggle('hidden', !editing);
    if (resetBtn) resetBtn.classList.toggle('hidden', !editing);
    ['sensor-layer-left', 'sensor-layer-right'].forEach((id) => {
      document.getElementById(id)?.classList.toggle('editing', editing);
    });
    const msg = document.getElementById('sensor-edit-msg');
    if (msg) msg.textContent = editing
      ? 'Calibration mode: drag dots on each sole, then Save Layout.'
      : 'Sensor layout uses calibrated positions on each sole SVG.';
  }

  // ── Layout persistence ────────────────────────────────────────────────────

  function cloneDefaultLayout() { return JSON.parse(JSON.stringify(DEFAULT_SENSOR_LAYOUT)); }

  function sanitizedLayout(raw) {
    const fb = cloneDefaultLayout();
    if (!raw || !Array.isArray(raw.left) || !Array.isArray(raw.right)) return fb;
    if (raw.left.length !== fb.left.length || raw.right.length !== fb.right.length) return fb;
    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    return {
      left:  raw.left.map((s, i)  => ({ x: clamp(+s.x, 0.05, 0.95), y: clamp(+s.y, 0.05, 0.95), w: clamp(+s.w, 0.6, 1.2) })),
      right: raw.right.map((s, i) => ({ x: clamp(+s.x, 0.05, 0.95), y: clamp(+s.y, 0.05, 0.95), w: clamp(+s.w, 0.6, 1.2) })),
    };
  }

  function loadSensorLayout() {
    try { return sanitizedLayout(JSON.parse(localStorage.getItem(SENSOR_LAYOUT_STORAGE_KEY))); }
    catch (_e) { return cloneDefaultLayout(); }
  }

  function saveSensorLayoutLocal() {
    localStorage.setItem(SENSOR_LAYOUT_STORAGE_KEY, JSON.stringify(state.sensorLayout));
  }

  async function loadSensorLayoutServer() {
    const data = await window.WBSUI.api('/api/ui-preferences/');
    return data?.sensor_layout ? sanitizedLayout(data.sensor_layout) : null;
  }

  async function saveSensorLayoutServer() {
    await window.WBSUI.api('/api/ui-preferences/', { method: 'PATCH', body: { sensor_layout: state.sensorLayout } });
  }

  // ── Selectors ─────────────────────────────────────────────────────────────

  async function populateSelectors() {
    const patientSel = document.getElementById('live-patient-select');
    const deviceSel  = document.getElementById('live-device-select');
    try {
      const [patients, devices] = await Promise.all([
        window.WBSUI.api('/api/patients/'),
        window.WBSUI.api('/api/devices/'),
      ]);
      if (patientSel) patientSel.innerHTML =
        '<option value="" selected disabled>Select patient</option>' +
        (patients.items || []).map((p) => {
          const name = `${p.first_name || ''} ${p.last_name || ''}`.trim() || p.external_id;
          return `<option value="${p.patient_id}">${name} (${p.external_id})</option>`;
        }).join('');
      if (deviceSel) deviceSel.innerHTML =
        '<option value="" selected disabled>Select device</option>' +
        (devices.items || []).map((d) =>
          `<option value="${d.device_id}">${d.serial_number || `Device #${d.device_id}`}</option>`
        ).join('');

      const saved = localStorage.getItem('selected_patient_id');
      if (saved && patientSel) {
        patientSel.value = saved;
        if (patientSel.value === saved) {
          state.selectedPatientId = Number(saved);
          setText('live-patient', `Patient #${saved}`);
        }
      }
    } catch (_e) {}
  }

  // ── Assessment ────────────────────────────────────────────────────────────

  async function startAssessment() {
    const patientSel = document.getElementById('live-patient-select');
    const deviceSel  = document.getElementById('live-device-select');
    const testType   = document.getElementById('live-test-type');
    const targetSec  = document.getElementById('live-target-sec');

    state.selectedPatientId = Number(patientSel?.value || 0) || null;
    state.selectedDeviceId  = Number(deviceSel?.value  || 0) || null;
    state.targetSec         = Number(targetSec?.value  || 30);

    if (!state.selectedPatientId) { writeMsg('Select a patient first.', true); return; }
    if (!state.selectedDeviceId)  { writeMsg('Select a device first.',  true); return; }

    const patientName = patientSel?.selectedOptions?.[0]?.textContent || `Patient #${state.selectedPatientId}`;
    const deviceName  = deviceSel?.selectedOptions?.[0]?.textContent  || `Device #${state.selectedDeviceId}`;
    const testName    = testType?.selectedOptions?.[0]?.textContent    || 'Double-Leg Stance';

    try {
      const s = await window.WBSUI.api('/api/sessions/start/', {
        method: 'POST',
        body: {
          source:     'live-assessment',
          notes:      `test_type=${testType?.value || 'double_leg_stance'}`,
          patient_id: state.selectedPatientId,
          device_id:  state.selectedDeviceId,
        },
      });
      state.sessionId    = s.session_id;
      state.startedAtMs  = Date.now();
      state.running      = true;
      state.metricsHistory = [];
      initCharts();
      ['chart-overlay-cop', 'chart-overlay-sway', 'chart-overlay-asym'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
      });

      setText('live-session-id',  `Session: #${s.session_id}`);
      setText('live-patient',     patientName);
      setText('live-test-context',`Test: ${testName} | Device: ${deviceName}`);
      setText('completion-status', `${state.targetSec}s remaining`);
      setText('measure-status',    'Assessment running...');
      setOverlayVisible(false);

      if (state.selectedPatientId) localStorage.setItem('selected_patient_id', String(state.selectedPatientId));

      document.getElementById('btn-assessment-toggle').textContent = 'End Assessment';
      writeMsg(`Session #${s.session_id} started`, false);

      // Start timers
      clearInterval(state.timerTick);
      state.timerTick = setInterval(tickTimer, 1000);
      clearInterval(state.frameTimer);
      state.frameTimer = setInterval(fetchLatestFrame, 200);

    } catch (err) {
      writeMsg(err.message, true);
    }
  }

  async function endAssessment() {
    if (!state.running) return;
    state.running = false;

    clearInterval(state.timerTick);
    clearInterval(state.frameTimer);
    // keep charts visible with final data — don't destroy

    setText('completion-status', 'Assessment ended');
    setText('measure-status',    'Assessment complete and saved.');
    document.getElementById('btn-assessment-toggle').textContent = 'Start Assessment';

    try {
      await window.WBSUI.api(`/api/sessions/${state.sessionId}/end/`, {
        method: 'POST',
        body: { risk_label: 'completed', risk_score: 25 },
      });
      writeMsg(`Session #${state.sessionId} saved.`, false);
    } catch (err) {
      writeMsg(err.message, true);
    }
  }

  // ── Bind ──────────────────────────────────────────────────────────────────

  function bind() {
    state.sensorLayout = loadSensorLayout();
    applySensorEditUi();

    document.getElementById('assessment-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!state.running) await startAssessment();
      else await endAssessment();
    });

    document.getElementById('btn-end-emergency')?.addEventListener('click', async (e) => {
      e.preventDefault();
      if (!state.running) return;
      state.running = false;
      clearInterval(state.timerTick);
      clearInterval(state.frameTimer);
      // keep charts with final data
      setText('completion-status', 'Emergency stopped');
      setText('measure-status', 'Session interrupted.');
      document.getElementById('btn-assessment-toggle').textContent = 'Start Assessment';
      try {
        await window.WBSUI.api(`/api/sessions/${state.sessionId}/end/`, {
          method: 'POST', body: { risk_label: 'interrupted', risk_score: 100 },
        });
      } catch (_e) {}
    });

    document.getElementById('fall-alert-ack')?.addEventListener('click', () => resetFallAlertUi());

    document.getElementById('fall-alert-view-summary')?.addEventListener('click', () => {
      resetFallAlertUi();
      document.getElementById('measure-status')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    document.getElementById('sensor-edit-toggle')?.addEventListener('click', (e) => {
      e.preventDefault();
      state.sensorEditMode = !state.sensorEditMode;
      applySensorEditUi();
      drawHeatmap('heatmap-left',  new Array(state.sensorLayout.left.length).fill(0),  false);
      drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
    });

    document.getElementById('sensor-edit-save')?.addEventListener('click', (e) => {
      e.preventDefault();
      saveSensorLayoutLocal();
      saveSensorLayoutServer()
        .then(() => { const m = document.getElementById('sensor-edit-msg'); if (m) m.textContent = 'Layout saved.'; })
        .catch(() => { const m = document.getElementById('sensor-edit-msg'); if (m) m.textContent = 'Saved locally only.'; });
    });

    document.getElementById('sensor-edit-reset')?.addEventListener('click', (e) => {
      e.preventDefault();
      state.sensorLayout = cloneDefaultLayout();
      drawHeatmap('heatmap-left',  new Array(state.sensorLayout.left.length).fill(0),  false);
      drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
    });

    state.liveKeyHandler = (event) => {
      if (!event.shiftKey) return;
      if (String(event.key || '').toUpperCase() === SENSOR_EDIT_KEY) {
        event.preventDefault();
        state.sensorEditMode = !state.sensorEditMode;
        applySensorEditUi();
        drawHeatmap('heatmap-left',  new Array(state.sensorLayout.left.length).fill(0),  false);
        drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
      }
    };
    document.addEventListener('keydown', state.liveKeyHandler);

    // Initial UI state
    setText('live-patient',      'Not selected');
    setText('live-test-context', 'Test: Not selected');
    setText('live-battery',      'Battery: --%');
    setText('live-session-id',   'Session: -');
    setText('live-timer',        '00:00');
    setText('completion-status', 'Not started');
    setText('measure-status',    'Select patient and device, then press Start.');
    setOverlayVisible(true);
    drawHeatmap('heatmap-left',  new Array(state.sensorLayout.left.length).fill(0),  false);
    drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
  }

  document.addEventListener('DOMContentLoaded', () => {
    bind();
    window.WBSUI.ready.then(async () => {
      try {
        const serverLayout = await loadSensorLayoutServer();
        if (serverLayout) { state.sensorLayout = serverLayout; saveSensorLayoutLocal(); }
      } catch (_e) {}
      drawHeatmap('heatmap-left',  new Array(state.sensorLayout.left.length).fill(0),  false);
      drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
      populateSelectors();
    });
  });

  window.addEventListener('beforeunload', () => {
    if (state.liveKeyHandler) document.removeEventListener('keydown', state.liveKeyHandler);
    clearInterval(state.frameTimer);
    clearInterval(state.timerTick);
  });
})();
