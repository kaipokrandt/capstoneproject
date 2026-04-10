(function () {
  const state = {
    sessionId: null,
    streamTimer: null,
    staleTimer: null,
    timerTick: null,
    lastSync: null,
    startedAtMs: null,
    selectedPatientId: null,
    copChart: null,
    stabilityChart: null,
    lastFrame: null,
  };

  function writeMsg(text, err) {
    const el = document.getElementById('live-msg');
    el.textContent = text;
    el.className = err ? 'text-xs mt-2 text-error' : 'text-xs mt-2 text-secondary';
  }

  function buildFrame(tsUs) {
    const vals = [200, 220, 240, 260].map((v) => v + Math.floor(Math.random() * 40));
    const b = [];
    vals.forEach((v) => { b.push(v & 255); b.push((v >> 8) & 255); });
    return {
      ts_us: tsUs,
      gw: 2,
      gh: 2,
      battery_pct: 90,
      flags: 0,
      total_load: vals.reduce((a, n) => a + n, 0),
      adc_base64: btoa(String.fromCharCode(...b)),
    };
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function drawHeatmap(canvasId, values) {
    const c = document.getElementById(canvasId);
    const ctx = c.getContext('2d');
    const w = c.width / 2;
    const h = c.height / 2;
    for (let y = 0; y < 2; y++) {
      for (let x = 0; x < 2; x++) {
        const v = values[y * 2 + x];
        const alpha = Math.min(1, v / 320);
        ctx.fillStyle = `rgba(19,105,106,${alpha})`;
        ctx.fillRect(x * w + 2, y * h + 2, w - 4, h - 4);
      }
    }
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
  }

  function updateDeviceVitals(frame) {
    const rssi = -40 - Math.floor(Math.random() * 30);
    setText('live-battery', `${frame.battery_pct}%`);
    setText('live-rssi', `${rssi} dBm`);
  }

  function startTimer() {
    clearInterval(state.timerTick);
    state.timerTick = setInterval(() => {
      if (!state.startedAtMs) {
        setText('live-timer', '00:00');
        return;
      }
      const sec = Math.max(0, Math.floor((Date.now() - state.startedAtMs) / 1000));
      const mm = String(Math.floor(sec / 60)).padStart(2, '0');
      const ss = String(sec % 60).padStart(2, '0');
      setText('live-timer', `${mm}:${ss}`);
    }, 1000);
  }

  function setOverlayVisible(visible) {
    const ov = document.getElementById('stale-overlay');
    if (!ov) return;
    ov.classList.toggle('hidden', !visible);
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
        data: { labels: copX.map((x) => x.ts_us), datasets: [{ label: 'CoP X', data: copX.map((x) => x.value), borderColor: '#002045' }, { label: 'CoP Y', data: copY.map((x) => x.value), borderColor: '#13696a' }] },
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
        data: { labels: total.map((x) => x.ts_us), datasets: [{ label: 'Total Load', data: total.map((x) => x.value), backgroundColor: '#1a365d' }] },
        options: { animation: false, responsive: true },
      });
    } else {
      state.stabilityChart.data.labels = total.map((x) => x.ts_us);
      state.stabilityChart.data.datasets[0].data = total.map((x) => x.value);
      state.stabilityChart.update();
    }
  }

  function startStaleMonitor() {
    clearInterval(state.staleTimer);
    state.staleTimer = setInterval(() => {
      const el = document.getElementById('live-sync');
      if (!state.lastSync) {
        el.textContent = 'Last synced: n/a';
        setOverlayVisible(false);
        return;
      }
      const age = Math.floor((Date.now() - state.lastSync) / 1000);
      el.textContent = `Last synced: ${age}s ago`;
      el.className = age > 3 ? 'text-xs mt-3 text-error' : 'text-xs mt-3 text-secondary';
      setOverlayVisible(age > 3);
    }, 1000);
  }

  function bind() {
    document.getElementById('start-session-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const body = { source: fd.get('source') || 'ui-live' };
      if (fd.get('patient_id')) body.patient_id = Number(fd.get('patient_id'));
      if (fd.get('device_id')) body.device_id = Number(fd.get('device_id'));
      try {
        const s = await window.WBSUI.api('/api/sessions/start/', { method: 'POST', body });
        state.sessionId = s.session_id;
        state.selectedPatientId = s.patient_id || null;
        state.startedAtMs = Date.now();
        startTimer();
        setText('live-patient', s.patient_id ? `Patient #${s.patient_id}` : 'Unassigned');
        writeMsg(`Session ${s.session_id} started`);
      } catch (err) {
        writeMsg(err.message, true);
      }
    });

    document.getElementById('btn-stream-start').addEventListener('click', () => {
      if (!state.sessionId) { writeMsg('Start a session first', true); return; }
      clearInterval(state.streamTimer);
      startStaleMonitor();
      state.streamTimer = setInterval(async () => {
        try {
          const ts = Date.now() * 1000;
          const frame = buildFrame(ts);
          await window.WBSUI.api(`/api/sessions/${state.sessionId}/frames/`, { method: 'POST', body: frame });
          state.lastSync = Date.now();
          state.lastFrame = frame;
          drawHeatmap('heatmap-left', [frame.total_load / 5, frame.total_load / 6, frame.total_load / 7, frame.total_load / 8]);
          drawHeatmap('heatmap-right', [frame.total_load / 8, frame.total_load / 7, frame.total_load / 6, frame.total_load / 5]);
          updateSymmetry([frame.total_load / 5, frame.total_load / 6, frame.total_load / 7, frame.total_load / 8]);
          updateDeviceVitals(frame);
          await fetchMetrics();
        } catch (err) {
          writeMsg(err.message, true);
        }
      }, 1000);
      writeMsg('Polling stream started');
    });

    document.getElementById('btn-stream-stop').addEventListener('click', () => {
      clearInterval(state.streamTimer);
      writeMsg('Polling stream stopped');
    });

    document.getElementById('btn-end').addEventListener('click', async () => {
      if (!state.sessionId) return;
      clearInterval(state.streamTimer);
      try {
        await window.WBSUI.api(`/api/sessions/${state.sessionId}/end/`, { method: 'POST', body: { risk_label: 'interrupted', risk_score: 100 } });
        clearInterval(state.timerTick);
        writeMsg('Session interrupted safely');
      } catch (err) {
        writeMsg(err.message, true);
      }
    });

    document.getElementById('btn-add-annotation').addEventListener('click', async () => {
      if (!state.sessionId) {
        writeMsg('Start a session first', true);
        return;
      }
      try {
        await window.WBSUI.api('/api/annotations/', {
          method: 'POST',
          body: {
            session_id: state.sessionId,
            patient_id: state.selectedPatientId,
            author: window.WBSUI.state?.me?.username || 'clinician',
            body: 'Live session note (prototype): patient maintained posture.',
            metadata: { source: 'live-ui', mock_seed: true },
          },
        });
        writeMsg('Annotation attached to session');
      } catch (err) {
        writeMsg(err.message, true);
      }
    });

    setText('live-patient', 'Demo Patient');
    setText('live-battery', '92%');
    setText('live-rssi', '-52 dBm');
    setText('stability-score', 'Stability score: 87');
    setText('symmetry-pct', '94%');
    updateSymmetry([240, 250, 230, 245]);
  }

  document.addEventListener('DOMContentLoaded', bind);
})();
