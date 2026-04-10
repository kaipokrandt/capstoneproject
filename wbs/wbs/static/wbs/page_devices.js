(function () {
  let loaded = false;

  function healthSummary(status) {
    if (!status) return '-';
    const battery = status.connection?.battery_pct;
    const quality = status.connection?.quality || 'unknown';
    return `${battery ?? '-'}% / ${quality}`;
  }

  async function fetchDeviceStatus(deviceId) {
    try {
      return await window.WBSUI.api(`/api/devices/${deviceId}/status/`);
    } catch (_e) {
      return null;
    }
  }

  async function loadDevices() {
    if (loaded) return;
    const tbody = document.getElementById('devices-tbody');
    tbody.innerHTML = '<tr><td colspan="4" class="py-3">Loading...</td></tr>';
    try {
      const data = await window.WBSUI.api('/api/devices/');
      if (!data.items.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="py-3">No devices yet</td></tr>';
        return;
      }
      const rows = [];
      for (const d of data.items) {
        const st = await fetchDeviceStatus(d.device_id);
        rows.push(`<tr class="border-b border-outline-variant/10">
          <td class="py-3">${d.serial_number}</td>
          <td>${d.firmware_version || '-'}</td>
          <td>${healthSummary(st)}</td>
          <td>${st?.pairing?.status || 'unpaired'}</td>
        </tr>`);
      }
      tbody.innerHTML = rows.join('');
      loaded = true;
    } catch (e) {
      if (e.status === 401) return;
      tbody.innerHTML = `<tr><td colspan="4" class="py-3 text-error">${e.message}</td></tr>`;
    }
  }

  function bindForms() {
    document.getElementById('pair-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const payload = Object.fromEntries(fd.entries());
      if (payload.device_id) payload.device_id = Number(payload.device_id);
      else delete payload.device_id;
      if (!payload.serial_number) delete payload.serial_number;
      const msg = document.getElementById('pair-msg');
      try {
        const out = await window.WBSUI.api('/api/devices/pair/', { method: 'POST', body: payload });
        msg.textContent = `Paired device ${out.device.device_id}`;
        msg.className = 'text-xs mt-2 text-secondary';
        loaded = false;
        await loadDevices();
      } catch (err) {
        msg.textContent = err.message;
        msg.className = 'text-xs mt-2 text-error';
      }
    });

    document.getElementById('fw-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.currentTarget);
      const deviceId = Number(fd.get('device_id'));
      const msg = document.getElementById('fw-msg');
      try {
        const out = await window.WBSUI.api(`/api/devices/${deviceId}/firmware/update/`, {
          method: 'POST',
          body: { target_version: fd.get('target_version'), duration_sec: Number(fd.get('duration_sec')) || 8 },
        });
        msg.textContent = `Firmware ${out.update.status}: ${out.update.target_version}`;
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
            profile_name: fd.get('profile_name'),
            version: fd.get('version'),
            duration_sec: Number(fd.get('duration_sec')) || 6,
            parameters: {},
          },
        });
        msg.textContent = `Calibration ${out.calibration_job.status}`;
        msg.className = 'text-xs mt-2 text-secondary';
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
