(function () {
  const FALL_TRIGGER_KEY = 'F';
  const SENSOR_EDIT_KEY = 'S';
  const SENSOR_LAYOUT_STORAGE_KEY = 'wbs_sensor_layout_v1';
  const DEFAULT_SENSOR_LAYOUT = {
    left: [
      { x: 0.565234030210846, y: 0.28328029898064006, w: 0.9 },
      { x: 0.3291048740877326, y: 0.30385444660162475, w: 0.95 },
      { x: 0.5933446440350261, y: 0.42729933232753287, w: 0.9 },
      { x: 0.4387362680020352, y: 0.44787347994851756, w: 0.9 },
      { x: 0.2897500147338804, y: 0.4684476275695022, w: 0.95 },
      { x: 0.1463858842305616, y: 0.4928794278694215, w: 0.9 },
      { x: 0.4921464342679775, y: 0.5443147969218832, w: 0.88 },
      { x: 0.41343671556027306, y: 0.5558877549586871, w: 0.92 },
      { x: 0.30380532164597046, y: 0.5687465972218025, w: 0.88 },
      { x: 0.19136286634924984, y: 0.5867489763901641, w: 0.9 },
      { x: 0.7114092220965827, y: 0.9313659490416576, w: 0.96 },
      { x: 0.5708561529756819, y: 0.9390812543995268, w: 0.9 },
    ],
    right: [
      { x: 0.38707760044028616, y: 0.2386495808262632, w: 0.9 },
      { x: 0.5730544854155201, y: 0.2554064600589109, w: 0.95 },
      { x: 0.42089157952669237, y: 0.4139523174139624, w: 0.9 },
      { x: 0.5945253728095258, y: 0.4323258163392478, w: 0.9 },
      { x: 0.7377047930297224, y: 0.4580103545889714, w: 0.95 },
      { x: 0.8556172567404725, y: 0.48883180048863956, w: 0.9 },
      { x: 0.5299542617298294, y: 0.5383662692126507, w: 0.88 },
      { x: 0.6394444066040973, y: 0.5512085383375125, w: 0.92 },
      { x: 0.7405122326418832, y: 0.5679034881998327, w: 0.88 },
      { x: 0.8331577398431868, y: 0.5858826649746391, w: 0.9 },
      { x: 0.4625757110379721, y: 0.9300554775209341, w: 0.96 },
      { x: 0.31658885120561486, y: 0.928771250608448, w: 0.9 },
    ],
  };

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
    sensorEditMode: false,
    sensorLayout: JSON.parse(JSON.stringify(DEFAULT_SENSOR_LAYOUT)),
    draggingSensor: null,
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

  function sensorColor(ratio) {
    if (ratio > 0.72) return 'rgba(220, 38, 38, 0.92)';
    if (ratio > 0.46) return 'rgba(245, 158, 11, 0.92)';
    return 'rgba(96, 165, 250, 0.9)';
  }

  function cloneDefaultLayout() {
    return JSON.parse(JSON.stringify(DEFAULT_SENSOR_LAYOUT));
  }

  function sanitizedLayout(raw) {
    const fallback = cloneDefaultLayout();
    if (!raw || !Array.isArray(raw.left) || !Array.isArray(raw.right)) return fallback;
    if (raw.left.length !== fallback.left.length || raw.right.length !== fallback.right.length) return fallback;

    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    return {
      left: raw.left.map((s, i) => ({
        x: clamp(Number(s?.x ?? fallback.left[i].x), 0.05, 0.95),
        y: clamp(Number(s?.y ?? fallback.left[i].y), 0.05, 0.95),
        w: clamp(Number(s?.w ?? fallback.left[i].w), 0.6, 1.2),
      })),
      right: raw.right.map((s, i) => ({
        x: clamp(Number(s?.x ?? fallback.right[i].x), 0.05, 0.95),
        y: clamp(Number(s?.y ?? fallback.right[i].y), 0.05, 0.95),
        w: clamp(Number(s?.w ?? fallback.right[i].w), 0.6, 1.2),
      })),
    };
  }

  function loadSensorLayout() {
    try {
      const raw = localStorage.getItem(SENSOR_LAYOUT_STORAGE_KEY);
      if (!raw) return cloneDefaultLayout();
      return sanitizedLayout(JSON.parse(raw));
    } catch (_e) {
      return cloneDefaultLayout();
    }
  }

  function saveSensorLayoutLocal() {
    localStorage.setItem(SENSOR_LAYOUT_STORAGE_KEY, JSON.stringify(state.sensorLayout));
  }

  async function loadSensorLayoutServer() {
    const data = await window.WBSUI.api('/api/ui-preferences/');
    if (!data || !data.sensor_layout) return null;
    return sanitizedLayout(data.sensor_layout);
  }

  async function saveSensorLayoutServer() {
    await window.WBSUI.api('/api/ui-preferences/', {
      method: 'PATCH',
      body: { sensor_layout: state.sensorLayout },
    });
  }

  function getFootSensors(isRight) {
    return isRight ? state.sensorLayout.right : state.sensorLayout.left;
  }

  function setSensorEditMessage(text, err) {
    const el = document.getElementById('sensor-edit-msg');
    if (!el) return;
    el.textContent = text;
    el.className = err ? 'text-xs text-error mb-2' : 'text-xs text-on-surface-variant mb-2';
  }

  function applySensorEditUi() {
    const editing = state.sensorEditMode;
    const toggle = document.getElementById('sensor-edit-toggle');
    const saveBtn = document.getElementById('sensor-edit-save');
    const resetBtn = document.getElementById('sensor-edit-reset');
    if (toggle) toggle.textContent = editing ? 'Exit Edit Mode (Shift+S)' : 'Edit Sensors (Shift+S)';
    if (saveBtn) saveBtn.classList.toggle('hidden', !editing);
    if (resetBtn) resetBtn.classList.toggle('hidden', !editing);

    ['sensor-layer-left', 'sensor-layer-right'].forEach((id) => {
      const layer = document.getElementById(id);
      if (!layer) return;
      layer.classList.toggle('editing', editing);
    });

    if (editing) {
      setSensorEditMessage('Calibration mode: drag dots on each sole, then Save Layout.', false);
    } else {
      onSensorDragEnd();
      setSensorEditMessage('Sensor layout uses calibrated positions on each sole SVG.', false);
    }
  }

  function updateDraggedSensor(clientX, clientY) {
    const d = state.draggingSensor;
    if (!d) return;
    const layer = document.getElementById(d.layerId);
    if (!layer) return;
    const rect = layer.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
    const x = clamp((clientX - rect.left) / rect.width, 0.05, 0.95);
    const y = clamp((clientY - rect.top) / rect.height, 0.05, 0.95);
    const sensors = d.isRight ? state.sensorLayout.right : state.sensorLayout.left;
    if (!sensors[d.index]) return;
    sensors[d.index].x = x;
    sensors[d.index].y = y;
    drawHeatmap('heatmap-left', new Array(state.sensorLayout.left.length).fill(0), false);
    drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
  }

  function onSensorDragMove(e) {
    if (!state.draggingSensor) return;
    const point = e.touches?.[0] || e;
    if (!point) return;
    e.preventDefault();
    updateDraggedSensor(point.clientX, point.clientY);
  }

  function onSensorDragEnd() {
    if (!state.draggingSensor) return;
    const layer = document.getElementById(state.draggingSensor.layerId);
    if (layer) {
      const dot = layer.children[state.draggingSensor.index];
      if (dot) dot.classList.remove('active');
    }
    state.draggingSensor = null;
    window.removeEventListener('mousemove', onSensorDragMove);
    window.removeEventListener('mouseup', onSensorDragEnd);
    window.removeEventListener('touchmove', onSensorDragMove);
    window.removeEventListener('touchend', onSensorDragEnd);
  }

  function drawHeatmap(canvasId, values, isRight) {
    const layerId = isRight ? 'sensor-layer-right' : 'sensor-layer-left';
    const layer = document.getElementById(layerId);
    if (!layer) return;
    const footSensors = getFootSensors(isRight);

    if (layer.children.length !== footSensors.length) {
      layer.innerHTML = '';
      footSensors.forEach((_s, i) => {
        const dot = document.createElement('div');
        dot.className = 'ca-sensor-dot';
        dot.dataset.idx = String(i);
        if (state.sensorEditMode) {
          dot.classList.add('editing');
          const label = document.createElement('span');
          label.className = 'ca-sensor-dot-label';
          label.textContent = String(i + 1);
          dot.appendChild(label);
        }
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

    const safeValues = Array.isArray(values) ? values : [];
    const maxVal = Math.max(1, ...safeValues.map((v) => Number(v) || 0));
    footSensors.forEach((sensor, idx) => {
      const dot = layer.children[idx];
      if (!dot) return;
      const raw = Number(safeValues[idx] || 0);
      const ratio = Math.max(0.14, Math.min(1, raw / maxVal));
      dot.style.left = `${sensor.x * 100}%`;
      dot.style.top = `${sensor.y * 100}%`;
      dot.style.backgroundColor = sensorColor(ratio);
      dot.style.opacity = state.sensorEditMode ? '1' : `${0.58 + ratio * 0.42}`;
      dot.style.boxShadow = state.sensorEditMode
        ? '0 0 0 2px rgba(59, 130, 246, 0.45)'
        : `0 0 0 5px ${sensorColor(ratio).replace('0.92', '0.08').replace('0.9', '0.08')}`;
      dot.classList.toggle('editing', state.sensorEditMode);
      const label = dot.querySelector('.ca-sensor-dot-label');
      if (state.sensorEditMode && !label) {
        const l = document.createElement('span');
        l.className = 'ca-sensor-dot-label';
        l.textContent = String(idx + 1);
        dot.appendChild(l);
      }
      if (!state.sensorEditMode && label) label.remove();
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

    if (state.sensorEditMode && mode !== 'fall') {
      setOverlayVisible(false);
      return;
    }

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

        const leftCells = state.sensorLayout.left.map((sensor, idx) => {
          const swayBias = 1 + Math.sin((Date.now() / 800) + idx) * 0.06;
          const localNoise = 0.82 + Math.random() * 0.34;
          return (frame.total_load / 18) * sensor.w * swayBias * localNoise;
        });
        const rightCells = state.sensorLayout.right.map((sensor, idx) => {
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
    state.sensorLayout = loadSensorLayout();
    applySensorEditUi();

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

    document.getElementById('sensor-edit-toggle')?.addEventListener('click', (e) => {
      e.preventDefault();
      state.sensorEditMode = !state.sensorEditMode;
      applySensorEditUi();
      drawHeatmap('heatmap-left', new Array(state.sensorLayout.left.length).fill(0), false);
      drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
      updateQualityAndSafety();
    });

    document.getElementById('sensor-edit-save')?.addEventListener('click', (e) => {
      e.preventDefault();
      saveSensorLayoutLocal();
      saveSensorLayoutServer()
        .then(() => setSensorEditMessage('Sensor layout saved to clinician profile.', false))
        .catch((err) => setSensorEditMessage(`Saved locally. Server profile save failed: ${err?.message || 'unknown error'}.`, true));
    });

    document.getElementById('sensor-edit-reset')?.addEventListener('click', (e) => {
      e.preventDefault();
      state.sensorLayout = cloneDefaultLayout();
      drawHeatmap('heatmap-left', new Array(state.sensorLayout.left.length).fill(0), false);
      drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
      setSensorEditMessage('Layout reset to default. Click Save Layout to persist it.', false);
    });

    state.liveKeyHandler = async (event) => {
      if (!event.shiftKey) return;
      const key = String(event.key || '').toUpperCase();
      if (key === SENSOR_EDIT_KEY) {
        event.preventDefault();
        state.sensorEditMode = !state.sensorEditMode;
        applySensorEditUi();
        drawHeatmap('heatmap-left', new Array(state.sensorLayout.left.length).fill(0), false);
        drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
        updateQualityAndSafety();
        return;
      }
      if (key === FALL_TRIGGER_KEY) {
        if (!state.running) return;
        event.preventDefault();
        await triggerSimulatedFall();
      }
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
    drawHeatmap('heatmap-left', new Array(state.sensorLayout.left.length).fill(0), false);
    drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
    resetFallAlertUi();
  }

  document.addEventListener('DOMContentLoaded', () => {
    bind();
    window.WBSUI.ready.then(async () => {
      try {
        const serverLayout = await loadSensorLayoutServer();
        if (serverLayout) {
          state.sensorLayout = serverLayout;
          saveSensorLayoutLocal();
        }
      } catch (_e) {
      }
      drawHeatmap('heatmap-left', new Array(state.sensorLayout.left.length).fill(0), false);
      drawHeatmap('heatmap-right', new Array(state.sensorLayout.right.length).fill(0), true);
      populateSelectors();
    });
  });

  window.addEventListener('beforeunload', () => {
    if (state.liveKeyHandler) document.removeEventListener('keydown', state.liveKeyHandler);
  });
})();
