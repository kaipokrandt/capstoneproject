(function () {
  const FALL_TRIGGER_KEY = 'F';
  const SOLES_SVG_URL = '/static/wbs/soles-feet.svg';
  const FOOT_SENSORS = [
    { x: 0.31, y: 0.15, w: 0.84 },
    { x: 0.44, y: 0.14, w: 0.92 },
    { x: 0.57, y: 0.14, w: 0.92 },
    { x: 0.70, y: 0.16, w: 0.84 },
    { x: 0.30, y: 0.30, w: 0.86 },
    { x: 0.43, y: 0.29, w: 0.92 },
    { x: 0.56, y: 0.29, w: 0.92 },
    { x: 0.69, y: 0.30, w: 0.86 },
    { x: 0.30, y: 0.47, w: 0.82 },
    { x: 0.43, y: 0.47, w: 0.88 },
    { x: 0.56, y: 0.47, w: 0.88 },
    { x: 0.69, y: 0.48, w: 0.82 },
    { x: 0.33, y: 0.67, w: 0.86 },
    { x: 0.45, y: 0.73, w: 0.94 },
    { x: 0.57, y: 0.73, w: 0.94 },
    { x: 0.69, y: 0.67, w: 0.86 },
  ];

  const state = {
    sessionId: null,
    running: false,
    streamTimer: null,
    staleTimer: null,
    timerTick: null,
    lastSync: null,
    startedAtMs: null,
    targetSec: 30,
    selectedPatientId: null,
    selectedDeviceId: null,
    selectedDeviceLabel: null,
    copChart: null,
    stabilityChart: null,
    lastFrame: null,
    lastRssi: null,
    fallAlertActive: false,
    fallTriggeredAt: null,
    fallTriggerSource: null,
    fallStopInFlight: false,
    liveKeyHandler: null,
    solesSvg: null,
    solesReady: false,
    solesBounds: null,
  };

  function writeMsg(text, err) {
    const el = document.getElementById('live-msg');
    if (!el) return;
    el.textContent = text;
    el.className = err ? 'text-xs mt-2 text-error' : 'text-xs mt-2 text-secondary';
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setClass(id, cls) {
    const el = document.getElementById(id);
    if (el) el.className = cls;
  }

  function setHidden(id, hidden) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('hidden', hidden);
  }

  function safePatientLabel() {
    const text = document.getElementById('live-patient')?.textContent || '';
    return text.trim() || (state.selectedPatientId ? `Patient #${state.selectedPatientId}` : 'Patient not selected');
  }

  function setAssessmentToggleDisabled(disabled) {
    const toggle = document.getElementById('btn-assessment-toggle');
    if (!toggle) return;
    toggle.disabled = !!disabled;
    toggle.classList.toggle('opacity-60', !!disabled);
    toggle.classList.toggle('cursor-not-allowed', !!disabled);
  }

  function resetFallAlertUi() {
    state.fallAlertActive = false;
    state.fallTriggeredAt = null;
    state.fallTriggerSource = null;
    setHidden('fall-alert-banner', true);
    const modal = document.getElementById('fall-alert-modal');
    if (modal) {
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
    }
    document.body.style.overflow = '';
    setAssessmentToggleDisabled(false);
  }

  function openFallAlertUi() {
    const ts = state.fallTriggeredAt || new Date();
    setHidden('fall-alert-banner', false);
    const modal = document.getElementById('fall-alert-modal');
    if (modal) {
      modal.classList.remove('hidden');
      modal.setAttribute('aria-hidden', 'false');
    }
    document.body.style.overflow = 'hidden';
    setText('fall-alert-context', `${safePatientLabel()} · Session #${state.sessionId || '-'} · Auto emergency stop executed.`);
    setText('fall-alert-time', `Triggered at: ${ts.toLocaleString()} · Source: ${state.fallTriggerSource || 'simulation'}`);
    setAssessmentToggleDisabled(true);
    document.getElementById('fall-alert-ack')?.focus();
  }

  function closeFallModalKeepBanner() {
    const modal = document.getElementById('fall-alert-modal');
    if (modal) {
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
    }
    document.body.style.overflow = '';
  }

  function acknowledgeFallAlert() {
    closeFallModalKeepBanner();
    resetFallAlertUi();
    updateQualityAndSafety();
  }

  function viewFallSummary() {
    closeFallModalKeepBanner();
    const summary = document.getElementById('measure-status');
    if (summary && typeof summary.scrollIntoView === 'function') {
      summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  function buildFrame(tsUs) {
    const vals = [200, 220, 240, 260].map((v) => v + Math.floor(Math.random() * 40));
    const b = [];
    vals.forEach((v) => {
      b.push(v & 255);
      b.push((v >> 8) & 255);
    });
    return {
      ts_us: tsUs,
      gw: 2,
      gh: 2,
      battery_pct: 88 + Math.floor(Math.random() * 10),
      flags: 0,
      total_load: vals.reduce((a, n) => a + n, 0),
      adc_base64: btoa(String.fromCharCode(...b)),
    };
  }

  function mapFootX(x, _isRight) {
    return x;
  }

  function detectSolesBounds(img) {
    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    if (!w || !h) return null;

    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(img, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h).data;
    const size = w * h;
    const mask = new Uint8Array(size);
    const visited = new Uint8Array(size);
    for (let i = 0; i < size; i++) {
      mask[i] = data[i * 4 + 3] >= 16 ? 1 : 0;
    }

    const components = [];
    const stack = [];
    const pushIf = (x, y) => {
      if (x < 0 || y < 0 || x >= w || y >= h) return;
      const idx = y * w + x;
      if (!mask[idx] || visited[idx]) return;
      visited[idx] = 1;
      stack.push(idx);
    };

    for (let idx = 0; idx < size; idx++) {
      if (!mask[idx] || visited[idx]) continue;
      visited[idx] = 1;
      stack.push(idx);
      let minX = w; let minY = h; let maxX = 0; let maxY = 0; let count = 0; let sumX = 0;
      while (stack.length) {
        const cur = stack.pop();
        const y = Math.floor(cur / w);
        const x = cur - (y * w);
        count += 1;
        sumX += x;
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
        pushIf(x - 1, y);
        pushIf(x + 1, y);
        pushIf(x, y - 1);
        pushIf(x, y + 1);
      }
      components.push({
        minX, minY, maxX, maxY, count,
        cx: count ? (sumX / count) : 0,
      });
    }

    if (components.length < 2) return null;
    components.sort((a, b) => b.count - a.count);
    const bodyA = components[0];
    const bodyB = components[1];
    const bodyLeft = bodyA.cx <= bodyB.cx ? bodyA : bodyB;
    const bodyRight = bodyA.cx <= bodyB.cx ? bodyB : bodyA;

    const left = { minX: bodyLeft.minX, minY: bodyLeft.minY, maxX: bodyLeft.maxX, maxY: bodyLeft.maxY };
    const right = { minX: bodyRight.minX, minY: bodyRight.minY, maxX: bodyRight.maxX, maxY: bodyRight.maxY };

    // Include detached toe islands by assigning each component to nearest body centroid.
    components.forEach((c) => {
      const dLeft = Math.abs(c.cx - bodyLeft.cx);
      const dRight = Math.abs(c.cx - bodyRight.cx);
      const t = dLeft <= dRight ? left : right;
      if (c.minX < t.minX) t.minX = c.minX;
      if (c.minY < t.minY) t.minY = c.minY;
      if (c.maxX > t.maxX) t.maxX = c.maxX;
      if (c.maxY > t.maxY) t.maxY = c.maxY;
    });

    const pad = 6;
    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    return {
      left: {
        sx: clamp(left.minX - pad, 0, w - 1),
        sy: clamp(left.minY - pad, 0, h - 1),
        sw: clamp((left.maxX - left.minX) + pad * 2, 1, w),
        sh: clamp((left.maxY - left.minY) + pad * 2, 1, h),
      },
      right: {
        sx: clamp(right.minX - pad, 0, w - 1),
        sy: clamp(right.minY - pad, 0, h - 1),
        sw: clamp((right.maxX - right.minX) + pad * 2, 1, w),
        sh: clamp((right.maxY - right.minY) + pad * 2, 1, h),
      },
    };
  }

  function ensureSolesSvgLoaded() {
    if (state.solesReady && state.solesSvg) return;
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => {
      state.solesSvg = img;
      state.solesReady = true;
      state.solesBounds = detectSolesBounds(img);
    };
    img.src = SOLES_SVG_URL;
  }

  function drawSoleOverlay(ctx, canvasWidth, canvasHeight, isRight) {
    if (!state.solesReady || !state.solesSvg || !state.solesBounds) return null;
    const img = state.solesSvg;
    const b = isRight ? state.solesBounds.right : state.solesBounds.left;
    const padX = canvasWidth * 0.06;
    const padY = canvasHeight * 0.04;
    const fitW = canvasWidth - padX * 2;
    const fitH = canvasHeight - padY * 2;
    const scale = Math.min(fitW / b.sw, fitH / b.sh);
    const dw = b.sw * scale;
    const dh = b.sh * scale;
    const dx = (canvasWidth - dw) / 2;
    const dy = (canvasHeight - dh) / 2;

    ctx.save();
    ctx.globalAlpha = 0.58;
    ctx.drawImage(img, b.sx, b.sy, b.sw, b.sh, dx, dy, dw, dh);
    ctx.restore();
    return { dx, dy, dw, dh };
  }

  function sensorColor(ratio) {
    if (ratio > 0.72) return [220, 38, 38];
    if (ratio > 0.46) return [245, 158, 11];
    return [59, 130, 246];
  }

  function drawHeatmap(canvasId, values, isRight) {
    const c = document.getElementById(canvasId);
    if (!c || typeof c.getContext !== 'function') return;
    const ctx = c.getContext('2d');
    const w = c.width;
    const h = c.height;
    ctx.clearRect(0, 0, c.width, c.height);

    // Render the exact sole silhouette provided by user.
    const layout = drawSoleOverlay(ctx, w, h, isRight);
    if (!layout) return;

    const safeValues = Array.isArray(values) ? values : [];
    const maxVal = Math.max(1, ...safeValues.map((v) => Number(v) || 0));
    FOOT_SENSORS.forEach((sensor, idx) => {
      const raw = Number(safeValues[idx] || 0);
      const ratio = Math.max(0.14, Math.min(1, raw / maxVal));
      const [r, g, b] = sensorColor(ratio);
      const sx = layout.dx + (mapFootX(sensor.x, isRight) * layout.dw);
      const sy = layout.dy + (sensor.y * layout.dh);
      const radius = Math.max(8, (w * 0.032) + (sensor.w * w * 0.024));
      const grad = ctx.createRadialGradient(sx, sy, 1, sx, sy, radius);
      grad.addColorStop(0, `rgba(${r},${g},${b},${0.72 * ratio + 0.2})`);
      grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(sx, sy, radius, 0, Math.PI * 2);
      ctx.fill();
    });

    // Sensor center markers
    ctx.fillStyle = 'rgba(71,85,105,0.52)';
    FOOT_SENSORS.forEach((sensor) => {
      ctx.beginPath();
      ctx.arc(layout.dx + (mapFootX(sensor.x, isRight) * layout.dw), layout.dy + (sensor.y * layout.dh), 1.1, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function symmetryBandText(symmetry) {
    if (!Number.isFinite(symmetry)) return { text: 'No interpretation yet.', cls: 'text-xs text-on-surface-variant mt-2' };
    if (symmetry >= 90) return { text: 'Within normal range', cls: 'text-xs ca-status-ok mt-2' };
    if (symmetry >= 80) return { text: 'Borderline symmetry range', cls: 'text-xs ca-status-warn mt-2' };
    return { text: 'Concerning asymmetry detected', cls: 'text-xs ca-status-danger mt-2' };
  }

  function updateSymmetry(values) {
    const left = (values[0] || 0) + (values[2] || 0);
    const right = (values[1] || 0) + (values[3] || 0);
    const total = left + right || 1;
    const leftPct = Math.round((left / total) * 100);
    const symmetry = 100 - Math.abs(50 - leftPct) * 2;
    const stability = Math.max(0, 100 - Math.abs(left - right) / 8);

    const fill = document.getElementById('symmetry-fill');
    if (fill) fill.style.width = `${leftPct}%`;
    setText('symmetry-pct', `${symmetry}%`);
    setText('stability-score', `Stability score: ${Math.round(stability)}`);

    const band = symmetryBandText(symmetry);
    setText('symmetry-band', band.text);
    setClass('symmetry-band', band.cls);

    return { symmetry, stability };
  }

  function updateDeviceVitals(frame) {
    const rssi = -42 - Math.floor(Math.random() * 26);
    state.lastRssi = rssi;
    setText('live-battery', `Battery: ${frame.battery_pct}%`);
    setText('live-rssi', `Signal: ${rssi} dBm`);
  }

  function setOverlayVisible(visible) {
    const ov = document.getElementById('stale-overlay');
    if (!ov) return;
    ov.classList.toggle('hidden', !visible);
  }

  function setOverlayState(mode) {
    const ov = document.getElementById('stale-overlay');
    if (!ov) return;

    if (mode === 'fall') {
      ov.textContent = 'Critical safety event detected. Session interrupted. Stabilize patient and reassess.';
      ov.className = 'absolute inset-0 bg-background/85 backdrop-blur-[1px] rounded-lg p-4 text-sm text-error font-semibold flex items-center justify-center text-center z-10';
      return;
    }

    if (mode === 'idle') {
      ov.textContent = 'Start assessment to view live pressure and CoP trace.';
      ov.className = 'absolute inset-0 bg-background/70 backdrop-blur-[1px] rounded-lg p-4 text-sm text-on-surface-variant font-semibold flex items-center justify-center text-center z-10';
      return;
    }

    if (mode === 'collecting') {
      ov.textContent = 'Collecting live signal...';
      ov.className = 'absolute inset-0 bg-background/60 backdrop-blur-[1px] rounded-lg p-4 text-sm text-on-surface-variant font-semibold flex items-center justify-center text-center z-10';
      return;
    }

    if (mode === 'warning') {
      ov.textContent = 'Signal unstable. Ensure patient safety and verify device contact.';
      ov.className = 'absolute inset-0 bg-background/80 backdrop-blur-[1px] rounded-lg p-4 text-sm text-error font-semibold flex items-center justify-center text-center z-10';
      return;
    }

    setOverlayVisible(false);
  }

  function updateProgressUI() {
    if (!state.startedAtMs) {
      setText('live-timer', '00:00');
      setText('completion-status', 'Not started');
      setText('measure-status', 'Waiting to start assessment.');
      const bar = document.getElementById('assessment-progress');
      if (bar) bar.style.width = '0%';
      return;
    }

    const sec = Math.max(0, Math.floor((Date.now() - state.startedAtMs) / 1000));
    const mm = String(Math.floor(sec / 60)).padStart(2, '0');
    const ss = String(sec % 60).padStart(2, '0');
    setText('live-timer', `${mm}:${ss}`);

    const pct = Math.min(100, Math.round((sec / state.targetSec) * 100));
    const bar = document.getElementById('assessment-progress');
    if (bar) bar.style.width = `${pct}%`;

    if (!state.running) {
      setText('completion-status', state.fallAlertActive ? 'Interrupted for safety' : 'Assessment ended');
      return;
    }

    if (sec < state.targetSec * 0.5) {
      setText('completion-status', `${state.targetSec - sec}s remaining`);
      setText('measure-status', 'Collecting baseline data...');
    } else if (sec < state.targetSec) {
      setText('completion-status', `${state.targetSec - sec}s remaining`);
      setText('measure-status', 'Stable measurement in progress.');
    } else {
      setText('completion-status', 'Sufficient data collected');
      setText('measure-status', 'Assessment complete. You may end session.');
    }
  }

  function updateQualityAndSafety() {
    if (state.fallAlertActive) {
      setText('quality-status', 'Critical event');
      setClass('quality-status', 'text-sm font-semibold ca-status-danger');
      setText('safety-status', 'Emergency interruption');
      setClass('safety-status', 'text-sm font-semibold ca-status-danger');
      setText('live-sync', 'Last synced: interrupted by safety event');
      setClass('live-sync', 'text-xs ca-status-danger');
      setOverlayState('fall');
      return;
    }

    if (!state.running) {
      setText('quality-status', 'Ready');
      setClass('quality-status', 'text-sm font-semibold text-on-surface');
      setText('safety-status', 'Ready to start');
      setClass('safety-status', 'text-sm font-semibold text-on-surface-variant');
      setText('live-sync', 'Last synced: n/a');
      setClass('live-sync', 'text-xs text-on-surface-variant');
      setOverlayState('idle');
      return;
    }

    const syncAge = state.lastSync ? Math.floor((Date.now() - state.lastSync) / 1000) : 999;
    const batt = Number(String(document.getElementById('live-battery')?.textContent || '').replace(/[^0-9]/g, ''));
    const rssi = Number(state.lastRssi);

    let quality = 'High';
    let qualityCls = 'text-sm font-semibold ca-status-ok';

    if (syncAge > 3 || (Number.isFinite(batt) && batt < 25) || (Number.isFinite(rssi) && rssi < -65)) {
      quality = 'Low';
      qualityCls = 'text-sm font-semibold ca-status-danger';
    } else if (syncAge > 1 || (Number.isFinite(rssi) && rssi < -55)) {
      quality = 'Moderate';
      qualityCls = 'text-sm font-semibold ca-status-warn';
    }

    setText('quality-status', quality);
    setClass('quality-status', qualityCls);

    if (quality === 'Low') {
      setText('safety-status', 'Verify stance and contact');
      setClass('safety-status', 'text-sm font-semibold ca-status-danger');
    } else {
      setText('safety-status', 'Monitoring');
      setClass('safety-status', 'text-sm font-semibold ca-status-ok');
    }

    const syncEl = document.getElementById('live-sync');
    if (syncEl) {
      syncEl.textContent = state.lastSync ? `Last synced: ${syncAge}s ago` : 'Last synced: n/a';
      syncEl.className = syncAge > 3 ? 'text-xs ca-status-danger' : 'text-xs text-on-surface-variant';
    }

    if (!state.lastSync) {
      setOverlayState('collecting');
    } else if (syncAge > 3) {
      setOverlayState('warning');
    } else {
      setOverlayState('hidden');
    }
  }

  async function fetchMetrics() {
    if (!state.sessionId) return;
    const data = await window.WBSUI.api(`/api/sessions/${state.sessionId}/metrics/?metric_name=cop_x,cop_y,total_load&limit=80`);
    const copX = data.series.cop_x || [];
    const copY = data.series.cop_y || [];
    const total = data.series.total_load || [];

    if (!state.copChart) {
      state.copChart = new Chart(document.getElementById('cop-chart'), {
        type: 'line',
        data: {
          labels: copX.map((x) => x.ts_us),
          datasets: [
            { label: 'Medial-Lateral Sway', data: copX.map((x) => x.value), borderColor: '#1d4ed8' },
            { label: 'Anterior-Posterior Sway', data: copY.map((x) => x.value), borderColor: '#d97706' },
          ],
        },
        options: { animation: false, responsive: true },
      });
    } else {
      state.copChart.data.labels = copX.map((x) => x.ts_us);
      state.copChart.data.datasets[0].data = copX.map((x) => x.value);
      state.copChart.data.datasets[1].data = copY.map((x) => x.value);
      state.copChart.update();
    }

    if (!state.stabilityChart) {
      state.stabilityChart = new Chart(document.getElementById('stability-chart'), {
        type: 'bar',
        data: { labels: total.map((x) => x.ts_us), datasets: [{ label: 'Load Trend', data: total.map((x) => x.value), backgroundColor: '#1a365d' }] },
        options: { animation: false, responsive: true },
      });
    } else {
      state.stabilityChart.data.labels = total.map((x) => x.ts_us);
      state.stabilityChart.data.datasets[0].data = total.map((x) => x.value);
      state.stabilityChart.update();
    }
  }

  function startMonitors() {
    clearInterval(state.staleTimer);
    clearInterval(state.timerTick);

    state.timerTick = setInterval(() => {
      updateProgressUI();
      updateQualityAndSafety();
    }, 1000);

    state.staleTimer = setInterval(updateQualityAndSafety, 1000);
  }

  function stopMonitors() {
    clearInterval(state.staleTimer);
    clearInterval(state.timerTick);
  }

  async function logFallAnnotation(triggerAt, triggerSource) {
    if (!state.sessionId || !state.selectedPatientId) return;
    try {
      await window.WBSUI.api('/api/annotations/', {
        method: 'POST',
        body: {
          session_id: state.sessionId,
          patient_id: state.selectedPatientId,
          author: window.WBSUI.state?.me?.username || 'clinician',
          body: 'Simulated fall event triggered during live assessment',
          metadata: {
            source: 'live-ui-fall-sim',
            trigger: 'keyboard_shift_f',
            device_source: triggerSource,
            triggered_at: triggerAt ? triggerAt.toISOString() : new Date().toISOString(),
            auto_emergency_stop: true,
          },
        },
      });
      writeMsg('Safety event logged to annotation timeline', false);
    } catch (err) {
      writeMsg(`Session interrupted. Annotation logging failed: ${err.message}`, true);
    }
  }

  async function startAssessment() {
    const patientSelect = document.getElementById('live-patient-select');
    const deviceSelect = document.getElementById('live-device-select');
    const testType = document.getElementById('live-test-type');
    const targetSec = document.getElementById('live-target-sec');

    state.targetSec = Number(targetSec?.value || 30);
    state.selectedPatientId = Number(patientSelect?.value || 0) || null;
    state.selectedDeviceId = Number(deviceSelect?.value || 0) || null;
    const selectedPatientName = patientSelect?.selectedOptions?.[0]?.textContent || '';
    const selectedDeviceName = deviceSelect?.selectedOptions?.[0]?.textContent || '';
    const selectedTestName = testType?.selectedOptions?.[0]?.textContent || 'Double-Leg Stance';

    if (!state.selectedPatientId) {
      writeMsg('Select a patient before starting assessment.', true);
      return;
    }
    if (!state.selectedDeviceId) {
      writeMsg('Select a device before starting assessment.', true);
      return;
    }
    state.selectedDeviceLabel = selectedDeviceName || `Device #${state.selectedDeviceId}`;

    resetFallAlertUi();

    const body = { source: 'live-assessment', notes: `test_type=${String(testType?.value || 'double_leg_stance')}` };
    if (state.selectedPatientId) body.patient_id = state.selectedPatientId;
    if (state.selectedDeviceId) body.device_id = state.selectedDeviceId;

    const s = await window.WBSUI.api('/api/sessions/start/', { method: 'POST', body });
    state.sessionId = s.session_id;
    state.startedAtMs = Date.now();
    state.running = true;
    state.lastSync = null;

    setText('live-session-id', `Session: #${s.session_id}`);
    setText('live-patient', selectedPatientName || `Patient #${state.selectedPatientId}`);
    setText('live-test-context', `Test: ${selectedTestName} | Device: ${selectedDeviceName || `#${state.selectedDeviceId}`}`);
    if (state.selectedPatientId) localStorage.setItem('selected_patient_id', String(state.selectedPatientId));

    startMonitors();

    clearInterval(state.streamTimer);
    state.streamTimer = setInterval(async () => {
      try {
        const ts = Date.now() * 1000;
        const frame = buildFrame(ts);
        await window.WBSUI.api(`/api/sessions/${state.sessionId}/frames/`, { method: 'POST', body: frame });
        state.lastSync = Date.now();
        state.lastFrame = frame;

        const leftCells = FOOT_SENSORS.map((sensor, idx) => {
          const swayBias = 1 + Math.sin((Date.now() / 800) + idx) * 0.06;
          const localNoise = 0.82 + Math.random() * 0.34;
          return (frame.total_load / 18) * sensor.w * swayBias * localNoise;
        });
        const rightCells = FOOT_SENSORS.map((sensor, idx) => {
          const swayBias = 1 + Math.cos((Date.now() / 930) + idx) * 0.06;
          const localNoise = 0.82 + Math.random() * 0.34;
          return (frame.total_load / 18) * sensor.w * swayBias * localNoise;
        });
        drawHeatmap('heatmap-left', leftCells, false);
        drawHeatmap('heatmap-right', rightCells, true);
        const leftTotal = leftCells.reduce((a, b) => a + b, 0);
        const rightTotal = rightCells.reduce((a, b) => a + b, 0);
        updateSymmetry([leftTotal / 2, rightTotal / 2, leftTotal / 2, rightTotal / 2]);
        updateDeviceVitals(frame);

        await fetchMetrics();
      } catch (err) {
        writeMsg(err.message, true);
      }
    }, 1000);

    const toggle = document.getElementById('btn-assessment-toggle');
    if (toggle) toggle.textContent = 'End Assessment';
    writeMsg(`Assessment started for session ${s.session_id}`, false);
  }

  async function endAssessment(interrupted, opts) {
    if (!state.sessionId) return;
    const options = opts || {};
    clearInterval(state.streamTimer);
    stopMonitors();

    const riskLabel = interrupted ? 'interrupted' : 'completed';
    const riskScore = interrupted ? 100 : 25;
    try {
      await window.WBSUI.api(`/api/sessions/${state.sessionId}/end/`, {
        method: 'POST',
        body: { risk_label: riskLabel, risk_score: riskScore },
      });
      state.running = false;
      const toggle = document.getElementById('btn-assessment-toggle');
      if (toggle) toggle.textContent = 'Start Assessment';

      if (interrupted) {
        setText('measure-status', 'Session interrupted for patient safety. Reassess patient condition before next attempt.');
        if (!options.keepFallAlertUi) resetFallAlertUi();
        writeMsg('Emergency stop completed safely', false);
      } else {
        setText('measure-status', 'Assessment completed and saved.');
        writeMsg('Assessment completed and session saved', false);
      }

      if (interrupted && options.triggerSource === 'keyboard_shift_f') {
        await logFallAnnotation(options.triggeredAt || new Date(), options.triggerSource);
      }

      updateProgressUI();
      updateQualityAndSafety();
    } catch (err) {
      writeMsg(err.message, true);
    }
  }

  async function triggerSimulatedFall() {
    if (!state.running) return;
    if (state.fallStopInFlight || state.fallAlertActive) return;

    state.fallStopInFlight = true;
    state.fallAlertActive = true;
    state.fallTriggeredAt = new Date();
    state.fallTriggerSource = state.selectedDeviceLabel || `Device #${state.selectedDeviceId || 'unknown'}`;

    setText('safety-status', 'Critical fall event');
    setClass('safety-status', 'text-sm font-semibold ca-status-danger');
    setText('quality-status', 'Critical event');
    setClass('quality-status', 'text-sm font-semibold ca-status-danger');
    setText('measure-status', 'Critical event detected. Auto emergency stop in progress...');
    setOverlayState('fall');
    openFallAlertUi();

    try {
      await endAssessment(true, {
        triggerSource: state.fallTriggerSource,
        triggeredAt: state.fallTriggeredAt,
        keepFallAlertUi: true,
      });
      writeMsg('Simulated fall detected. Session auto-stopped and safety event logged.', true);
    } finally {
      state.fallStopInFlight = false;
    }
  }

  async function populateSelectors() {
    const patientSel = document.getElementById('live-patient-select');
    const deviceSel = document.getElementById('live-device-select');

    try {
      const [patients, devices] = await Promise.all([
        window.WBSUI.api('/api/patients/'),
        window.WBSUI.api('/api/devices/'),
      ]);

      const patientOptions = ['<option value="" selected disabled>Select patient</option>'].concat(
        (patients.items || []).map((p) => {
          const name = `${p.first_name || ''} ${p.last_name || ''}`.trim() || p.external_id;
          return `<option value="${p.patient_id}">${name} (${p.external_id})</option>`;
        }),
      );
      if (patientSel) patientSel.innerHTML = patientOptions.join('');

      const deviceOptions = ['<option value="" selected disabled>Select device</option>'].concat(
        (devices.items || []).map((d) => `<option value="${d.device_id}">${d.serial_number || `Device #${d.device_id}`}</option>`),
      );
      if (deviceSel) deviceSel.innerHTML = deviceOptions.join('');

      const savedPatientId = localStorage.getItem('selected_patient_id');
      if (savedPatientId && patientSel) {
        patientSel.value = savedPatientId;
        if (patientSel.value === savedPatientId) {
          state.selectedPatientId = Number(savedPatientId);
          setText('live-patient', `Patient #${savedPatientId}`);
        }
      }
    } catch (_e) {
      if (patientSel) patientSel.innerHTML = '<option value="" selected disabled>Select patient</option>';
      if (deviceSel) deviceSel.innerHTML = '<option value="" selected disabled>Select device</option>';
    }
  }

  function bind() {
    document.getElementById('assessment-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!state.running) {
        await startAssessment();
      } else {
        await endAssessment(false, {});
      }
    });

    document.getElementById('btn-end-emergency')?.addEventListener('click', async (e) => {
      e.preventDefault();
      await endAssessment(true, { triggerSource: 'manual_emergency', keepFallAlertUi: false });
    });

    document.getElementById('btn-add-annotation')?.addEventListener('click', async (e) => {
      e.preventDefault();
      if (!state.sessionId) {
        writeMsg('Start assessment before adding a note.', true);
        return;
      }
      const note = window.prompt('Add clinical note for this assessment:', 'Patient maintained posture.');
      if (!note) return;
      try {
        await window.WBSUI.api('/api/annotations/', {
          method: 'POST',
          body: {
            session_id: state.sessionId,
            patient_id: state.selectedPatientId,
            author: window.WBSUI.state?.me?.username || 'clinician',
            body: note,
            metadata: { source: 'live-ui' },
          },
        });
        writeMsg('Clinical note added to session', false);
      } catch (err) {
        writeMsg(err.message, true);
      }
    });

    document.getElementById('fall-alert-ack')?.addEventListener('click', (e) => {
      e.preventDefault();
      acknowledgeFallAlert();
    });

    document.getElementById('fall-alert-view-summary')?.addEventListener('click', (e) => {
      e.preventDefault();
      viewFallSummary();
    });

    state.liveKeyHandler = async (event) => {
      if (!event.shiftKey) return;
      if (String(event.key || '').toUpperCase() !== FALL_TRIGGER_KEY) return;
      if (!state.running) return;
      event.preventDefault();
      await triggerSimulatedFall();
    };
    document.addEventListener('keydown', state.liveKeyHandler);

    setText('live-patient', 'Not selected');
    setText('live-test-context', 'Test: Not selected');
    setText('live-battery', 'Battery: --%');
    setText('live-rssi', 'Signal: -- dBm');
    setText('live-session-id', 'Session: -');
    setText('quality-status', 'Unknown');
    setText('safety-status', 'Monitoring');
    setText('measure-status', 'Waiting to start assessment.');
    updateProgressUI();
    updateQualityAndSafety();
    updateSymmetry([240, 250, 230, 245]);
    resetFallAlertUi();
  }

  document.addEventListener('DOMContentLoaded', () => {
    bind();
    ensureSolesSvgLoaded();
    window.WBSUI.ready.then(populateSelectors);
  });

  window.addEventListener('beforeunload', () => {
    if (state.liveKeyHandler) document.removeEventListener('keydown', state.liveKeyHandler);
  });
})();
