(function () {
  const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

  const state = {
    loaded: false,
    patients: [],
    patientsById: {},
    reports: [],
    sessionCatalog: [],
    sessionById: {},
    fhirSessions: new Set(),
    selectedPatientId: null,
    selectedSessionId: null,
    modalOpen: false,
    modalActiveTab: "summary",
    modalReport: null,
    modalLastTrigger: null,
  };

  const REPORT_LABELS = {
    clinical_summary: "Clinical Summary PDF",
    fall_risk_summary: "Fall Risk Summary PDF",
    fhir_export: "EMR Export Package",
  };

  const METRIC_LABELS = {
    stability_score: "Stability Score",
    symmetry_index: "Pressure Symmetry",
    cop_x: "Medial-Lateral Sway",
    cop_y: "Anterior-Posterior Sway",
    total_load: "Load Balance",
  };

  function safeNum(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function fmtDateTimeIso(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "-";
    return d.toLocaleString();
  }

  function fmtDateFromUs(us) {
    const n = Number(us);
    if (!Number.isFinite(n) || n <= 0) return "-";
    const dt = new Date(Math.floor(n / 1000));
    if (Number.isNaN(dt.getTime())) return "-";
    return dt.toLocaleDateString();
  }

  function riskText(label, score) {
    const l = String(label || "").trim();
    if (l && Number.isFinite(safeNum(score, null))) return `${l[0].toUpperCase()}${l.slice(1)} (${Number(score).toFixed(1)})`;
    if (l) return l[0].toUpperCase() + l.slice(1);
    if (Number.isFinite(safeNum(score, null))) return `Score ${Number(score).toFixed(1)}`;
    return "Not classified";
  }

  function prettyAssessment(source) {
    const value = String(source || "").trim();
    if (!value) return "Assessment";
    return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function patientName(patientId) {
    const p = state.patientsById[String(patientId)];
    if (!p) return patientId ? `Patient #${patientId}` : "Needs assignment";
    const full = `${p.first_name || ""} ${p.last_name || ""}`.trim();
    return full || p.external_id || `Patient #${patientId}`;
  }

  function reportLabel(type) {
    return REPORT_LABELS[type] || String(type || "Report").replaceAll("_", " ");
  }

  function setMsg(id, text, isErr, extraClass) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    if (extraClass) {
      el.className = extraClass;
      return;
    }
    el.className = isErr ? "text-xs mt-2 text-error" : "text-xs mt-2 text-secondary";
  }

  function selectedSessionInfo() {
    return state.sessionCatalog.find((s) => s.session_id === state.selectedSessionId) || null;
  }

  function refreshSelectionSummary() {
    const line = document.getElementById("report-selection-summary");
    const emr = document.getElementById("emr-status");
    const info = selectedSessionInfo();
    if (!line || !emr) return;

    if (!state.selectedPatientId || !state.selectedSessionId || !info) {
      line.textContent = "Choose a patient and session to continue.";
      emr.textContent = "Select a session first";
      return;
    }

    const patient = patientName(info.patient_id);
    const date = fmtDateFromUs(info.started_at_us);
    const assessment = prettyAssessment(info.source);
    const risk = riskText(info.risk_label, info.risk_score);
    line.textContent = `${patient} · ${date} · ${assessment} · ${risk}`;

    emr.textContent = info.has_fhir_export
      ? "Already synced to EMR for this session (you can re-send)"
      : "Ready to send to EMR";
  }

  async function loadSessionCatalog() {
    const path = state.selectedPatientId ? `/api/sessions/?patient_id=${state.selectedPatientId}` : "/api/sessions/";
    const sessions = await window.WBSUI.api(path);

    state.sessionCatalog = (sessions.items || []).map((s) => ({
      session_id: s.session_id,
      patient_id: s.patient_id,
      started_at_us: s.started_at_us,
      source: s.source || "",
      risk_label: s.risk_label || "",
      risk_score: s.risk_score,
      has_fhir_export: state.fhirSessions.has(Number(s.session_id)),
    }));

    state.sessionById = Object.fromEntries(state.sessionCatalog.map((s) => [String(s.session_id), s]));
  }

  function resolvedSessionContext(report) {
    const payloadSession = report.payload?.session || {};
    const liveSession = state.sessionById[String(report.session_id)] || {};
    return {
      patient_id: payloadSession.patient_id ?? liveSession.patient_id ?? report.patient_id ?? null,
      started_at_us: payloadSession.started_at_us ?? liveSession.started_at_us ?? report.started_at_us ?? null,
      source: payloadSession.source ?? liveSession.source ?? report.session_source ?? "",
      risk_label: payloadSession.risk_label ?? liveSession.risk_label ?? report.risk_label ?? "",
      risk_score: payloadSession.risk_score ?? liveSession.risk_score ?? report.risk_score ?? null,
    };
  }

  function reportStatus(report) {
    const sid = Number(report.session_id);
    if (report.report_type === "fhir_export") return "Synced to EMR";
    if (state.fhirSessions.has(sid)) return "Generated + Synced";
    return "Generated";
  }

  function statusClass(status) {
    if (status.includes("Synced")) return "text-xs ca-status-ok";
    return "text-xs text-on-surface-variant";
  }

  function populatePatientSelect() {
    const sel = document.getElementById("report-patient-select");
    if (!sel) return;

    const options = ['<option value="">Select patient</option>'].concat(
      state.patients.map((p) => {
        const full = `${p.first_name || ""} ${p.last_name || ""}`.trim() || p.external_id;
        return `<option value="${p.patient_id}">${full} (${p.external_id})</option>`;
      }),
    );
    sel.innerHTML = options.join("");

    const preferred = localStorage.getItem("selected_patient_id");
    if (preferred && sel.querySelector(`option[value="${preferred}"]`)) {
      sel.value = preferred;
      state.selectedPatientId = Number(preferred);
    }
  }

  function populateSessionSelect() {
    const sel = document.getElementById("report-session-select");
    if (!sel) return;

    const filtered = state.selectedPatientId
      ? state.sessionCatalog.filter((s) => Number(s.patient_id) === Number(state.selectedPatientId))
      : state.sessionCatalog;

    if (!filtered.length) {
      sel.innerHTML = '<option value="">No sessions found for selection</option>';
      state.selectedSessionId = null;
      refreshSelectionSummary();
      return;
    }

    sel.innerHTML = ['<option value="">Select assessment session</option>']
      .concat(
        filtered.map((s) => {
          const date = fmtDateFromUs(s.started_at_us);
          const assessment = prettyAssessment(s.source);
          return `<option value="${s.session_id}">#${s.session_id} · ${date} · ${assessment}</option>`;
        }),
      )
      .join("");

    const current = state.selectedSessionId && filtered.find((s) => s.session_id === state.selectedSessionId);
    if (current) {
      sel.value = String(state.selectedSessionId);
    } else {
      state.selectedSessionId = filtered[0].session_id;
      sel.value = String(state.selectedSessionId);
    }
    refreshSelectionSummary();
  }

  function getModalEls() {
    return {
      root: document.getElementById("report-preview-modal"),
      backdrop: document.getElementById("report-preview-backdrop"),
      panel: document.getElementById("report-modal-panel"),
      close: document.getElementById("report-modal-close"),
      closeFooter: document.getElementById("report-modal-close-footer"),
      title: document.getElementById("report-modal-title"),
      subtitle: document.getElementById("report-modal-subtitle"),
      status: document.getElementById("report-modal-status"),
      state: document.getElementById("report-modal-state"),
      tabSummary: document.getElementById("report-tab-summary"),
      tabPdf: document.getElementById("report-tab-pdf"),
      paneSummary: document.getElementById("report-modal-summary-pane"),
      panePdf: document.getElementById("report-modal-pdf-pane"),
      summaryContent: document.getElementById("report-modal-summary-content"),
      pdfFrame: document.getElementById("report-modal-pdf-frame"),
      pdfFallback: document.getElementById("report-modal-pdf-fallback"),
      pdfLink: document.getElementById("report-modal-pdf-link"),
      btnDownload: document.getElementById("report-modal-download"),
      btnSync: document.getElementById("report-modal-sync"),
    };
  }

  function setModalTab(tab) {
    state.modalActiveTab = tab;
    const el = getModalEls();
    if (!el.tabSummary || !el.tabPdf || !el.paneSummary || !el.panePdf) return;

    const summaryActive = tab === "summary";
    el.tabSummary.classList.toggle("active", summaryActive);
    el.tabPdf.classList.toggle("active", !summaryActive);
    el.tabSummary.setAttribute("aria-selected", summaryActive ? "true" : "false");
    el.tabPdf.setAttribute("aria-selected", summaryActive ? "false" : "true");

    el.paneSummary.classList.toggle("active", summaryActive);
    el.panePdf.classList.toggle("active", !summaryActive);
  }

  function setModalMeta(report, session, statusText) {
    const el = getModalEls();
    const patient = patientName(session.patient_id);
    const assessment = prettyAssessment(session.source);
    const date = fmtDateFromUs(session.started_at_us);
    const risk = riskText(session.risk_label, session.risk_score);
    if (el.title) el.title.textContent = reportLabel(report.report_type);
    if (el.subtitle) el.subtitle.textContent = `${patient} · ${date} · ${assessment} · ${risk}`;
    if (el.status) {
      el.status.textContent = statusText;
      el.status.className = statusClass(statusText);
    }
  }

  function renderModalSummary(report, session, statusText) {
    const el = getModalEls();
    const payload = report.payload || {};
    const counts = payload.counts || {};
    const metrics = payload.metrics_summary || {};
    const synced = statusText.includes("Synced");

    const metricRows = Object.entries(metrics)
      .slice(0, 8)
      .map(([name, s]) => {
        const avg = s?.avg !== undefined ? Number(s.avg).toFixed(2) : "-";
        return `<tr><td class="pr-4 py-1">${METRIC_LABELS[name] || name}</td><td class="font-mono">${avg}</td></tr>`;
      })
      .join("");

    if (!el.summaryContent) return;
    el.summaryContent.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
        <div><span class="ca-title-kicker block">Patient</span><span class="text-on-surface font-semibold">${patientName(session.patient_id)}</span></div>
        <div><span class="ca-title-kicker block">Session Date</span><span class="text-on-surface">${fmtDateFromUs(session.started_at_us)}</span></div>
        <div><span class="ca-title-kicker block">Assessment</span><span class="text-on-surface">${prettyAssessment(session.source)}</span></div>
        <div><span class="ca-title-kicker block">Risk</span><span class="text-on-surface">${riskText(session.risk_label, session.risk_score)}</span></div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <div class="ca-subtle p-3"><span class="ca-title-kicker block mb-1">Report Status</span><span class="${statusClass(statusText)}">${statusText}</span></div>
        <div class="ca-subtle p-3"><span class="ca-title-kicker block mb-1">Created</span><span class="text-on-surface">${fmtDateTimeIso(report.generated_at)}</span></div>
        <div class="ca-subtle p-3"><span class="ca-title-kicker block mb-1">Counts</span><span class="text-on-surface">Frames ${counts.raw_frames ?? "-"} · Metrics ${counts.computed_metrics ?? "-"}</span></div>
      </div>
      <div class="mb-3">
        <span class="ca-title-kicker block mb-1">Key Metrics</span>
        <table class="text-xs">${metricRows || "<tr><td>No metric summary available</td></tr>"}</table>
      </div>
      <div class="mb-3">
        <span class="ca-title-kicker block mb-1">Clinician Note</span>
        <p class="text-sm text-on-surface-variant">${report.clinician_notes || "None"}</p>
      </div>
      <div>
        <span class="ca-title-kicker block mb-1">Status Timeline</span>
        <ul class="text-sm text-on-surface-variant list-disc pl-4">
          <li>Generated at ${fmtDateTimeIso(report.generated_at)}</li>
          <li>${synced ? "Synced to EMR" : "Pending EMR sync"}</li>
        </ul>
      </div>
    `;
  }

  function setModalPdf(report) {
    const el = getModalEls();
    if (!el.pdfFrame || !el.pdfLink) return;
    const pdfUrl = `/api/reports/${report.report_id}/download/`;
    el.pdfFallback?.classList.add("hidden");
    el.pdfLink.href = pdfUrl;
    el.pdfFrame.onerror = function () {
      el.pdfFallback?.classList.remove("hidden");
    };
    el.pdfFrame.src = pdfUrl;
  }

  function setModalState(text, err) {
    const el = getModalEls();
    if (!el.state) return;
    el.state.textContent = text;
    el.state.className = err ? "text-xs ca-status-danger" : "text-xs text-on-surface-variant";
  }

  function getFocusableInModal() {
    const el = getModalEls();
    if (!el.panel) return [];
    return Array.from(el.panel.querySelectorAll(FOCUSABLE_SELECTOR)).filter((node) => !node.hasAttribute("disabled"));
  }

  function handleModalKeydown(e) {
    if (!state.modalOpen) return;
    if (e.key === "Escape") {
      e.preventDefault();
      closePreviewModal();
      return;
    }
    if (e.key !== "Tab") return;
    const focusables = getFocusableInModal();
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function openModalShell() {
    const el = getModalEls();
    if (!el.root) return;
    el.root.classList.remove("hidden");
    el.root.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    state.modalOpen = true;
    document.addEventListener("keydown", handleModalKeydown);
  }

  function closePreviewModal() {
    const el = getModalEls();
    if (!el.root) return;
    el.root.classList.add("hidden");
    el.root.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    state.modalOpen = false;
    state.modalReport = null;
    document.removeEventListener("keydown", handleModalKeydown);

    if (state.modalLastTrigger && typeof state.modalLastTrigger.focus === "function") {
      state.modalLastTrigger.focus();
    }
  }

  async function openPreviewModal(reportId, triggerEl) {
    state.modalLastTrigger = triggerEl || null;
    openModalShell();
    setModalTab("summary");
    setModalState("Loading report details...", false);
    const el = getModalEls();
    if (el.summaryContent) el.summaryContent.textContent = "Loading report details...";
    if (el.pdfFrame) el.pdfFrame.src = "about:blank";

    try {
      const detail = await window.WBSUI.api(`/api/reports/${reportId}/`);
      state.modalReport = detail;
      const session = resolvedSessionContext(detail);
      const statusText = reportStatus(detail);
      setModalMeta(detail, session, statusText);
      renderModalSummary(detail, session, statusText);
      setModalPdf(detail);
      setModalState("Loaded", false);
      getModalEls().tabSummary?.focus();
    } catch (err) {
      setModalState(`Failed to load: ${err.message}`, true);
      if (el.summaryContent) el.summaryContent.innerHTML = '<p class="text-sm ca-status-danger">Unable to load report detail.</p>';
    }
  }

  async function syncSessionForReport(report) {
    if (!report) return;
    const sid = Number(report.session_id);
    if (!sid) return;
    setModalState("Syncing to EMR...", false);
    try {
      const out = await window.WBSUI.api(`/api/fhir/export/session/${sid}/`, { method: "POST", body: {} });
      setMsg("fhir-msg", `Sent to EMR successfully (export #${out.report_id})`, false, "text-xs mt-2 text-on-primary");
      state.loaded = false;
      await loadReports();

      const refreshed = await window.WBSUI.api(`/api/reports/${report.report_id}/`);
      state.modalReport = refreshed;
      const session = resolvedSessionContext(refreshed);
      const statusText = reportStatus(refreshed);
      setModalMeta(refreshed, session, statusText);
      renderModalSummary(refreshed, session, statusText);
      setModalState("Synced to EMR", false);
    } catch (err) {
      setModalState(`Sync failed: ${err.message}`, true);
    }
  }

  function bindPreviewButtons() {
    document.querySelectorAll(".report-preview-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const reportId = Number(btn.dataset.reportId);
        if (!reportId) return;
        openPreviewModal(reportId, btn);
      });
    });
  }

  function bindRowSyncButtons() {
    document.querySelectorAll(".report-sync-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sid = Number(btn.dataset.sessionId);
        if (!sid) return;
        try {
          const out = await window.WBSUI.api(`/api/fhir/export/session/${sid}/`, { method: "POST", body: {} });
          setMsg("fhir-msg", `Sent to EMR successfully (export #${out.report_id})`, false, "text-xs mt-2 text-on-primary");
          setMsg("report-msg", `Session #${sid} synced to EMR`, false);
          state.loaded = false;
          await loadReports();
        } catch (err) {
          setMsg("fhir-msg", `EMR sync failed: ${err.message}`, true, "text-xs mt-2 text-on-error");
        }
      });
    });
  }

  function bindModal() {
    const el = getModalEls();
    if (!el.root) return;

    el.close?.addEventListener("click", closePreviewModal);
    el.closeFooter?.addEventListener("click", closePreviewModal);
    el.backdrop?.addEventListener("click", closePreviewModal);
    el.tabSummary?.addEventListener("click", () => setModalTab("summary"));
    el.tabPdf?.addEventListener("click", () => setModalTab("pdf"));
    el.btnDownload?.addEventListener("click", () => {
      if (!state.modalReport) return;
      window.open(`/api/reports/${state.modalReport.report_id}/download/`, "_blank", "noopener");
    });
    el.btnSync?.addEventListener("click", () => {
      syncSessionForReport(state.modalReport);
    });
  }

  async function loadReports() {
    if (state.loaded) return;
    const tbody = document.getElementById("reports-tbody");
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="py-3">Loading...</td></tr>';

    try {
      const reportsData = await window.WBSUI.api("/api/reports/");
      state.reports = reportsData.items || [];
      state.fhirSessions = new Set(state.reports.filter((r) => r.report_type === "fhir_export").map((r) => Number(r.session_id)));

      await loadSessionCatalog();
      populateSessionSelect();

      if (!state.reports.length) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="py-3">No reports yet. Select a patient/session and generate one.</td></tr>';
        state.loaded = true;
        return;
      }

      if (tbody) {
        tbody.innerHTML = state.reports
          .map((r) => {
            const session = resolvedSessionContext(r);
            const status = reportStatus(r);
            const risk = riskText(session.risk_label, session.risk_score);
            const patient = patientName(session.patient_id);
            const assessment = prettyAssessment(session.source);
            const sessionDate = fmtDateFromUs(session.started_at_us);
            return `
              <tr class="border-b border-outline-variant/10">
                <td class="py-3">${patient}</td>
                <td>${sessionDate}</td>
                <td>${assessment}</td>
                <td>${risk}</td>
                <td>${reportLabel(r.report_type)}</td>
                <td><span class="${statusClass(status)}">${status}</span></td>
                <td>${fmtDateTimeIso(r.generated_at)}</td>
                <td class="whitespace-nowrap">
                  <a class="text-primary underline mr-2" href="/api/reports/${r.report_id}/download/" target="_blank" rel="noopener">PDF</a>
                  <button class="report-preview-btn text-secondary underline mr-2" data-report-id="${r.report_id}">Preview</button>
                  ${r.report_type === "fhir_export" ? "" : `<button class="report-sync-btn text-on-surface-variant underline" data-session-id="${r.session_id}">Sync</button>`}
                </td>
              </tr>
            `;
          })
          .join("");
      }

      bindPreviewButtons();
      bindRowSyncButtons();
      state.loaded = true;
    } catch (err) {
      if (err.status === 401) return;
      if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="py-3 text-error">${err.message}</td></tr>`;
    }
  }

  function downloadJson(filename, payload) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(href);
  }

  async function loadPatients() {
    const data = await window.WBSUI.api("/api/patients/");
    state.patients = data.items || [];
    state.patientsById = Object.fromEntries(state.patients.map((p) => [String(p.patient_id), p]));
    populatePatientSelect();
  }

  function requireSelection(msgId, darkMsgId) {
    if (!state.selectedSessionId) {
      setMsg(msgId, "Select a patient and session first.", true);
      if (darkMsgId) setMsg(darkMsgId, "Select a patient and session first.", true, "text-xs mt-2 text-on-error");
      return false;
    }
    return true;
  }

  function bindForms() {
    const patientSel = document.getElementById("report-patient-select");
    const sessionSel = document.getElementById("report-session-select");

    if (patientSel) {
      patientSel.addEventListener("change", async () => {
        state.selectedPatientId = Number(patientSel.value) || null;
        if (state.selectedPatientId) localStorage.setItem("selected_patient_id", String(state.selectedPatientId));
        state.selectedSessionId = null;
        await loadSessionCatalog();
        populateSessionSelect();
      });
    }

    if (sessionSel) {
      sessionSel.addEventListener("change", () => {
        state.selectedSessionId = Number(sessionSel.value) || null;
        refreshSelectionSummary();
      });
    }

    document.getElementById("report-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!requireSelection("report-msg")) return;
      const fd = new FormData(e.currentTarget);
      try {
        await window.WBSUI.api("/api/reports/generate/", {
          method: "POST",
          body: {
            session_id: state.selectedSessionId,
            report_type: fd.get("report_type") || "clinical_summary",
            clinician_notes: fd.get("clinician_notes") || "",
          },
        });
        setMsg("report-msg", "Report generated successfully.", false);
        state.loaded = false;
        await loadReports();
      } catch (err) {
        setMsg("report-msg", err.message, true);
      }
    });

    document.getElementById("fhir-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!requireSelection("fhir-msg", "fhir-msg")) return;
      try {
        const out = await window.WBSUI.api(`/api/fhir/export/session/${state.selectedSessionId}/`, { method: "POST", body: {} });
        setMsg("fhir-msg", `Sent to EMR successfully (export #${out.report_id})`, false, "text-xs mt-2 text-on-primary");
        state.loaded = false;
        await loadReports();
      } catch (err) {
        setMsg("fhir-msg", `EMR sync failed: ${err.message}`, true, "text-xs mt-2 text-on-error");
      }
    });

    document.getElementById("json-export-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!requireSelection("json-msg")) return;
      const fd = new FormData(e.currentTarget);
      const metricName = encodeURIComponent(fd.get("metric_name") || "stability_score,symmetry_index,cop_x,cop_y,total_load");
      try {
        const metrics = await window.WBSUI.api(`/api/sessions/${state.selectedSessionId}/metrics/?metric_name=${metricName}&limit=500`);
        downloadJson(`session_${state.selectedSessionId}_metrics.json`, metrics);
        setMsg("json-msg", `Downloaded JSON metrics for session #${state.selectedSessionId}.`, false);
      } catch (err) {
        const mock = {
          session_id: state.selectedSessionId,
          count: 3,
          metric_names: ["stability_score", "symmetry_index", "cop_x"],
          series: {
            stability_score: [{ ts_us: 1, value: 86.2, unit: "score" }],
            symmetry_index: [{ ts_us: 1, value: 91.7, unit: "%" }],
            cop_x: [{ ts_us: 1, value: 0.53, unit: "grid_x" }],
          },
          mock_seed: true,
          detail: err.message,
        };
        downloadJson(`session_${state.selectedSessionId}_metrics_mock.json`, mock);
        setMsg("json-msg", "Live metric export unavailable. Downloaded mock metrics JSON.", false);
      }
    });
  }

  async function init() {
    bindForms();
    bindModal();

    try {
      await loadPatients();
    } catch (_e) {
      const patientSel = document.getElementById("report-patient-select");
      if (patientSel) patientSel.innerHTML = '<option value="">Patient list unavailable</option>';
    }

    await loadReports();
    refreshSelectionSummary();
  }

  document.addEventListener("DOMContentLoaded", () => {
    window.WBSUI.ready.then(init);
  });

  window.addEventListener("wbs-auth-changed", () => {
    state.loaded = false;
    loadReports();
  });
})();
