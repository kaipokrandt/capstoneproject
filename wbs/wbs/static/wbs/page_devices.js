(function () {
  let loaded = false;
  let deviceRows = [];
  let activeDeviceId = null;

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function chip(text, cls) {
    return `<span class="text-xs px-2 py-1 rounded-full bg-surface-container ${cls || 'text-on-surface-variant'}">${text}</span>`;
  }

  function fmtLastSeen(us) {
    const n = Number(us);
    if (!Number.isFinite(n) || n <= 0) return '-';
    const dt = new Date(Math.floor(n / 1000));
    if (Number.isNaN(dt.getTime())) return '-';
    return dt.toLocaleString();
  }

  function firmwareRecommended(currentVersion) {
    const cur = String(currentVersion || '').trim();
    if (!cur) return '1.0.0';
    const parts = cur.split('.').map((p) => Number(p));
    if (parts.length < 3 || parts.some((p) => !Number.isFinite(p))) return `${cur}.1`;
    return `${parts[0]}.${parts[1]}.${parts[2] + 1}`;
  }

  async function getActiveDeviceId() {
    try {
      const o = await window.WBSUI.api('/api/overview/');
      const sid = o?.latest?.session_id;
      if (!sid) return null;
      const s = await window.WBSUI.api(`/api/sessions/${sid}/`);
      return s?.device_id || null;
    } catch (_e) {
      return null;
    }
  }

  function connectionLabel(status) {
    const s = String(status?.connection?.status || '').toLowerCase();
    if (s === 'connected') return chip('Connected', 'ca-status-ok');
    if (s === 'unknown') return chip('Unknown', 'ca-status-warn');
    return chip('Disconnected', 'ca-status-danger');
  }

  function calibrationLabel(status, hasActiveCalibration) {
    const job = status?.calibration_job || {};
    if (String(job.status || '').toLowerCase() === 'in_progress') {
      return chip(`In Progress (${job.progress_pct || 0}%)`, 'ca-status-warn');
    }
    if (hasActiveCalibration || (String(job.status || '').toLowerCase() === 'completed')) {
      return chip('Valid', 'ca-status-ok');
    }
    return chip('Recommended', 'ca-status-warn');
  }

  function firmwareLabel(status, currentVersion) {
    const fw = status?.firmware_update || {};
    const st = String(fw.status || 'idle').toLowerCase();
    if (st === 'in_progress') {
      return chip(`Updating ${fw.progress_pct || 0}%`, 'ca-status-warn');
    }
    if (st === 'completed') {
      return chip(`Updated ${currentVersion || '-'}`, 'ca-status-ok');
    }
    return chip(`Current ${currentVersion || '-'}`, 'text-on-surface-variant');
  }

  function readiness(status, hasActiveCalibration) {
    const batt = Number(status?.connection?.battery_pct);
    const conn = String(status?.connection?.status || '').toLowerCase();
    const fwState = String(status?.firmware_update?.status || 'idle').toLowerCase();

    if (conn !== 'connected') return { text: 'Disconnected', cls: 'ca-status-danger' };
    if (Number.isFinite(batt) && batt < 20) return { text: 'Low Battery', cls: 'ca-status-danger' };
    if (fwState === 'in_progress') return { text: 'Updating', cls: 'ca-status-warn' };
    if (!hasActiveCalibration) return { text: 'Needs Calibration', cls: 'ca-status-warn' };
    return { text: 'Ready', cls: 'ca-status-ok' };
  }

  function buildRow(device, status, hasActiveCalibration) {
    const batt = Number(status?.connection?.battery_pct);
    const battText = Number.isFinite(batt) ? `${Math.round(batt)}%` : '-';
    const r = readiness(status, hasActiveCalibration);
    const activeChip = Number(device.device_id) === Number(activeDeviceId)
      ? chip('Active Session Device', 'ca-status-ok')
      : chip('Idle', 'text-on-surface-variant');

    return `<tr class="border-b border-outline-variant/10">
      <td class="py-3"><div class="font-semibold text-primary">${device.serial_number || `Device #${device.device_id}`}</div><div class="text-xs text-on-surface-variant">ID ${device.device_id}</div></td>
      <td>${connectionLabel(status)}</td>
      <td>${calibrationLabel(status, hasActiveCalibration)}</td>
      <td>${firmwareLabel(status, device.firmware_version)}</td>
      <td class="text-xs text-on-surface-variant">${fmtLastSeen(status?.connection?.last_seen_us)}</td>
      <td class="text-sm ${Number.isFinite(batt) && batt < 30 ? 'ca-status-danger font-semibold' : 'text-on-surface'}">${battText}</td>
      <td>${chip(r.text, r.cls)}</td>
      <td>${activeChip}</td>
    </tr>`;
  }

  function refreshSelectors() {
    const fwSel = document.getElementById('fw-device-select');
    const calSel = document.getElementById('cal-device-select');
    const options = deviceRows.map((d) => `<option value="${d.device.device_id}">${d.device.serial_number || `Device #${d.device.device_id}`}</option>`).join('');
    if (fwSel) fwSel.innerHTML = options || '<option value="">No devices</option>';
    if (calSel) calSel.innerHTML = options || '<option value="">No devices</option>';

    if (fwSel && deviceRows.length) {
      const preferred = activeDeviceId || deviceRows[0].device.device_id;
      fwSel.value = String(preferred);
      updateFirmwareContext();
    }
    if (calSel && deviceRows.length) {
      const preferred = activeDeviceId || deviceRows[0].device.device_id;
      calSel.value = String(preferred);
      updateCalibrationContext();
    }
  }

  function updateKpis() {
    const ready = deviceRows.filter((d) => readiness(d.status, d.hasActiveCalibration).text === 'Ready').length;
    const connected = deviceRows.filter((d) => String(d.status?.connection?.status || '').toLowerCase() === 'connected').length;
    const needsCal = deviceRows.filter((d) => readiness(d.status, d.hasActiveCalibration).text === 'Needs Calibration').length;
    const lowBatt = deviceRows.filter((d) => {
      const b = Number(d.status?.connection?.battery_pct);
      return Number.isFinite(b) && b < 30;
    }).length;

    setText('dev-kpi-ready', String(ready));
    setText('dev-kpi-connected', `${connected}/${deviceRows.length}`);
    setText('dev-kpi-calibration', String(needsCal));
    setText('dev-kpi-battery', String(lowBatt));
  }

  async function loadDevices() {
    if (loaded) return;
    const tbody = document.getElementById('devices-tbody');
    tbody.innerHTML = '<tr><td colspan="8" class="py-3">Loading...</td></tr>';

    try {
      const [devicesRes, activeCalibrationRes, inferredActiveDeviceId] = await Promise.all([
        window.WBSUI.api('/api/devices/'),
        window.WBSUI.api('/api/calibration-profiles/?is_active=true'),
        getActiveDeviceId(),
      ]);
      activeDeviceId = inferredActiveDeviceId;

      const devices = devicesRes.items || [];
      if (!devices.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="py-3">No devices yet</td></tr>';
        deviceRows = [];
        refreshSelectors();
        updateKpis();
        loaded = true;
        return;
      }

      const activeCalSet = new Set((activeCalibrationRes.items || []).map((c) => Number(c.device_id)));
      const statuses = await Promise.all(
        devices.map(async (d) => {
          try {
            const status = await window.WBSUI.api(`/api/devices/${d.device_id}/status/`);
            return status;
          } catch (_e) {
            return null;
          }
        }),
      );

      deviceRows = devices.map((device, i) => {
        const status = statuses[i] || { connection: { status: 'unknown', quality: 'unknown' }, firmware_update: { status: 'idle' } };
        const metadata = device.metadata || {};
        status.connection = status.connection || metadata.connection || {};
        status.firmware_update = status.firmware_update || metadata.firmware_update || {};
        status.calibration_job = metadata.calibration_job || {};
        return {
          device,
          status,
          hasActiveCalibration: activeCalSet.has(Number(device.device_id)),
        };
      });

      tbody.innerHTML = deviceRows.map((row) => buildRow(row.device, row.status, row.hasActiveCalibration)).join('');
      refreshSelectors();
      updateKpis();
      loaded = true;
    } catch (e) {
      if (e.status === 401) return;
      tbody.innerHTML = `<tr><td colspan="8" class="py-3 text-error">${e.message}</td></tr>`;
    }
  }

  function selectedRowFrom(selectorId) {
    const el = document.getElementById(selectorId);
    if (!el) return null;
    const id = Number(el.value);
    if (!Number.isFinite(id)) return null;
    return deviceRows.find((r) => Number(r.device.device_id) === id) || null;
  }

  function updateFirmwareContext() {
    const row = selectedRowFrom('fw-device-select');
    const currentInput = document.getElementById('fw-current-version');
    const recInput = document.getElementById('fw-recommended-version');
    const ctx = document.getElementById('fw-context');
    if (!row) {
      if (currentInput) currentInput.value = '';
      if (recInput) recInput.value = '';
      if (ctx) ctx.textContent = 'Select a device to view recommended update.';
      return;
    }
    const current = row.device.firmware_version || '1.0.0';
    const recommended = firmwareRecommended(current);
    if (currentInput) currentInput.value = `Current: ${current}`;
    if (recInput) recInput.value = `Recommended: ${recommended}`;
    if (ctx) ctx.textContent = `${row.device.serial_number || `Device #${row.device.device_id}`}: update recommended to maintain reliability.`;
  }

  function updateCalibrationContext() {
    const row = selectedRowFrom('cal-device-select');
    const ctx = document.getElementById('cal-context');
    if (!row || !ctx) return;
    const r = readiness(row.status, row.hasActiveCalibration);
    if (r.text === 'Needs Calibration') {
      ctx.textContent = `${row.device.serial_number || `Device #${row.device.device_id}`}: calibration recommended before next assessment.`;
    } else {
      ctx.textContent = `${row.device.serial_number || `Device #${row.device.device_id}`}: calibration valid.`;
    }
  }

  function bindForms() {
    document.getElementById('pair-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const manualSerial = String(fd.get('serial_number') || '').trim();
      const serial = manualSerial || `INSOLE-${Date.now().toString().slice(-6)}`;
      const payload = {
        serial_number: serial,
        connection_status: 'connected',
        connection_quality: 'good',
      };
      const msg = document.getElementById('pair-msg');
      try {
        const out = await window.WBSUI.api('/api/devices/pair/', { method: 'POST', body: payload });
        msg.textContent = `Paired ${out.device.serial_number || `device ${out.device.device_id}`}`;
        msg.className = 'text-xs mt-2 text-secondary';
        e.currentTarget.reset();
        loaded = false;
        await loadDevices();
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-error';
      }
    });

    document.getElementById('fw-device-select')?.addEventListener('change', updateFirmwareContext);
    document.getElementById('cal-device-select')?.addEventListener('change', updateCalibrationContext);

    document.getElementById('fw-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const deviceId = Number(fd.get('device_id'));
      const row = deviceRows.find((r) => Number(r.device.device_id) === deviceId);
      const current = row?.device?.firmware_version || '1.0.0';
      const target = firmwareRecommended(current);
      const msg = document.getElementById('fw-msg');
      try {
        const out = await window.WBSUI.api(`/api/devices/${deviceId}/firmware/update/`, {
          method: 'POST',
          body: { target_version: target, duration_sec: Number(fd.get('duration_sec')) || 8 },
        });
        msg.textContent = `Firmware update started: ${out.current_version || current} -> ${target}`;
        msg.className = 'text-xs mt-2 text-secondary';
        loaded = false;
        await loadDevices();
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-error';
      }
    });

    document.getElementById('cal-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const msg = document.getElementById('cal-msg');
      try {
        const out = await window.WBSUI.api('/api/calibration/run/', {
          method: 'POST',
          body: {
            device_id: Number(fd.get('device_id')),
            profile_name: String(fd.get('profile_name') || 'clinic-default'),
            version: String(fd.get('version') || 'v1'),
            duration_sec: Number(fd.get('duration_sec')) || 6,
            parameters: {},
          },
        });
        msg.textContent = `Calibration started (${out.calibration_job.progress_pct || 0}% initial).`;
        msg.className = 'text-xs mt-2 text-secondary';
        loaded = false;
        await loadDevices();
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-error';
      }
    });
  }

  function init() {
    bindForms();
    window.WBSUI.ready.then(loadDevices);
  }

  document.addEventListener('DOMContentLoaded', init);
  window.addEventListener('wbs-auth-changed', loadDevices);
})();
