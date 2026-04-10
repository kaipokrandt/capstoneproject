(function () {
  let loaded = false;

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '-';
  }

  function setList(id, items, emptyText) {
    const el = document.getElementById(id);
    if (!el) return;
    const rows = (items && items.length) ? items : [emptyText];
    el.innerHTML = rows.map((row) => `<li>${row}</li>`).join('');
  }

  function deviceHealthClass(value, warnWhenLow) {
    if (warnWhenLow) {
      if (value > 0) return 'ca-status-warn';
      return 'ca-status-ok';
    }
    if (value > 0) return 'ca-status-ok';
    return 'ca-status-danger';
  }

  async function load() {
    if (loaded) return;
    try {
      const [overview, patientsRes, devicesRes, reportsRes] = await Promise.all([
        window.WBSUI.api('/api/overview/'),
        window.WBSUI.api('/api/patients/'),
        window.WBSUI.api('/api/devices/'),
        window.WBSUI.api('/api/reports/'),
      ]);

      const patients = patientsRes.items || [];
      const devices = devicesRes.items || [];
      const reports = reportsRes.items || [];

      setText('kpi-patients', overview.counts?.patients ?? 0);
      setText('kpi-devices', overview.counts?.devices ?? 0);
      setText('kpi-sessions', overview.counts?.sessions ?? 0);
      setText('kpi-reports', overview.counts?.reports ?? 0);

      const uniqueReportedSessions = new Set(reports.map((r) => r.session_id).filter((x) => x !== null && x !== undefined));
      const pendingReviewCount = Math.max(0, (overview.counts?.sessions || 0) - uniqueReportedSessions.size);

      setText('kpi-patients-meta', `${Math.min(patients.length, 5)} recently active`);
      setText('kpi-devices-meta', 'readiness shown at right');
      setText('kpi-sessions-meta', `${pendingReviewCount} pending report review`);
      setText('kpi-reports-meta', `${reports.length} generated records`);

      const recentPatients = [...patients]
        .sort((a, b) => (b.patient_id || 0) - (a.patient_id || 0))
        .slice(0, 5)
        .map((p) => `${p.external_id} - ${(p.first_name || '').trim()} ${(p.last_name || '').trim()}`.trim());
      setList('dash-recent-patients', recentPatients, 'No recent patients');

      const recentReports = reports.slice(0, 5).map((r) => `Report #${r.report_id} for Session #${r.session_id}`);
      setList('dash-recent-reports', recentReports, 'No reports yet');

      const recentSessions = Array.from(uniqueReportedSessions)
        .slice(0, 5)
        .map((sid) => `Session #${sid}`);
      setList('dash-recent-sessions', recentSessions, 'No recent sessions');

      const pendingItems = [];
      if (pendingReviewCount > 0) pendingItems.push(`${pendingReviewCount} sessions missing reports`);
      const highRiskReport = reports.find((r) => String(r.payload?.session?.risk_label || '').toLowerCase() === 'high');
      if (highRiskReport) pendingItems.push(`High-risk session #${highRiskReport.session_id} needs review`);
      if (!pendingItems.length) pendingItems.push('No critical review alerts');
      setList('dash-pending-review', pendingItems, 'No pending review');

      const deviceStatuses = await Promise.all(
        devices.map(async (d) => {
          try {
            return await window.WBSUI.api(`/api/devices/${d.device_id}/status/`);
          } catch (_e) {
            return null;
          }
        }),
      );
      const connectedNow = deviceStatuses.filter((s) => {
        const status = String(s?.pairing?.status || '').toLowerCase();
        const conn = String(s?.connection?.status || '').toLowerCase();
        return status === 'paired' || conn === 'connected';
      }).length;
      const batteryAlerts = deviceStatuses.filter((s) => {
        const batt = Number(s?.connection?.battery_pct);
        return Number.isFinite(batt) && batt < 30;
      }).length;
      const firmwareInProgress = deviceStatuses.filter((s) => String(s?.firmware_update?.status || '').toLowerCase() === 'in_progress').length;

      setText('device-connected-now', `${connectedNow}/${devices.length}`);
      setText('device-battery-alerts', String(batteryAlerts));
      setText('device-firmware-progress', String(firmwareInProgress));

      const battEl = document.getElementById('device-battery-alerts');
      const connEl = document.getElementById('device-connected-now');
      const fwEl = document.getElementById('device-firmware-progress');
      if (battEl) battEl.className = `text-sm font-semibold ${deviceHealthClass(batteryAlerts, true)}`;
      if (connEl) connEl.className = `text-sm font-semibold ${connectedNow > 0 ? 'ca-status-ok' : 'ca-status-warn'}`;
      if (fwEl) fwEl.className = `text-sm font-semibold ${firmwareInProgress > 0 ? 'ca-status-warn' : 'ca-status-ok'}`;

      setText('status-health', (overview.health || 'unknown').toUpperCase());
      setText('status-auth', overview.authenticated ? 'SIGNED IN' : 'SIGNED OUT');
      setText('status-time', overview.timestamp || '-');
      if (overview.user) {
        setText('status-user', `${overview.user.username || '-'} (${overview.user.email || 'no email'})`);
      } else {
        setText('status-user', 'No active user');
      }
      setText('status-latest-session', overview.latest?.session_id ?? 'none');
      setText('status-latest-report', overview.latest?.report_id ?? 'none');

      setText('check-api', 'OK');
      setText('check-auth', overview.authenticated ? 'OK' : 'FAIL');
      const dataReady = (overview.counts?.patients || 0) + (overview.counts?.devices || 0) + (overview.counts?.sessions || 0) > 0;
      setText('check-data', dataReady ? 'OK' : 'EMPTY');

      loaded = true;
    } catch (e) {
      if (e.status === 401) return;
      const err = document.getElementById('status-error');
      if (err) {
        err.textContent = e.message;
        err.classList.remove('hidden');
      }
      setList('dash-recent-patients', ['P-DEMO-004 - Alex Chen', 'P-DEMO-002 - Jordan Lee'], 'No recent patients');
      setList('dash-recent-sessions', ['Session #4021', 'Session #4018'], 'No recent sessions');
      setList('dash-pending-review', ['1 sessions missing reports'], 'No pending review');
      setList('dash-recent-reports', ['Report #101 for Session #4021'], 'No reports yet');
      setText('device-connected-now', '3/5');
      setText('device-battery-alerts', '1');
      setText('device-firmware-progress', '0');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    window.WBSUI.ready.then(load);
  });
  window.addEventListener('wbs-auth-changed', load);
})();
