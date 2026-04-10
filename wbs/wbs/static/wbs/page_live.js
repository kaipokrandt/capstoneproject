(function () {
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
    copChart: null,
    stabilityChart: null,
    lastFrame: null,
    lastRssi: null,
  };

  function writeMsg(text, err) {
    const el = document.getElementById('live-msg');
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

  function buildFrame(tsUs) {
    const vals = [200, 220, 240, 260].map((v) => v + Math.floor(Math.random() * 40));
    const b = [];
    vals.forEach((v) => { b.push(v & 255); b.push((v >> 8) & 255); });
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

  function drawHeatmap(canvasId, values) {
    const c = document.getElementById(canvasId);
    const ctx = c.getContext('2d');
    const w = c.width / 2;
    const h = c.height / 2;
    ctx.clearRect(0, 0, c.width, c.height);
    for (let y = 0; y < 2; y++) {
      for (let x = 0; x < 2; x++) {
        const v = values[y * 2 + x];
        const ratio = Math.max(0.18, Math.min(1, v / 320));
        let color = `rgba(147,197,253,${ratio})`;
        if (ratio > 0.7) color = `rgba(220,38,38,${ratio})`;
        else if (ratio > 0.45) color = `rgba(245,158,11,${ratio})`;
        ctx.fillStyle = color;
        ctx.fillRect(x * w + 2, y * h + 2, w - 4, h - 4);
      }
    }
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
      setText('completion-status', 'Assessment ended');
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

        const leftCells = [frame.total_load / 5, frame.total_load / 6, frame.total_load / 7, frame.total_load / 8];
        const rightCells = [frame.total_load / 8, frame.total_load / 7, frame.total_load / 6, frame.total_load / 5];
        drawHeatmap('heatmap-left', leftCells);
        drawHeatmap('heatmap-right', rightCells);
        updateSymmetry(leftCells);
        updateDeviceVitals(frame);

        await fetchMetrics();
      } catch (err) {
        writeMsg(err.message, true);
      }
    }, 1000);

    const toggle = document.getElementById('btn-assessment-toggle');
    if (toggle) toggle.textContent = 'End Assessment';
    writeMsg(`Assessment started for session ${s.session_id}`);
  }

  async function endAssessment(interrupted) {
    if (!state.sessionId) return;
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
        setText('measure-status', 'Session interrupted for patient safety.');
        writeMsg('Emergency stop completed safely');
      } else {
        setText('measure-status', 'Assessment completed and saved.');
        writeMsg('Assessment completed and session saved');
      }
      updateProgressUI();
      updateQualityAndSafety();
    } catch (err) {
      writeMsg(err.message, true);
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
    document.getElementById('assessment-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!state.running) {
        await startAssessment();
      } else {
        await endAssessment(false);
      }
    });

    document.getElementById('btn-end-emergency').addEventListener('click', async (e) => {
      e.preventDefault();
      await endAssessment(true);
    });

    document.getElementById('btn-add-annotation').addEventListener('click', async (e) => {
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
        writeMsg('Clinical note added to session');
      } catch (err) {
        writeMsg(err.message, true);
      }
    });

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
  }

  document.addEventListener('DOMContentLoaded', () => {
    bind();
    window.WBSUI.ready.then(populateSelectors);
  });
})();
