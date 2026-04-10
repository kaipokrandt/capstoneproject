(function () {
  const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';
  const CHART_COLORS = ["#1d4ed8", "#0f766e", "#d97706", "#9333ea", "#dc2626", "#0891b2", "#16a34a", "#475569"];
  const DEFAULT_METRICS = [
    "stability_score",
    "symmetry_index",
    "cop_x",
    "cop_y",
    "total_load",
    "cop_v",
    "sway_path",
    "asymmetry_index",
    "stance_pct",
    "swing_pct",
  ];

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
    modalCharts: {},
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
    cop_v: "CoP Velocity",
    sway_path: "Sway Path",
    asymmetry_index: "Asymmetry Index",
    stance_pct: "Stance %",
    swing_pct: "Swing %",
  };

  const METRIC_COLOR = {
    stability_score: "#1d4ed8",
    symmetry_index: "#0f766e",
    cop_x: "#16a34a",
    cop_y: "#475569",
    total_load: "#0891b2",
    cop_v: "#d97706",
    sway_path: "#2563eb",
    asymmetry_index: "#0f766e",
    stance_pct: "#9333ea",
    swing_pct: "#dc2626",
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

  function isFallRiskReport(reportType) {
    return String(reportType || "").toLowerCase() === "fall_risk_summary";
  }

  function riskBand(score) {
    const s = safeNum(score, null);
    if (!Number.isFinite(s)) return { label: "Unknown", cls: "ca-status-warn" };
    if (s >= 65) return { label: "High", cls: "ca-status-danger" };
    if (s >= 35) return { label: "Moderate", cls: "ca-status-warn" };
    return { label: "Low", cls: "ca-status-ok" };
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
    emr.textContent = info.has_fhir_export ? "Already synced to EMR for this session (you can re-send)" : "Ready to send to EMR";
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
    return status.includes("Synced") ? "text-xs ca-status-ok" : "text-xs text-on-surface-variant";
  }

  function metricLabel(name) {
    return METRIC_LABELS[name] || String(name || "").replaceAll("_", " ");
  }

  function metricColor(name, idx) {
    return METRIC_COLOR[name] || CHART_COLORS[idx % CHART_COLORS.length];
  }

  function metricGroupsForCharts(metricNames, fallRisk) {
    const preferred = fallRisk
      ? [
          ["sway_path", "asymmetry_index"],
          ["cop_v", "total_load"],
          ["cop_x", "cop_y"],
          ["stance_pct", "swing_pct"],
          ["stability_score", "symmetry_index"],
        ]
      : [
          ["stability_score", "symmetry_index"],
          ["cop_x", "cop_y"],
          ["stance_pct", "swing_pct"],
          ["sway_path", "cop_v"],
          ["asymmetry_index", "total_load"],
        ];

    const available = new Set(metricNames);
    const groups = [];
    const used = new Set();

    preferred.forEach((pair) => {
      const present = pair.filter((m) => available.has(m));
      if (!present.length) return;
      present.forEach((m) => used.add(m));
      groups.push(present);
    });

    metricNames.forEach((name) => {
      if (used.has(name)) return;
      groups.push([name]);
    });
    return groups;
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

  function destroyModalCharts() {
    Object.values(state.modalCharts).forEach((chart) => {
      if (chart && typeof chart.destroy === "function") chart.destroy();
    });
    state.modalCharts = {};
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
    destroyModalCharts();
    el.root.classList.add("hidden");
    el.root.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    state.modalOpen = false;
    state.modalReport = null;
    document.removeEventListener("keydown", handleModalKeydown);
    if (state.modalLastTrigger && typeof state.modalLastTrigger.focus === "function") state.modalLastTrigger.focus();
  }

  function normalizeSeriesValues(values) {
    const finite = values.filter((v) => Number.isFinite(v));
    if (!finite.length) return values.map(() => 0);
    const min = Math.min(...finite);
    const max = Math.max(...finite);
    if (max === min) return values.map(() => 50);
    return values.map((v) => (Number.isFinite(v) ? ((v - min) / (max - min)) * 100 : null));
  }

  function buildSeriesMapFromPayload(payload) {
    const out = {};
    const preview = payload?.metrics_series_preview || {};
    Object.entries(preview).forEach(([name, rows]) => {
      out[name] = (rows || []).map((r) => ({ ts_us: r.ts_us, value: safeNum(r.value, null) })).filter((r) => Number.isFinite(r.value));
    });
    return out;
  }

  async function fetchSessionSeries(report) {
    const sid = Number(report.session_id);
    if (!sid) return {};
    try {
      const url = `/api/sessions/${sid}/metrics/?metric_name=${encodeURIComponent(DEFAULT_METRICS.join(","))}&limit=500`;
      const data = await window.WBSUI.api(url);
      const out = {};
      (data.metric_names || []).forEach((name) => {
        out[name] = (data.series?.[name] || []).map((r) => ({ ts_us: r.ts_us, value: safeNum(r.value, null) })).filter((r) => Number.isFinite(r.value));
      });
      return out;
    } catch (_err) {
      return buildSeriesMapFromPayload(report.payload || {});
    }
  }

  function renderModalCharts(metricsSummary, seriesMap, riskScore, reportType) {
    if (!window.Chart) return;
    destroyModalCharts();
    const fallRisk = isFallRiskReport(reportType);

    const metricNames = Object.keys(metricsSummary || {});
    const namesForPanels = metricNames.length ? metricNames : Object.keys(seriesMap || {});
    const groups = metricGroupsForCharts(namesForPanels, fallRisk).slice(0, 8);

    const grid = document.getElementById("modal-chart-metric-grid");
    if (grid) {
      grid.innerHTML = groups
        .map((group, idx) => `
          <div class="ca-subtle p-2">
            <p class="text-xs font-semibold text-primary mb-1">${group.map(metricLabel).join(" + ")}</p>
            <div class="h-44"><canvas id="modal-chart-group-${idx}"></canvas></div>
          </div>
        `)
        .join("");
    }

    groups.forEach((group, idx) => {
      const seriesRows = group.map((name) => ({
        name,
        values: (seriesMap?.[name] || []).map((p) => p.value),
      }));
      const hasRealSeries = seriesRows.some((s) => s.values.length >= 2);
      const labels = hasRealSeries
        ? Array.from({ length: Math.max(...seriesRows.map((s) => s.values.length)) }, (_, i) => `T${i + 1}`)
        : ["Snapshot"];
      const datasets = seriesRows.map((row, i) => {
        const color = metricColor(row.name, idx + i);
        return {
          label: metricLabel(row.name),
          data: hasRealSeries ? normalizeSeriesValues(row.values) : [safeNum(metricsSummary[row.name]?.avg, 0)],
          borderColor: color,
          backgroundColor: `${color}33`,
          tension: 0.25,
          pointRadius: 2,
          fill: false,
          spanGaps: true,
        };
      });

      const ctx = document.getElementById(`modal-chart-group-${idx}`);
      if (!ctx || !datasets.length) return;
      state.modalCharts[`group_${idx}`] = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { legend: { position: "top" } },
          scales: hasRealSeries ? { y: { min: 0, max: 100 } } : undefined,
        },
      });
    });

    const copX = (seriesMap?.cop_x || []).map((p) => p.value);
    const copY = (seriesMap?.cop_y || []).map((p) => p.value);
    const copLabels = Array.from({ length: Math.max(copX.length, copY.length) }, (_, i) => `T${i + 1}`);
    const copCtx = document.getElementById("modal-chart-cop");
    if (copCtx && copLabels.length) {
      state.modalCharts.cop = new Chart(copCtx, {
        type: "line",
        data: {
          labels: copLabels,
          datasets: [
            { label: "Medial-Lateral Sway", data: copX, borderColor: "#1d4ed8", backgroundColor: "#1d4ed833", tension: 0.25, fill: false },
            { label: "Anterior-Posterior Sway", data: copY, borderColor: "#d97706", backgroundColor: "#d9770633", tension: 0.25, fill: false },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { title: { display: true, text: fallRisk ? "Sway Behavior (CoP)" : "CoP Behavior" } },
        },
      });
    }

    const barNames = (fallRisk
      ? ["asymmetry_index", "sway_path", "cop_v", "stability_score", "symmetry_index", "stance_pct", "swing_pct", "total_load"]
      : Object.keys(metricsSummary || {}))
      .filter((n) => Object.prototype.hasOwnProperty.call(metricsSummary || {}, n))
      .slice(0, 8);

    const barCtx = document.getElementById("modal-chart-summary");
    if (barCtx && barNames.length) {
      state.modalCharts.summary = new Chart(barCtx, {
        type: "bar",
        data: {
          labels: barNames.map(metricLabel),
          datasets: [
            { label: "Avg", data: barNames.map((n) => safeNum(metricsSummary[n]?.avg, 0)), backgroundColor: "#0f766e99" },
            { label: "Min", data: barNames.map((n) => safeNum(metricsSummary[n]?.min, 0)), backgroundColor: "#1d4ed866" },
            { label: "Max", data: barNames.map((n) => safeNum(metricsSummary[n]?.max, 0)), backgroundColor: "#d9770666" },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: { title: { display: true, text: fallRisk ? "Fall-Risk Metric Distribution" : "Metric Summary Distribution" } },
        },
      });
    }

    const radarCtx = document.getElementById("modal-chart-radar");
    if (radarCtx && barNames.length) {
      const avgs = barNames.map((n) => safeNum(metricsSummary[n]?.avg, 0));
      const norm = normalizeSeriesValues(avgs);
      state.modalCharts.radar = new Chart(radarCtx, {
        type: "radar",
        data: {
          labels: barNames.map(metricLabel),
          datasets: [{
            label: fallRisk ? "Normalized Fall-Risk Profile" : "Normalized Balance Profile",
            data: norm,
            backgroundColor: fallRisk ? "#dc262633" : "#9333ea33",
            borderColor: fallRisk ? "#dc2626" : "#9333ea",
            pointBackgroundColor: fallRisk ? "#dc2626" : "#9333ea",
          }],
        },
        options: { responsive: true, maintainAspectRatio: false, animation: false, scales: { r: { min: 0, max: 100 } } },
      });
    }

    const gaugeCtx = document.getElementById("modal-chart-risk");
    if (gaugeCtx) {
      const risk = Math.max(0, Math.min(100, safeNum(riskScore, 0)));
      state.modalCharts.risk = new Chart(gaugeCtx, {
        type: "doughnut",
        data: {
          labels: ["Risk", "Remaining"],
          datasets: [{ data: [risk, 100 - risk], backgroundColor: [risk > 65 ? "#dc2626" : risk > 35 ? "#d97706" : "#16a34a", "#e2e8f0"], borderWidth: 0 }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "70%",
          animation: false,
          plugins: {
            title: { display: true, text: fallRisk ? `Fall-Risk Gauge (${risk.toFixed(1)})` : `Risk Gauge (${risk.toFixed(1)})` },
            legend: { display: false },
          },
        },
      });
    }
  }

  function renderMetricTiles(metricsSummary) {
    const entries = Object.entries(metricsSummary || {});
    if (!entries.length) return '<p class="text-sm text-on-surface-variant">No metric summary available.</p>';
    const maxAvg = Math.max(...entries.map(([, s]) => Math.abs(safeNum(s?.avg, 0))), 1);
    return entries
      .map(([name, s]) => {
        const avg = safeNum(s?.avg, 0);
        const fill = Math.max(8, Math.round((Math.abs(avg) / maxAvg) * 100));
        return `
          <div class="ca-subtle p-3">
            <p class="text-xs font-semibold text-primary">${metricLabel(name)}</p>
            <p class="text-sm text-on-surface mt-1">Avg ${avg.toFixed(2)} · Min ${safeNum(s?.min, 0).toFixed(2)} · Max ${safeNum(s?.max, 0).toFixed(2)}</p>
            <div class="w-full h-1.5 rounded bg-surface-container-high mt-2 overflow-hidden">
              <div class="h-1.5 bg-secondary rounded" style="width:${fill}%"></div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderModalSummary(report, session, statusText) {
    const el = getModalEls();
    const payload = report.payload || {};
    const counts = payload.counts || {};
    const metrics = payload.metrics_summary || {};
    const synced = statusText.includes("Synced");
    const fallRisk = isFallRiskReport(report.report_type);
    const band = riskBand(session.risk_score);
    const keyIndicators = [
      ["asymmetry_index", "Asymmetry Index"],
      ["sway_path", "Sway Path"],
      ["cop_v", "CoP Velocity"],
      ["stability_score", "Stability Score"],
      ["symmetry_index", "Pressure Symmetry"],
    ]
      .filter(([key]) => Object.prototype.hasOwnProperty.call(metrics, key))
      .slice(0, 5)
      .map(([key, label]) => `${label}: ${safeNum(metrics[key]?.avg, 0).toFixed(2)}`);
    if (!el.summaryContent) return;

    el.summaryContent.innerHTML = `
      <div class="ca-subtle p-3 mb-3">
        <div class="flex flex-wrap items-center gap-3">
          <span class="ca-title-kicker">${fallRisk ? "Fall Risk Assessment" : "Clinical Summary"}</span>
          <span class="text-xs ${band.cls}">${fallRisk ? `Risk Band: ${band.label}` : `Risk Class: ${band.label}`}</span>
        </div>
        <p class="text-sm text-on-surface-variant mt-2">
          ${fallRisk
            ? "This report prioritizes fall propensity indicators and safety interpretation while preserving the full metric dataset."
            : "This report prioritizes overall balance interpretation while preserving the full metric dataset."}
        </p>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
        <div><span class="ca-title-kicker block">Patient</span><span class="text-on-surface font-semibold">${patientName(session.patient_id)}</span></div>
        <div><span class="ca-title-kicker block">Session Date</span><span class="text-on-surface">${fmtDateFromUs(session.started_at_us)}</span></div>
        <div><span class="ca-title-kicker block">Assessment</span><span class="text-on-surface">${prettyAssessment(session.source)}</span></div>
        <div><span class="ca-title-kicker block">Risk</span><span class="text-on-surface">${riskText(session.risk_label, session.risk_score)}</span></div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <div class="ca-subtle p-3"><span class="ca-title-kicker block mb-1">Report Status</span><span class="${statusClass(statusText)}">${statusText}</span></div>
        <div class="ca-subtle p-3"><span class="ca-title-kicker block mb-1">Created</span><span class="text-on-surface">${fmtDateTimeIso(report.generated_at)}</span></div>
        <div class="ca-subtle p-3"><span class="ca-title-kicker block mb-1">Counts</span><span class="text-on-surface">Frames ${counts.raw_frames ?? "-"} · Metrics ${counts.computed_metrics ?? "-"}</span></div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mb-4">
        ${renderMetricTiles(metrics)}
      </div>
      <div class="ca-subtle p-3 mb-4">
        <span class="ca-title-kicker block mb-1">${fallRisk ? "Key Fall Indicators" : "Key Clinical Indicators"}</span>
        <ul class="text-sm text-on-surface-variant list-disc pl-4">
          ${(keyIndicators.length ? keyIndicators : ["No indicator metrics available"]).map((line) => `<li>${line}</li>`).join("")}
        </ul>
      </div>
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
        <div class="ca-chart-surface xl:col-span-2">
          <p class="text-sm font-semibold text-primary mb-2">${fallRisk ? "Fall-Risk Metric Panels" : "Clinical Metric Panels"}</p>
          <div id="modal-chart-metric-grid" class="grid grid-cols-1 lg:grid-cols-2 gap-3"></div>
        </div>
        <div class="ca-chart-surface h-64"><canvas id="modal-chart-summary"></canvas></div>
        <div class="ca-chart-surface h-64"><canvas id="modal-chart-cop"></canvas></div>
        <div class="ca-chart-surface h-64"><canvas id="modal-chart-radar"></canvas></div>
        <div class="ca-chart-surface h-64 xl:col-span-2"><canvas id="modal-chart-risk"></canvas></div>
      </div>
      <div class="mb-4">
        <span class="ca-title-kicker block mb-1">Clinician Note</span>
        <p class="text-sm text-on-surface-variant">${report.clinician_notes || "None"}</p>
      </div>
      <div>
        <span class="ca-title-kicker block mb-1">Status Timeline</span>
        <ul class="text-sm text-on-surface-variant list-disc pl-4">
          <li>Generated at ${fmtDateTimeIso(report.generated_at)}</li>
          <li>${synced ? "Synced to EMR" : "Pending EMR sync"}</li>
          <li>${fallRisk ? "Fall-risk interpretation applied to same full metric dataset" : "Clinical interpretation applied to same full metric dataset"}</li>
        </ul>
      </div>
    `;
  }

  function setModalPdf(report) {
    const el = getModalEls();
    if (!el.pdfFrame || !el.pdfLink) return;
    const pdfUrl = `/api/reports/${report.report_id}/download/`;
    if (el.pdfFallback) el.pdfFallback.classList.add("hidden");
    el.pdfLink.href = pdfUrl;
    el.pdfFrame.onerror = function () {
      el.pdfFallback?.classList.remove("hidden");
    };
    el.pdfFrame.src = pdfUrl;
  }

  async function openPreviewModal(reportId, triggerEl) {
    state.modalLastTrigger = triggerEl || null;
    openModalShell();
    setModalTab("summary");
    setModalState("Loading report details...", false);
    const el = getModalEls();
    if (el.summaryContent) el.summaryContent.textContent = "Loading report details...";
    if (el.pdfFrame) el.pdfFrame.src = "about:blank";
    destroyModalCharts();

    try {
      const detail = await window.WBSUI.api(`/api/reports/${reportId}/`);
      state.modalReport = detail;
      const session = resolvedSessionContext(detail);
      const statusText = reportStatus(detail);
      setModalMeta(detail, session, statusText);
      renderModalSummary(detail, session, statusText);
      setModalPdf(detail);
      setModalState("Loaded", false);
      const series = await fetchSessionSeries(detail);
      renderModalCharts(
        detail.payload?.metrics_summary || {},
        series,
        safeNum(session.risk_score, 0),
        detail.report_type,
      );
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
      const series = await fetchSessionSeries(refreshed);
      renderModalCharts(
        refreshed.payload?.metrics_summary || {},
        series,
        safeNum(session.risk_score, 0),
        refreshed.report_type,
      );
      setModalState("Synced to EMR", false);
    } catch (err) {
      setModalState(`Sync failed: ${err.message}`, true);
    }
  }

  function bindPreviewButtons() {
    document.querySelectorAll(".report-view-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const reportId = Number(btn.dataset.reportId);
        if (!reportId) return;
        openPreviewModal(reportId, btn);
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
                <td><button class="report-view-btn ca-btn-secondary !py-2 !px-3 text-sm" data-report-id="${r.report_id}">View</button></td>
              </tr>
            `;
          })
          .join("");
      }
      bindPreviewButtons();
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
      const metricName = encodeURIComponent(fd.get("metric_name") || DEFAULT_METRICS.join(","));
      try {
        const metrics = await window.WBSUI.api(`/api/sessions/${state.selectedSessionId}/metrics/?metric_name=${metricName}&limit=500`);
        downloadJson(`session_${state.selectedSessionId}_metrics.json`, metrics);
        setMsg("json-msg", `Downloaded JSON metrics for session #${state.selectedSessionId}.`, false);
      } catch (err) {
        const mock = { session_id: state.selectedSessionId, count: 0, metric_names: [], series: {}, detail: err.message, mock_seed: true };
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
