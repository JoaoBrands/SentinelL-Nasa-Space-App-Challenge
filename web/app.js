let ws = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
let hasConnectedOnce = false;
const MAX_RECONNECT_DELAY_MS = 10000;
const PROTOCOL_ACK_TIMEOUT_MS = 5000;
const el = (id) => document.getElementById(id);

let currentStatuses = {};
let chartInitialized = false;
let chartData = { labels: [], localCo2: [], moduleCo2: [], hr: [] };
let isBlackout = false;
let dominoAcknowledged = false;
let protocolState = createProtocolState();
let latestProtocolContext = null;
let protocolTimeouts = {};
let sourceById = {};
let provenanceRendered = false;

function createProtocolState() {
  return {
    active: false,
    airflowChecked: false,
    airflowPending: false,
    reassessmentRecorded: false,
    reassessmentPending: false,
    reassessment: null,
    message: "",
  };
}

function resetProtocolState() {
  Object.values(protocolTimeouts).forEach(clearTimeout);
  protocolTimeouts = {};
  protocolState = createProtocolState();
}

function initChart() {
  chartInitialized = true;
  window.addEventListener("resize", drawVitalsChart);
  drawVitalsChart();
}

function drawVitalsChart() {
  const canvas = el("vitalsChart");
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  ctx.font = "10px sans-serif";

  const colors = { localCo2: "#d4a020", moduleCo2: "#54a7c7", hr: "#3a7aca" };
  const plot = { left: 42, right: rect.width - 38, top: 52, bottom: rect.height - 25 };
  const plotHeight = Math.max(1, plot.bottom - plot.top);
  const co2Values = [...chartData.localCo2, ...chartData.moduleCo2].filter(Number.isFinite);
  const hrValues = chartData.hr.filter(Number.isFinite);
  const co2Max = Math.max(1, Math.ceil((Math.max(0, ...co2Values) + 0.25) * 2) / 2);
  const hrMin = Math.max(0, Math.floor((Math.min(40, ...hrValues) - 10) / 10) * 10);
  const hrMax = Math.max(hrMin + 20, Math.ceil((Math.max(140, ...hrValues) + 10) / 10) * 10);
  const x = (index) => plot.left + (chartData.labels.length <= 1
    ? 0
    : index * (plot.right - plot.left) / (chartData.labels.length - 1));
  const y = (value, min, max) => plot.bottom - ((value - min) / (max - min)) * plotHeight;

  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillStyle = colors.localCo2;
  ctx.fillRect(plot.left, 11, 14, 2);
  ctx.fillStyle = "#e0e0e0";
  ctx.fillText("Local CO₂ · synthetic", plot.left + 21, 12);
  ctx.fillStyle = colors.moduleCo2;
  ctx.fillRect(plot.left, 26, 14, 2);
  ctx.fillStyle = "#e0e0e0";
  ctx.fillText("Module CO₂ · synthetic", plot.left + 21, 27);
  ctx.fillStyle = colors.hr;
  ctx.fillRect(plot.left, 41, 14, 2);
  ctx.fillStyle = "#e0e0e0";
  ctx.fillText("Heart rate · synthetic", plot.left + 21, 42);

  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#9aa6b6";
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = co2Max * tick / 4;
    const tickY = plot.bottom - plotHeight * tick / 4;
    ctx.strokeStyle = "#1a2332";
    ctx.beginPath();
    ctx.moveTo(plot.left, tickY);
    ctx.lineTo(plot.right, tickY);
    ctx.stroke();
    ctx.fillText(value.toFixed(value % 1 === 0 ? 0 : 1), plot.left - 6, tickY);
  }

  ctx.textAlign = "left";
  ctx.fillStyle = colors.hr;
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = hrMin + (hrMax - hrMin) * tick / 4;
    const tickY = plot.bottom - plotHeight * tick / 4;
    ctx.fillText(String(Math.round(value)), plot.right + 5, tickY);
  }

  ctx.save();
  ctx.font = "9px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#b7c3d1";
  ctx.translate(9, plot.top + plotHeight / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("CO₂ (mmHg)", 0, 0);
  ctx.restore();

  ctx.save();
  ctx.font = "9px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = colors.hr;
  ctx.translate(rect.width - 8, plot.top + plotHeight / 2);
  ctx.rotate(Math.PI / 2);
  ctx.fillText("Heart rate (bpm)", 0, 0);
  ctx.restore();

  function drawSeries(values, min, max, color, dash = []) {
    if (!values.length) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dash);
    ctx.beginPath();
    let hasPoint = false;
    values.forEach((value, index) => {
      if (!Number.isFinite(value)) {
        hasPoint = false;
        return;
      }
      const pointX = x(index);
      const pointY = y(value, min, max);
      if (hasPoint) ctx.lineTo(pointX, pointY);
      else ctx.moveTo(pointX, pointY);
      hasPoint = true;
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  drawSeries(chartData.localCo2, 0, co2Max, colors.localCo2);
  drawSeries(chartData.moduleCo2, 0, co2Max, colors.moduleCo2, [5, 3]);
  drawSeries(chartData.hr, hrMin, hrMax, colors.hr);

  if (chartData.labels.length) {
    const labelCount = Math.min(5, chartData.labels.length);
    ctx.fillStyle = "#6a7a90";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let tick = 0; tick < labelCount; tick += 1) {
      const index = Math.round(tick * (chartData.labels.length - 1) / Math.max(1, labelCount - 1));
      ctx.fillText(chartData.labels[index], x(index), plot.bottom + 5);
    }
  }
}

function setBackendStatus(label, color, pulse = false) {
  const badge = el("link-state");
  badge.textContent = label;
  badge.style.background = color;
  badge.style.animation = pulse ? "pulse 1s infinite" : "none";
}

function resetForNewBackendSession() {
  currentStatuses = {};
  resetProtocolState();
  latestProtocolContext = null;
  chartData = { labels: [], localCo2: [], moduleCo2: [], hr: [] };
  if (chartInitialized) drawVitalsChart();

  isBlackout = false;
  dominoAcknowledged = false;
  el("sim-time").textContent = "0.0";
  el("btn-cut").disabled = false;
  el("btn-restore").disabled = true;
  el("btn-action").disabled = true;
  el("btn-action").style.animation = "none";
  el("btn-module-ventilation").hidden = true;
  el("btn-module-ventilation").disabled = false;
  el("fan-recovery").hidden = true;
  el("module-recovery").hidden = true;
  el("blackout-overlay").classList.remove("active");
  el("blackout-message").textContent = "Onboard monitoring continues; events are stored locally.";
  el("telemetry-receipt").hidden = true;
  el("telemetry-receipt").replaceChildren();
}

function sendAction(message) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    logEvent("Command not sent: the backend is not connected.");
    return false;
  }
  ws.send(JSON.stringify(message));
  return true;
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  ws = socket;

  socket.onopen = () => {
    const isReconnect = hasConnectedOnce;
    hasConnectedOnce = true;
    reconnectAttempts = 0;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (isReconnect) {
      resetForNewBackendSession();
      logEvent("Backend reconnected. A new simulation session has started; the previous session buffer was not recovered.");
    } else {
      logEvent("Connected to the Sentinel backend");
    }
    setBackendStatus("CONNECTED", "#1a4a2a");
    if (!chartInitialized) initChart();
  };

  socket.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "tick") renderTick(msg, true);
    if (msg.type === "onboard_tick") renderTick(msg, false);
    if (msg.type === "link_status") renderLinkStatus(msg);
    if (msg.type === "telemetry_packet") renderTelemetryReceipt(msg);
    if (msg.type === "link_error") logEvent("Could not authenticate the packet; the buffer was kept.");
    if (msg.type === "protocol_ack") handleProtocolAck(msg);
    if (msg.type === "protocol_error") handleProtocolError(msg);
  };

  socket.onerror = () => {
    if (ws === socket) {
      setBackendStatus("CONNECTION ERROR", "#7a1a1a", true);
    }
  };

  socket.onclose = () => {
    if (ws !== socket) return;
    const delay = Math.min(1000 * (2 ** reconnectAttempts), MAX_RECONNECT_DELAY_MS);
    reconnectAttempts += 1;
    setBackendStatus("RECONNECTING", "#7a4a1a", true);
    logEvent(`Backend connection lost. The session ended; reconnecting in ${Math.round(delay / 1000)} s.`);
    reconnectTimer = setTimeout(connectWebSocket, delay);
  };
}

connectWebSocket();

// --- Button events ---
document.querySelectorAll("[data-scenario]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const id = btn.dataset.scenario;
    const action = id === "none"
      ? { action: "stop" }
      : { action: "start_scenario", id };
    if (!sendAction(action)) return;

    dominoAcknowledged = false;
    resetProtocolState();
    latestProtocolContext = null;
    renderProtocol(null, null);
    chartData = { labels: [], localCo2: [], moduleCo2: [], hr: [] };
    if (chartInitialized) drawVitalsChart();

    if (id === "none") {
      if (!isBlackout) logEvent("Simulation stopped — state reset");
      currentStatuses = {};
      if (!isBlackout) {
        el("btn-cut").disabled = false;
        el("btn-restore").disabled = true;
        el("link-state").textContent = "CONNECTED";
        el("link-state").style.background = "#1a4a2a";
        el("link-state").style.animation = "none";
      }
    } else {
      if (!isBlackout) logEvent("Scenario started: CO2 failure");
      currentStatuses = {};
    }
  });
});

el("btn-action").addEventListener("click", () => {
  if (!sendAction({ action: "activate_fan" })) return;
  protocolState.active = true;
  refreshProtocol();
  if (!isBlackout) logEvent("Action sent: local fan");
});

el("protocol-container").addEventListener("click", (event) => {
  const target = event.target instanceof Element
    ? event.target.closest("[data-protocol-action]")
    : null;
  if (!target) return;

  const action = target.dataset.protocolAction;
  if (action === "activate-fan") {
    if (!sendAction({ action: "activate_fan" })) return;
    protocolState.active = true;
    refreshProtocol();
    if (!isBlackout) logEvent("Action sent: local fan from crew protocol");
  } else if (action === "airflow-check" || action === "reassessment") {
    const step = action === "airflow-check" ? "airflow_check" : "reassessment";
    if (!sendAction({ action: "protocol_step", step })) return;
    beginProtocolRequest(step);
    refreshProtocol();
  }
});

function beginProtocolRequest(step) {
  const pendingKey = step === "airflow_check" ? "airflowPending" : "reassessmentPending";
  if (protocolTimeouts[step]) clearTimeout(protocolTimeouts[step]);
  protocolState[pendingKey] = true;
  protocolTimeouts[step] = setTimeout(() => {
    delete protocolTimeouts[step];
    if (!protocolState[pendingKey]) return;
    protocolState[pendingKey] = false;
    protocolState.message =
      "The backend did not confirm this step. Check the connection; after code updates, restart Sentinel and start a new scenario.";
    refreshProtocol();
  }, PROTOCOL_ACK_TIMEOUT_MS);
}

function clearProtocolRequest(step) {
  if (protocolTimeouts[step]) {
    clearTimeout(protocolTimeouts[step]);
    delete protocolTimeouts[step];
  }
  if (step === "airflow_check") protocolState.airflowPending = false;
  if (step === "reassessment") protocolState.reassessmentPending = false;
}

function handleProtocolAck(message) {
  protocolState.message = "";
  clearProtocolRequest(message.step);
  if (message.step === "airflow_check") {
    protocolState.airflowChecked = true;
    if (!isBlackout) logEvent(`Crew confirmed airflow-path check at T+${message.sim_t} min.`);
  } else if (message.step === "reassessment") {
    protocolState.reassessmentRecorded = true;
    protocolState.reassessment = {
      sim_t: message.sim_t,
      local_co2_mmhg: message.local_co2_mmhg,
      symptoms: message.symptoms || [],
    };
    if (!isBlackout) logEvent(`Crew recorded protocol reassessment at T+${message.sim_t} min.`);
  }
  refreshProtocol();
}

function handleProtocolError(message) {
  clearProtocolRequest(message.step);
  protocolState.message = message.message || "Protocol step could not be recorded.";
  if (!isBlackout) logEvent(`Protocol step not recorded: ${protocolState.message}`);
  refreshProtocol();
}

function refreshProtocol() {
  if (latestProtocolContext) {
    renderProtocol(latestProtocolContext.anaData, latestProtocolContext.state);
  }
}

el("btn-module-ventilation").addEventListener("click", () => {
  if (!sendAction({ action: "activate_module_ventilation" })) return;
  el("btn-module-ventilation").disabled = true;
  if (!isBlackout) logEvent("Action sent: module ventilation (illustrative simulation)");
});

el("btn-cut").addEventListener("click", () => {
  if (!sendAction({ action: "cut_comms" })) return;
  isBlackout = true;
  el("btn-cut").disabled = true;
  el("blackout-overlay").classList.add("active");
  el("blackout-message").textContent = "Waiting for link status confirmation...";
});

el("btn-restore").addEventListener("click", () => {
  if (!sendAction({ action: "restore_comms" })) return;
  el("btn-restore").disabled = true;
  el("blackout-message").textContent = "Restoring the link and authenticating stored telemetry...";
});

// --- Screen rendering ---
function renderTick(msg, earthConnected) {
  if (msg.provenance) {
    sourceById = Object.fromEntries(msg.provenance.sources.map(source => [source.id, source]));
    if (!provenanceRendered) {
      renderDataProvenance(msg.provenance);
      provenanceRendered = true;
    }
  }

  el("sim-time").textContent = msg.state.t.toFixed(1);
  renderCO2Window(msg.evaluation.module_metrics);
  renderFanRecovery(msg.state.interventions, msg.state.metrics);
  renderModuleVentilation(msg.evaluation.module_alerts, msg.state.interventions, msg.state.metrics);

  if (msg.state.t > 0) {
    chartData.labels.push("T+" + Math.round(msg.state.t));
    chartData.localCo2.push(msg.state.metrics.ana_local_co2);
    chartData.moduleCo2.push(msg.state.metrics.module2_co2);
    chartData.hr.push(msg.state.metrics.ana_hr);
    if (chartData.labels.length > 40) {
      chartData.labels.shift();
      chartData.localCo2.shift();
      chartData.moduleCo2.shift();
      chartData.hr.shift();
    }
    if (chartInitialized) drawVitalsChart();
  }

  const grid = el("crew-grid");
  grid.innerHTML = "";
  const evalCrew = msg.evaluation.crew;

  for (const [cid, data] of Object.entries(evalCrew)) {
    const profile = msg.profiles_summary[cid] || {};
    const status = data.status;
    const card = document.createElement("div");
    card.className = `crew-card status-${status.toLowerCase()}`;
    card.innerHTML = `
      <div class="crew-name">${profile.name || cid}</div>
      <div class="crew-status">${statusIcon(status)} ${statusLabel(status)}</div>
      <div class="crew-conditions">${(profile.conditions || []).map(conditionLabel).join(", ") || "—"}</div>
    `;
    if (cid === "ana") {
      const vitalSignals = document.createElement("div");
      vitalSignals.className = "crew-signals";
      for (const [key, label] of [["heart_rate", "Heart rate"], ["spo2", "SpO₂"]]) {
        const signal = data.vital_signals?.[key];
        if (!signal) continue;

        const line = document.createElement("div");
        line.className = "crew-signal";
        if (signal.status === "SYNTHETIC" && Number.isFinite(signal.value)) {
          const value = Number.isInteger(signal.value) ? String(signal.value) : signal.value.toFixed(1);
          const unitSuffix = signal.unit === "%" ? "%" : ` ${signal.unit}`;
          line.textContent = `${label}: ${value}${unitSuffix} · synthetic scenario input`;
        } else {
          line.textContent = `${label}: ${signal.status === "INVALID" ? "INVALID INPUT" : "NOT MONITORED"}`;
        }
        vitalSignals.appendChild(line);
      }
      card.appendChild(vitalSignals);
    }
    grid.appendChild(card);

    if (earthConnected && currentStatuses[cid] !== status) {
      currentStatuses[cid] = status;
      logEvent(`${profile.name || cid}: ${statusLabel(status)}`);
    }
  }

  const anaData = evalCrew["ana"];
  const actionBtn = el("btn-action");
  const fanActive = Boolean(msg.state.interventions?.bed_fan?.active);
  if (anaData && ["OBSERVE", "WARNING", "CRITICAL"].includes(anaData.status) && !fanActive) {
    actionBtn.disabled = false;
    actionBtn.style.animation = "pulse 1s infinite";
  } else {
    actionBtn.disabled = true;
    actionBtn.style.animation = "none";
  }

  const alertBox = el("alerts");
  alertBox.innerHTML = "";
  const allAlerts = [];
  for (const [cid, data] of Object.entries(evalCrew)) {
    for (const a of data.alerts) allAlerts.push({ crew: cid, ...a });
  }
  for (const ma of msg.evaluation.module_alerts) allAlerts.push({ crew: "module", ...ma });

  if (allAlerts.length === 0) {
    alertBox.innerHTML = '<div class="no-alerts">No active alerts</div>';
  } else {
    for (const a of allAlerts) {
      alertBox.appendChild(renderAlert(a));
    }
  }

  renderCascade(anaData, msg.state.t);
  latestProtocolContext = { anaData, state: msg.state };
  renderProtocol(anaData, msg.state);
  renderAI(anaData);
  renderDomino(anaData);

  if (earthConnected && msg.state.finished) logEvent("Scenario complete");
}

function statusLabel(status) {
  return {
    NORMAL: "NORMAL",
    OBSERVE: "OBSERVE",
    WARNING: "WARNING",
    CRITICAL: "CRITICAL",
    NOT_MONITORED: "NOT MONITORED"
  }[status] || status;
}

function conditionLabel(condition) {
  return {
    migraine: "migraine",
    knee_ligament_tear: "knee ligament injury",
    renal_stone_history: "history of renal stones",
    hypertension_controlled: "controlled hypertension"
  }[condition] || condition;
}

function crewLabel(crew) {
  return crew === "module" ? "Module" : crew;
}

function metricLabel(metric) {
  return {
    module2_co2: "Module CO₂",
    module2_ventilation: "Module ventilation",
    ana_local_co2: "Ana's local CO₂",
    ana_local_ventilation: "Ana's local ventilation",
    ana_hr: "Ana's heart rate",
    ana_spo2: "Ana's SpO₂"
  }[metric] || metric;
}

function actionLabel(action) {
  return {
    activate_bed_fan: "local fan activated",
    activate_module_ventilation: "module ventilation activated",
    protocol_airflow_check: "airflow-path check confirmed by crew",
    protocol_reassessment: "crew reassessment recorded"
  }[action] || action;
}

function renderCO2Window(metrics = {}) {
  const value = el("co2-window-value");
  const detail = el("co2-window-detail");
  const average = metrics.module2_co2_1h_avg_mmhg;
  const latest = metrics.module2_co2_sample_mmhg;
  const coverage = metrics.module2_co2_coverage_minutes || 0;
  const required = metrics.module2_co2_window_minutes || 60;

  if (average === null || average === undefined) {
    value.textContent = `Collecting hourly window · ${coverage.toFixed(0)}/${required} min`;
    detail.textContent = latest === null || latest === undefined
      ? "No module CO₂ reading in this sample."
      : `Latest synthetic reading: ${latest.toFixed(2)} mmHg. No hourly alert before full coverage.`;
    return;
  }

  value.textContent = `${average.toFixed(2)} mmHg ${average > 3 ? "· ABOVE REFERENCE" : "· WITHIN REFERENCE"}`;
  detail.textContent = `60-minute weighted average. Latest reading: ${latest.toFixed(2)} mmHg.`;
}

function renderFanRecovery(interventions = {}, metrics = {}) {
  const fan = interventions.bed_fan;
  const panel = el("fan-recovery");
  if (!fan || !fan.active) {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  el("fan-recovery-progress").value = fan.progress_percent;
  const localCO2 = metrics.ana_local_co2;
  const localCO2Text = typeof localCO2 === "number" ? `${localCO2.toFixed(2)} mmHg` : "unavailable";
  el("fan-recovery-detail").textContent =
    `${fan.elapsed_minutes.toFixed(1)}/${fan.washout_duration_minutes.toFixed(1)} simulated min · local CO₂ ${localCO2Text}. Illustrative linear ramp; module CO₂ does not change.`;
}

function renderModuleVentilation(moduleAlerts = [], interventions = {}, metrics = {}) {
  const alertActive = moduleAlerts.some(alert => alert.rule_id === "module_co2_limit");
  const intervention = interventions.module_ventilation;
  const button = el("btn-module-ventilation");
  const panel = el("module-recovery");

  button.hidden = !alertActive || Boolean(intervention && intervention.active);
  button.disabled = false;
  panel.hidden = !intervention || !intervention.active;

  if (intervention && intervention.active) {
    el("module-recovery-progress").value = intervention.progress_percent;
    el("module-recovery-title").textContent = intervention.progress_percent >= 100
      ? "MODULE VENTILATION RESPONSE COMPLETE"
      : "MODULE VENTILATION ACTIVE";
    const moduleCO2 = metrics.module2_co2;
    const moduleCO2Text = typeof moduleCO2 === "number" ? `${moduleCO2.toFixed(2)} mmHg` : "unavailable";
    el("module-recovery-detail").textContent =
      `${intervention.elapsed_minutes.toFixed(1)}/${intervention.response_duration_minutes.toFixed(1)} simulated min · module CO₂ ${moduleCO2Text} · hourly alert ${alertActive ? "still active" : "resolved"}. The rolling average determines resolution.`;
  }
}

function renderLinkStatus(msg) {
  const linkState = el("link-state");
  if (msg.status === "blackout") {
    isBlackout = true;
    linkState.textContent = "NO SIGNAL";
    linkState.style.background = "#7a1a1a";
    linkState.style.animation = "pulse 1s infinite";
    el("btn-cut").disabled = true;
    el("btn-restore").disabled = false;
    el("blackout-message").textContent = "Onboard monitoring continues; events are stored locally.";
    el("blackout-overlay").classList.add("active");
    logEvent("Communication interrupted. Earth telemetry paused; onboard buffer active.");
  }
}

function renderTelemetryReceipt(message) {
  isBlackout = false;
  const linkState = el("link-state");
  linkState.textContent = "CONNECTED";
  linkState.style.background = "#1a4a2a";
  linkState.style.animation = "none";
  el("btn-cut").disabled = false;
  el("btn-restore").disabled = true;
  el("blackout-overlay").classList.remove("active");

  const receipt = el("telemetry-receipt");
  const packet = message.packet;
  const summary = message.receipt;
  receipt.hidden = false;
  receipt.replaceChildren();

  const title = document.createElement("strong");
  title.textContent = "STORED TELEMETRY RECEIVED";
  receipt.appendChild(title);

  const metadata = document.createElement("p");
  metadata.textContent = `${packet.packet_id} | ${message.record_count} records | ${packet.algorithm} + ${packet.compression} | encrypted payload: ${packet.encrypted_payload_bytes} bytes`;
  receipt.appendChild(metadata);

  const compression = document.createElement("p");
  compression.textContent = `${packet.uncompressed_bytes} bytes before compression; ${packet.compressed_bytes} bytes after. Key: ${message.key_mode === "ephemeral_demo" ? "ephemeral demo" : "configured"}.`;
  receipt.appendChild(compression);

  const integrity = document.createElement("p");
  integrity.className = message.receiver_verified ? "receipt-valid" : "receipt-invalid";
  integrity.textContent = message.receiver_verified
    ? `AES-GCM authentication verified. ${message.receiver_note === "Demo receiver runs in this same backend process; this validates the packet roundtrip, not a deployed spacecraft-to-Earth link." ? "The demo receiver runs in the same backend process; this validates the packet roundtrip, not an operational spacecraft-to-Earth link." : message.receiver_note}`
    : "Packet authentication failed; do not use this summary.";
  receipt.appendChild(integrity);

  const interval = document.createElement("p");
  interval.textContent = `Stored interval: T+${summary.started_t} to T+${summary.ended_t} min; ${summary.ticks} onboard updates.`;
  receipt.appendChild(interval);

  const co2Hourly = summary.co2_hourly;
  if (co2Hourly) {
    const hourlyLine = document.createElement("p");
    const averageText = co2Hourly.average_mmhg === null
      ? "unavailable"
      : `${Number(co2Hourly.average_mmhg).toFixed(3)} mmHg`;
    const sampleText = co2Hourly.latest_sample_mmhg === null
      ? "unavailable"
      : `${Number(co2Hourly.latest_sample_mmhg).toFixed(2)} mmHg`;
    const alertText = co2Hourly.alert_active ? "hourly alert active" : "no hourly alert";
    hourlyLine.textContent = `Module CO₂: 1-hour average ${averageText}; coverage ${co2Hourly.coverage_minutes}/${co2Hourly.window_minutes} min; latest reading ${sampleText}; ${alertText}.`;
    hourlyLine.className = co2Hourly.alert_active ? "receipt-warning" : "";
    receipt.appendChild(hourlyLine);
  }

  for (const [metric, values] of Object.entries(summary.metrics || {})) {
    const metricLine = document.createElement("p");
    metricLine.textContent = `${metricLabel(metric)}: min. ${values.min}, max. ${values.max}, last ${values.last}`;
    receipt.appendChild(metricLine);
  }

  for (const alert of summary.alerts || []) {
    const alertLine = document.createElement("p");
    alertLine.textContent = `${crewLabel(alert.crew)}: ${statusLabel(alert.status)} ${alert.rule_id} (T+${alert.first_seen_t} to T+${alert.last_seen_t})`;
    receipt.appendChild(alertLine);
  }

  for (const change of summary.crew_status_changes || []) {
    const statusLine = document.createElement("p");
    statusLine.textContent = `${crewLabel(change.crew)}: state ${statusLabel(change.status)} at T+${change.t} min`;
    receipt.appendChild(statusLine);
  }

  for (const action of summary.actions || []) {
    if (action.action === "comms_lost") continue;
    const actionLine = document.createElement("p");
    if (action.action === "protocol_reassessment" && action.details) {
      const localCO2 = Number.isFinite(action.details.local_co2_mmhg)
        ? `${action.details.local_co2_mmhg.toFixed(2)} mmHg`
        : "unavailable";
      const symptoms = summarizeScenarioSymptoms(action.details.symptoms || []);
      actionLine.textContent =
        `Crew reassessment at T+${action.t} min — synthetic local CO₂ ${localCO2}; ` +
        `scenario symptom inputs: ${symptoms}.`;
    } else {
      actionLine.textContent = `Action ${actionLabel(action.action)} at T+${action.t} min`;
    }
    receipt.appendChild(actionLine);
  }

  logEvent(`Blackout packet received: ${message.record_count} records, ${packet.encrypted_payload_bytes} encrypted bytes.`);
  logEvent(message.receiver_verified ? "AES-GCM authentication verified by the demo receiver." : "Telemetry packet authentication failed.");
}

function renderAlert(alert) {
  const container = document.createElement("div");
  container.className = `alert alert-${(alert.status || "INFO").toLowerCase()}`;

  const message = document.createElement("div");
  message.textContent = `[${statusLabel(alert.status)}] ${alert.text}`;
  container.appendChild(message);

  if (alert.vital_context) {
    const context = alert.vital_context;
    const contextLine = document.createElement("div");
    contextLine.className = "alert-measurements";
    const value = Number.isFinite(context.value)
      ? Number(context.value.toFixed(1)).toString()
      : "unavailable";
    const threshold = Number.isFinite(context.threshold)
      ? Number(context.threshold.toFixed(1)).toString()
      : "unavailable";
    const unitSuffix = context.unit === "%" ? "%" : ` ${context.unit}`;
    contextLine.textContent =
      `Synthetic scenario input — ${context.metric}: ${value}${unitSuffix}. ` +
      `Prototype trigger: ${context.metric} ${context.operator} ${threshold}${unitSuffix}.\n` +
      (context.interpretation_note || "Illustrative prototype rule; not a clinical assessment.");
    container.appendChild(contextLine);
  }

  if (alert.scenario_context) {
    const context = alert.scenario_context;
    const contextLine = document.createElement("div");
    contextLine.className = "alert-measurements";
    const localCO2 = Number.isFinite(context.ana_local_co2_mmhg)
      ? `${context.ana_local_co2_mmhg.toFixed(2)} mmHg`
      : "unavailable";
    const moduleCO2 = Number.isFinite(context.module2_co2_sample_mmhg)
      ? `${context.module2_co2_sample_mmhg.toFixed(2)} mmHg`
      : "unavailable";
    const threshold = Number.isFinite(context.individual_threshold_mmhg)
      ? `${context.individual_threshold_mmhg.toFixed(2)} mmHg`
      : "unavailable";
    const supportingSignals = Array.isArray(context.supporting_signals)
      ? context.supporting_signals.join("; ")
      : "";
    contextLine.textContent = [
      `Synthetic readings — local CO₂: ${localCO2}; module sample: ${moduleCO2} (not the 1-hour average).`,
      `Illustrative individual threshold: ${threshold}.`,
      supportingSignals ? `Supporting inputs: ${supportingSignals}.` : "",
      context.interpretation_note || "",
    ].filter(Boolean).join("\n");
    container.appendChild(contextLine);
  }

  const evidence = document.createElement("div");
  evidence.className = "alert-evidence";

  const classification = document.createElement("strong");
  classification.textContent = alert.evidence_classification || "Illustrative prototype rule";
  evidence.appendChild(classification);

  const note = document.createElement("div");
  note.textContent = alert.evidence_note || "No NASA source is linked to this rule.";
  evidence.appendChild(note);

  const sources = (alert.source_ids || []).map(id => sourceById[id]).filter(Boolean);
  if (sources.length) {
    const links = document.createElement("div");
    links.className = "alert-source-links";
    for (const source of sources) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.id;
      links.appendChild(link);
    }
    evidence.appendChild(links);
  }

  container.appendChild(evidence);
  return container;
}

function renderDataProvenance(provenance) {
  const container = el("provenance-content");
  container.replaceChildren();

  const policy = document.createElement("p");
  policy.className = "provenance-policy";
  policy.textContent = provenance.policy;
  container.appendChild(policy);

  if (provenance.data_flow) {
    const heading = document.createElement("h3");
    heading.className = "provenance-flow-title";
    heading.textContent = provenance.data_flow.title;
    container.appendChild(heading);

    const flow = document.createElement("div");
    flow.className = "provenance-flow";
    for (const step of provenance.data_flow.steps) {
      const item = document.createElement("div");
      item.className = "provenance-step";

      const label = document.createElement("strong");
      label.textContent = step.label;
      const description = document.createElement("p");
      description.textContent = step.description;
      item.append(label, description);

      const sources = (step.source_ids || [])
        .map(id => ({ id, source: sourceById[id] }))
        .filter(entry => entry.source);
      if (sources.length) {
        const links = document.createElement("div");
        links.className = "provenance-step-sources";
        for (const { id, source } of sources) {
          const link = document.createElement("a");
          link.href = source.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = id;
          links.appendChild(link);
        }
        item.appendChild(links);
      }
      flow.appendChild(item);
    }
    container.appendChild(flow);
  }

  for (const layer of provenance.data_layers) {
    const item = document.createElement("div");
    item.className = "provenance-layer";
    const label = document.createElement("strong");
    label.textContent = layer.label;
    const description = document.createElement("span");
    description.textContent = layer.description;
    item.append(label, description);
    container.appendChild(item);
  }

  const scenario = document.createElement("p");
  scenario.className = "provenance-scenario";
  scenario.textContent = `${provenance.scenario_data.description} ${provenance.scenario_data.threshold_note}`;
  container.appendChild(scenario);

  for (const source of provenance.sources) {
    const item = document.createElement("div");
    item.className = "provenance-source";
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.title;
    const identifier = document.createElement("span");
    identifier.className = "provenance-id";
    identifier.textContent = `${source.id} · ${source.type}`;
    const summary = document.createElement("p");
    summary.textContent = source.supports;
    const limitation = document.createElement("p");
    limitation.className = "provenance-limitation";
    limitation.textContent = `Limitations: ${source.limitations}`;
    item.append(link, identifier, summary, limitation);
    container.appendChild(item);
  }
}

function renderAI(anaData) {
  const panel = el("ai-panel");
  const content = el("ai-content");
  const badge = el("ai-badge");

  if (!anaData || anaData.alerts.length === 0) {
    panel.style.display = "none";
    return;
  }

  const alert = anaData.alerts.find(a => a.ai_explanation);

  if (alert) {
    panel.style.display = "block";
    badge.textContent = alert.ai_source && (alert.ai_source.includes("AO VIVO") || alert.ai_source.includes("LIVE"))
      ? "LIVE AI"
      : "PRECOMPUTED";

    if (alert.ai_source && (alert.ai_source.includes("AO VIVO") || alert.ai_source.includes("LIVE"))) {
      badge.style.background = "#1a4a2a";
      badge.style.color = "#4ade80";
    } else {
      badge.style.background = "#2a2a2a";
      badge.style.color = "#a0a0a0";
    }

    const explanation = document.createElement("div");
    explanation.textContent = alert.ai_explanation;

    const action = document.createElement("div");
    action.className = "ai-action";
    action.textContent = `⚡ RECOMMENDATION: ${alert.ai_action}`;

    const sourceNote = document.createElement("div");
    sourceNote.className = "ai-source-note";
    sourceNote.textContent =
      "The AI text is explanatory only. The status is defined by deterministic rules; evidence is included with the alert.";

    content.replaceChildren(explanation, action, sourceNote);
  } else {
    panel.style.display = "none";
  }
}

function renderDomino(anaData) {
  const panel = el("domino-panel");
  if (!anaData || !anaData.domino || dominoAcknowledged) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "block";
  const d = anaData.domino;
  const content = el("domino-content");
  const message = document.createElement("p");
  message.textContent = d.message;

  const load = document.createElement("p");
  load.append("Illustrative workload: ", `${d.current_load}% → `);
  const newLoad = document.createElement("span");
  newLoad.className = "highlight";
  newLoad.textContent = `${d.new_load}%`;
  load.appendChild(newLoad);

  const note = document.createElement("p");
  note.textContent = d.warning;
  content.replaceChildren(message, load, note);
}

function renderCascade(anaData, currentT) {
  const container = el("cascade-container");
  if (!anaData || !anaData.cascade || anaData.cascade.length === 0) {
    container.innerHTML = '<div class="no-data">No active cascade</div>';
    return;
  }

  container.innerHTML = "";
  anaData.cascade.forEach(node => {
    const div = document.createElement("div");
    const isActive = currentT >= node.simulation_hour * 60;
    div.className = `cascade-node ${isActive ? 'active' : ''}`;
    const label = document.createElement("span");
    label.textContent = node.label;
    const time = document.createElement("span");
    time.textContent = `SIM T+${node.simulation_hour} h`;
    div.append(label, time);
    container.appendChild(div);
  });
}

function renderProtocol(anaData, state) {
  const container = el("protocol-container");
  const fan = state?.interventions?.bed_fan;
  const fanActive = Boolean(fan?.active);
  if (
    anaData && ["OBSERVE", "WARNING", "CRITICAL"].includes(anaData.status)
    || fanActive
  ) {
    protocolState.active = true;
  }
  if (!protocolState.active) {
    container.innerHTML = '<div class="no-data">No active protocol</div>';
    return;
  }

  const fanProgress = fanActive ? fan.progress_percent : 0;
  const fanDuration = fan?.washout_duration_minutes || 5;
  const fanComplete = fanActive && fanProgress >= 100;
  const localCO2 = state?.metrics?.ana_local_co2;
  const hasLocalCO2 = Number.isFinite(localCO2) && localCO2 >= 0;
  const scenarioSymptoms = summarizeScenarioSymptoms(state?.symptoms || []);
  container.replaceChildren();

  const note = document.createElement("p");
  note.className = "protocol-note";
  note.textContent =
    "Illustrative crew workflow. Confirmations are manual; they are not sensor readings or medical clearance.";
  container.appendChild(note);

  appendProtocolStep(container, {
    number: 1,
    title: "Activate the bedside fan",
    complete: fanActive,
    status: fanActive ? "ACTIVE" : "PENDING",
    detail: fanActive
      ? `${fan.elapsed_minutes.toFixed(1)}/${fanDuration.toFixed(1)} simulated min of the illustrative fan ramp.`
      : "Begins the illustrative local airflow response.",
    action: !fanActive
      ? { name: "activate-fan", label: "ACTIVATE FAN", disabled: false }
      : null,
  });

  appendProtocolStep(container, {
    number: 2,
    title: "Check the airflow path",
    complete: protocolState.airflowChecked,
    status: protocolState.airflowChecked
      ? "CREW CONFIRMED"
      : fanActive ? "AWAITING CREW" : "WAITING",
    detail: "Manual crew confirmation only; no airflow-obstruction sensor is connected.",
    action: !protocolState.airflowChecked
      ? {
          name: "airflow-check",
          label: protocolState.airflowPending ? "SENDING..." : "CONFIRM CHECK",
          disabled: !fanActive || protocolState.airflowPending,
        }
      : null,
  });

  let reassessmentDetail;
  if (protocolState.reassessmentRecorded && protocolState.reassessment) {
    const snapshot = protocolState.reassessment;
    const recordedCO2 = Number.isFinite(snapshot.local_co2_mmhg)
      ? `${snapshot.local_co2_mmhg.toFixed(2)} mmHg`
      : "unavailable";
    reassessmentDetail =
      `Recorded at T+${snapshot.sim_t} min · synthetic local CO₂ ${recordedCO2} · ` +
      `scenario symptom inputs: ${summarizeScenarioSymptoms(snapshot.symptoms)}.`;
  } else if (!fanActive) {
    reassessmentDetail = "Activate the fan before starting the five-minute reassessment interval.";
  } else if (!fanComplete) {
    reassessmentDetail =
      `Available after the illustrative fan ramp (${fan.elapsed_minutes.toFixed(1)}/${fanDuration.toFixed(1)} simulated min).`;
  } else if (!protocolState.airflowChecked) {
    reassessmentDetail = "Confirm the airflow-path check before recording reassessment.";
  } else if (!hasLocalCO2) {
    reassessmentDetail = "Unavailable: no valid synthetic local CO₂ reading to review.";
  } else {
    reassessmentDetail =
      `Review synthetic local CO₂ ${localCO2.toFixed(2)} mmHg and scenario symptom inputs: ${scenarioSymptoms}.`;
  }

  appendProtocolStep(container, {
    number: 3,
    title: "Review and record reassessment",
    complete: protocolState.reassessmentRecorded,
    status: protocolState.reassessmentRecorded
      ? "RECORDED"
      : fanComplete && protocolState.airflowChecked ? "READY" : "WAITING",
    detail: reassessmentDetail,
    action: !protocolState.reassessmentRecorded
      ? {
          name: "reassessment",
          label: protocolState.reassessmentPending ? "RECORDING..." : "RECORD REVIEW",
          disabled: !fanComplete
            || !protocolState.airflowChecked
            || !hasLocalCO2
            || protocolState.reassessmentPending,
        }
      : null,
  });

  if (protocolState.message) {
    const message = document.createElement("p");
    message.className = "protocol-message";
    message.textContent = protocolState.message;
    container.appendChild(message);
  }
}

function appendProtocolStep(container, { number, title, status, detail, action, complete }) {
  const step = document.createElement("div");
  step.className = complete ? "protocol-step complete" : "protocol-step";

  const copy = document.createElement("div");
  copy.className = "protocol-step-copy";
  const heading = document.createElement("strong");
  heading.textContent = `${number}. ${title}`;
  const description = document.createElement("span");
  description.textContent = detail;
  const stepStatus = document.createElement("span");
  stepStatus.className = "protocol-step-status";
  stepStatus.textContent = status;
  copy.append(heading, description, stepStatus);
  step.appendChild(copy);

  if (action) {
    const button = document.createElement("button");
    button.className = "protocol-action";
    button.type = "button";
    button.dataset.protocolAction = action.name;
    button.disabled = action.disabled;
    button.textContent = action.label;
    step.appendChild(button);
  }
  container.appendChild(step);
}

function summarizeScenarioSymptoms(symptoms) {
  const labels = symptoms
    .filter((symptom) => symptom.crew === "ana")
    .map((symptom) => ({
      stuffy_nose: "nasal congestion",
      headache: "headache",
    }[symptom.symptom] || symptom.symptom));
  return labels.length ? labels.join(", ") : "none reported in scenario inputs";
}

function statusIcon(status) {
  return {
    NORMAL: "✓",
    OBSERVE: "👁",
    WARNING: "⚠",
    CRITICAL: "🚨",
    NOT_MONITORED: "—"
  }[status] || "?";
}

function logEvent(text) {
  const log = el("event-log");
  const ts = new Date().toTimeString().slice(0, 8);
  const line = document.createElement("div");
  line.className = "log-line";
  line.textContent = `[${ts}] ${text}`;
  log.prepend(line);
}

el("btn-domino").addEventListener("click", () => {
  dominoAcknowledged = true;
  logEvent("Illustrative workload scenario acknowledged; no tasks were reassigned and no mission state changed.");
  el("domino-panel").style.display = "none";
});

// --- BODY MAP LOGIC ---
const BODY_PART_INFO = {
  head: {
    title: "Head",
    scenarioSignals: [
      "Local CO₂ at the breathing zone — synthetic scenario value",
      "Headache / congestion — simulated symptom inputs"
    ],
    measurementContext: [
      "Cognitive status requires separate assessment; this prototype does not measure it."
    ]
  },
  neck: {
    title: "Neck / Airway",
    scenarioSignals: [
      "Local CO₂ — synthetic scenario value",
      "Nasal congestion — simulated symptom input"
    ],
    measurementContext: [
      "Respiratory rate can be recorded by a suitable sensor or observed chest movement; not collected by this prototype."
    ]
  },
  chest: {
    title: "Chest",
    scenarioSignals: [
      "Heart rate and SpO₂ — synthetic scenario inputs"
    ],
    measurementContext: [
      "ECG electrodes or a wearable are generally positioned on the chest; ECG/HRV are not collected.",
      "Pulse oximetry is commonly measured at a finger or ear; the displayed SpO₂ is synthetic, not a sensor reading."
    ]
  },
  gut: {
    title: "Abdomen",
    scenarioSignals: [],
    measurementContext: [
      "Hydration, digestive, and renal concerns require separate measurements or clinical assessment; no such data are collected here."
    ]
  },
  arm_l: {
    title: "Left arm",
    scenarioSignals: [],
    measurementContext: [
      "Blood pressure cuff placement: upper arm; no BP reading is collected.",
      "IV access is a procedure, not a monitoring signal; it is not represented."
    ]
  },
  arm_r: {
    title: "Right arm",
    scenarioSignals: [],
    measurementContext: [
      "Blood pressure cuff placement: upper arm; no BP reading is collected.",
      "IV access is a procedure, not a monitoring signal; it is not represented."
    ]
  },
  leg_l: {
    title: "Left leg",
    scenarioSignals: [],
    measurementContext: [
      "Muscle status and bone density require dedicated assessment or imaging (such as DXA); neither is collected by this prototype."
    ]
  },
  leg_r: {
    title: "Right leg",
    scenarioSignals: [],
    measurementContext: [
      "Muscle status and bone density require dedicated assessment or imaging (such as DXA); neither is collected by this prototype."
    ]
  }
};

function appendBodyInfoGroup(container, headingText, items) {
  if (!items.length) return;

  const group = document.createElement("div");
  group.className = "body-info-group";
  const heading = document.createElement("strong");
  heading.textContent = headingText;
  const list = document.createElement("ul");
  items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.textContent = item;
    list.append(listItem);
  });
  group.append(heading, list);
  container.append(group);
}

document.querySelectorAll('.body-part').forEach(part => {
  part.addEventListener('click', () => {
    document.querySelectorAll('.body-part').forEach(p => p.classList.remove('active'));
    part.classList.add('active');

    const partId = part.dataset.part;
    const info = BODY_PART_INFO[partId];

    if (info) {
      el('body-info-title').textContent = info.title;
      const content = el('body-info-content');
      content.replaceChildren();
      appendBodyInfoGroup(content, "Synthetic scenario inputs", info.scenarioSignals);
      appendBodyInfoGroup(content, "Measurement context — not collected here", info.measurementContext);
    }
  });
});