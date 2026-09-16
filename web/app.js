/* -------------------------------------------------------------------------
 * ERP-Agent · Frontend de prueba
 *
 * Consume:
 *   POST /chat/stream  →  Server-Sent Events (tokens + tool traces).
 *   POST /chat         →  Respuesta JSON completa.
 *
 * SSE con POST: no podemos usar EventSource (que sólo hace GET). Usamos
 * fetch() + ReadableStream y parseamos el formato SSE manualmente:
 *   event: <tipo>\ndata: <json>\n\n
 * ------------------------------------------------------------------------- */

const $log       = document.getElementById("log");
const $form      = document.getElementById("form");
const $input     = document.getElementById("input");
const $btnSend   = document.getElementById("btn-send");
const $btnStop   = document.getElementById("btn-stop");
const $btnClear  = document.getElementById("btn-clear");
const $provider  = document.getElementById("provider");
const $role      = document.getElementById("role");
const $year      = document.getElementById("year");
const $endpoint  = document.getElementById("endpoint");
const $connDot   = document.getElementById("conn-dot");
const $connLabel = document.getElementById("conn-label");

let currentController = null;

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function setStatus(state, label) {
  $connDot.classList.remove("dot-idle", "dot-active", "dot-error");
  $connDot.classList.add(state === "active" ? "dot-active" : state === "error" ? "dot-error" : "dot-idle");
  $connLabel.textContent = label;
}

function scroll() {
  $log.scrollTop = $log.scrollHeight;
}

function makeRow() {
  const row = document.createElement("div");
  row.className = "msg-row";
  $log.appendChild(row);
  return row;
}

function addUser(text) {
  const row = makeRow();
  const b = document.createElement("div");
  b.className = "bubble bubble-user self-end ml-auto";
  b.textContent = text;
  row.appendChild(b);
  scroll();
}

function addAgentBubble() {
  const row = makeRow();
  const b = document.createElement("div");
  b.className = "bubble bubble-agent cursor-blink";
  row.appendChild(b);
  scroll();
  return { row, bubble: b };
}

function addErrorBubble(text) {
  const row = makeRow();
  const b = document.createElement("div");
  b.className = "bubble bubble-error";
  b.textContent = "⚠  " + text;
  row.appendChild(b);
  scroll();
}

function addBlockedBubble(text, category) {
  const row = makeRow();
  const b = document.createElement("div");
  b.className = "bubble bubble-block";
  b.textContent = "🛡  Bloqueado (" + (category || "guardrail") + "): " + text;
  row.appendChild(b);
  scroll();
}

function addToolChip(row, name, args) {
  const chip = document.createElement("span");
  chip.className = "tool-chip running";
  chip.textContent = `⚙ ${name}(${previewArgs(args)}) …`;
  row.appendChild(chip);
  scroll();
  return chip;
}

function updateToolChip(chip, name, output) {
  const err = output && typeof output === "object" && output.error;
  chip.className = "tool-chip " + (err ? "error" : "done");
  chip.textContent = err
    ? `⚠ ${name} → ${output.error}`
    : `✓ ${name} → ${previewOutput(output)}`;
}

function previewArgs(args) {
  try {
    const s = JSON.stringify(args);
    return s.length > 60 ? s.slice(0, 57) + "…" : s;
  } catch { return "…"; }
}
function previewOutput(out) {
  try {
    const s = typeof out === "string" ? out : JSON.stringify(out);
    return s.length > 80 ? s.slice(0, 77) + "…" : s;
  } catch { return "…"; }
}

function addSourcesBlock(row, sources) {
  if (!sources || !sources.length) return;
  const details = document.createElement("details");
  details.className = "sources";
  const summary = document.createElement("summary");
  summary.textContent = `📎 ${sources.length} fuente(s) del RAG`;
  details.appendChild(summary);
  const pre = document.createElement("pre");
  pre.textContent = sources
    .map((s, i) => `[${i + 1}] ${s.file}${s.year ? ` (year=${s.year})` : ""}${s.score != null ? ` score=${s.score.toFixed(3)}` : ""}\n${s.snippet || ""}`)
    .join("\n\n");
  details.appendChild(pre);
  row.appendChild(details);
}

// ---------------------------------------------------------------------------
// Petición: modo completo (/chat)
// ---------------------------------------------------------------------------
async function sendFull(payload) {
  setStatus("active", "enviando…");
  const { row, bubble } = addAgentBubble();
  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text()}`);
    const data = await res.json();
    bubble.classList.remove("cursor-blink");
    if (data.blocked) {
      row.removeChild(bubble);
      addBlockedBubble(data.response, data.block_reason);
    } else {
      bubble.textContent = data.response || "(vacío)";
      (data.tools_used || []).forEach(t => {
        const chip = addToolChip(row, t.name, t.arguments);
        updateToolChip(chip, t.name, t.output);
      });
      addSourcesBlock(row, data.sources);
    }
  } catch (e) {
    bubble.classList.remove("cursor-blink");
    row.removeChild(bubble);
    addErrorBubble(e.message);
  } finally {
    setStatus("idle", "idle");
  }
}

// ---------------------------------------------------------------------------
// Petición: modo streaming (/chat/stream)
// ---------------------------------------------------------------------------
async function sendStream(payload) {
  setStatus("active", "streaming…");
  $btnStop.disabled = false;

  const controller = new AbortController();
  currentController = controller;

  const { row, bubble } = addAgentBubble();
  let acc = "";
  const toolChips = new Map(); // name -> chip element (last)

  try {
    const res = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        if (j && j.message) msg = j.message;
        if (j && j.category === "prompt_injection" || j && j.category === "restricted_data") {
          row.removeChild(bubble);
          addBlockedBubble(msg, j.category);
          return;
        }
      } catch {}
      throw new Error(msg);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // sse-starlette (y la spec SSE) usan CRLF (\r\n) como terminador de línea.
      // Normalizamos a LF para poder buscar el separador de bloques (\n\n) sin
      // fallar en Windows / con proxies que preservan CRLF.
      buffer = buffer.replace(/\r\n/g, "\n");

      // Parseo SSE: bloques separados por \n\n. Cada bloque tiene "event:" y "data:".
      let sepIdx;
      while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);
        const evt = parseSseBlock(raw);
        if (!evt) continue;
        handleEvent(evt, { row, bubble, toolChips, accRef: v => (acc = v ?? acc) });
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      addErrorBubble("Stream cancelado por el usuario.");
    } else {
      addErrorBubble(e.message);
    }
  } finally {
    bubble.classList.remove("cursor-blink");
    setStatus("idle", "idle");
    $btnStop.disabled = true;
    currentController = null;
  }
}

function parseSseBlock(raw) {
  let event = "message";
  const dataLines = [];
  // split acepta CRLF o LF por si algún proxy no fue normalizado antes.
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    // ignora id:, retry:, comentarios que empiezan con ":" (heartbeats "ping").
  }
  if (!dataLines.length) return null;
  const dataStr = dataLines.join("\n");
  let data = null;
  try { data = JSON.parse(dataStr); } catch { data = { raw: dataStr }; }
  return { event, data };
}

function handleEvent(evt, ctx) {
  const { row, bubble, toolChips } = ctx;
  const { event, data } = evt;
  const type = (data && data.type) || event;

  switch (type) {
    case "meta": {
      // Muestra el proveedor y prepara fuentes; las mostramos al final también.
      const info = document.createElement("div");
      info.className = "bubble bubble-meta";
      info.textContent = `provider=${data.provider} · sources=${(data.sources || []).length}`;
      row.insertBefore(info, bubble);
      row._sources = data.sources || [];
      break;
    }
    case "tool_start": {
      const chip = addToolChip(row, data.name, data.arguments);
      toolChips.set(data.name + ":" + (toolChips.size), chip);
      row._lastChip = chip;
      break;
    }
    case "tool_end": {
      const chip = row._lastChip;
      if (chip) updateToolChip(chip, data.name, data.output);
      break;
    }
    case "token": {
      bubble.textContent += (data.content || "");
      scroll();
      break;
    }
    case "done": {
      if (row._sources) addSourcesBlock(row, row._sources);
      break;
    }
    case "error": {
      addErrorBubble(data.message || "Error desconocido en el stream.");
      break;
    }
    default:
      // Evento desconocido: lo ignoramos silenciosamente.
      break;
  }
}

// ---------------------------------------------------------------------------
// Envío
// ---------------------------------------------------------------------------
async function submit() {
  const message = $input.value.trim();
  if (!message) return;
  const payload = {
    message,
    user_role: $role.value,
    year_filter: $year.value ? Number($year.value) : null,
  };
  if ($provider.value) payload.provider = $provider.value;

  addUser(message);
  $input.value = "";
  $input.style.height = "auto";
  $btnSend.disabled = true;

  try {
    if ($endpoint.value === "/chat/stream") {
      await sendStream(payload);
    } else {
      await sendFull(payload);
    }
  } finally {
    $btnSend.disabled = false;
    $input.focus();
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
$form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
});

$input.addEventListener("input", () => {
  $input.style.height = "auto";
  $input.style.height = Math.min($input.scrollHeight, 160) + "px";
});

document.querySelectorAll(".preset").forEach(btn => {
  btn.addEventListener("click", () => {
    $input.value = btn.dataset.msg;
    $input.dispatchEvent(new Event("input"));
    $input.focus();
  });
});

$btnStop.addEventListener("click", () => {
  if (currentController) currentController.abort();
});

$btnClear.addEventListener("click", () => {
  $log.innerHTML = '<div class="text-center text-xs text-slate-500">Log limpiado.</div>';
});

setStatus("idle", "idle");
