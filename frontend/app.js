// API base: ?api=http://127.0.0.1:8000 overrides the deployed default (no need to edit/commit this file).
const API_URL = (new URLSearchParams(location.search).get("api") || "https://chroma-proof.onrender.com").replace(/\/$/, "");
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ICON = { POSITIVE: "✖ POSITIVE (presumptive)", NEGATIVE: "✔ NEGATIVE (presumptive)", INCONCLUSIVE: "❓ INCONCLUSIVE" };

function getLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve("GPS: unavailable");
    navigator.geolocation.getCurrentPosition(
      (p) => resolve(`${p.coords.latitude.toFixed(6)},${p.coords.longitude.toFixed(6)} (+/-${Math.round(p.coords.accuracy)}m, device-reported)`),
      () => resolve("GPS: unavailable"), { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 });
  });
}

// ---------- offline queue (IndexedDB) ----------
const idb = () => new Promise((res, rej) => {
  const r = indexedDB.open("chromaproof", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const tx = async (mode, fn) => { const d = await idb(); return new Promise((res, rej) => { const t = d.transaction("queue", mode); const out = fn(t.objectStore("queue")); t.oncomplete = () => res(out.result); t.onerror = () => rej(t.error); }); };
const qAdd = (item) => tx("readwrite", (s) => s.add(item));
const qAll = () => tx("readonly", (s) => s.getAll());
const qDel = (id) => tx("readwrite", (s) => s.delete(id));

async function updatePending() {
  const items = await qAll().catch(() => []);
  const el = $("pending");
  el.style.display = items.length ? "block" : "none";
  el.textContent = items.length ? `⏳ ${items.length} capture(s) PENDING SYNC - will upload when online.` : "";
}
async function flushQueue() {
  for (const it of await qAll().catch(() => [])) {
    try {
      const res = await send(it.blob, it.operator, it.kit, it.location);
      if (res.status !== 0) await qDel(it.id);     // delivered (success or a definite server answer)
    } catch { break; }                              // still offline
  }
  updatePending();
}
async function send(blob, operator, kit, location) {
  const fd = new FormData();
  fd.append("image", blob, "capture.jpg"); fd.append("operator_id", operator); fd.append("kit_id", kit); fd.append("location", location);
  const res = await fetch(`${API_URL}/api/process`, { method: "POST", body: fd });
  return { status: res.status, ok: res.ok, data: await res.json().catch(() => ({})) };
}

// ---------- capture ----------
function busy(on) {
  $("btnCapture").disabled = $("btnGallery").disabled = on;
  $("btnCapture").innerText = on ? "Processing..." : "Snap & Analyze";
  $("btnGallery").innerText = on ? "Processing..." : "📁 Upload from Gallery";
}
async function processBlob(blob, source) {
  const operator = $("operatorId").value.trim() || "UNKNOWN";
  const kit = $("kitSelect").value;
  const location = `${await getLocation()} [${source}]`;
  busy(true);
  try {
    const r = await send(blob, operator, kit, location);
    if (r.ok && r.data.status === "SUCCESS") showResult(r.data.record);
    else if (r.status === 422) showRetake(r.data.reasons || [r.data.detail]);
    else showError(r.data.detail || "Analysis failed.");
  } catch {
    await qAdd({ blob, operator, kit, location, ts: Date.now() });
    updatePending();
    showError("Offline: capture saved locally with status PENDING SYNC. It will upload automatically when you are back online.");
  } finally { busy(false); }
}
function showResult(rec) {
  const b = $("resultBox"); b.style.display = "block"; b.className = `result-box ${rec.result}`;
  b.innerHTML = `<div class="presumptive">PRESUMPTIVE RESULT - LAB CONFIRMATION REQUIRED</div>
    <h2>${esc(ICON[rec.result] || rec.result)}</h2>
    <p><strong>Colour-margin cue:</strong> ${esc(rec.confidence)} <small>(relative cue, not a probability)</small></p>
    <p><strong>Why:</strong> ${esc(rec.explanation)}</p>
    <div class="meta-data"><p>ID: ${esc(rec.record_id)}</p><p>Location: ${esc(rec.location)}</p>
    <p>Hash: ${esc(rec.image_sha256)}</p><p>Signed by: ${esc(rec.key_id)} | Sync: ${esc(rec.sync_status)}</p></div>`;
}
function showRetake(reasons) {
  const b = $("resultBox"); b.style.display = "block"; b.className = "result-box";
  b.innerHTML = `<div class="retake"><strong>⚠ Retake needed - no result recorded</strong><ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`;
}
function showError(msg) {
  const b = $("resultBox"); b.style.display = "block"; b.className = "result-box";
  b.innerHTML = `<div class="retake"><strong>${esc(msg)}</strong></div>`;
}

// ---------- history / verify ----------
async function loadHistory() {
  const p = new URLSearchParams();
  if ($("fResult").value) p.set("result", $("fResult").value);
  if ($("fOperator").value) p.set("operator", $("fOperator").value);
  if ($("fDate").value) p.set("date", $("fDate").value);
  const list = $("historyList"); list.textContent = "Loading...";
  try {
    const rows = await (await fetch(`${API_URL}/api/records?${p}`)).json();
    list.innerHTML = rows.length ? rows.map((r) => `<div class="row" data-id="${esc(r.record_id)}"><span>${esc(r.record_id)}<br><small>${esc(r.operator_id)} · ${esc(r.timestamp_utc)}</small></span><span class="badge ${esc(r.result)}">${esc(ICON[r.result] || r.result)}</span></div>`).join("") : "No records found.";
    list.querySelectorAll(".row").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.id)));
  } catch { list.textContent = "Could not reach the server."; }
}
async function openDetail(id) {
  const rec = await (await fetch(`${API_URL}/api/records/${encodeURIComponent(id)}`)).json();
  const d = $("detail"); d.style.display = "block";
  d.innerHTML = `<strong>${esc(rec.record_id)}</strong> - ${esc(rec.result)}<br>
    Operator: ${esc(rec.operator_id)}<br>Time: ${esc(rec.timestamp_utc)} (${esc(rec.timestamp_source)})<br>Kit: ${esc(rec.kit_id)}<br>
    Cue: ${esc(rec.confidence)} · ${esc(rec.classifier_version)}<br>Location: ${esc(rec.location)}<br>Image SHA-256: ${esc(rec.image_sha256)}<br>
    Key: ${esc(rec.key_id)} · Sync: ${esc(rec.sync_status)}<br>
    <img src="${API_URL}/api/records/${encodeURIComponent(id)}/image" alt="captured image" style="width:100%;max-width:320px;margin-top:8px;border-radius:8px">
    <div class="actions">
      <button class="btn small" id="vOk">Verify integrity</button>
      <button class="btn small secondary" id="vBad">Simulate tampering</button>
      <a class="btn small secondary" href="${API_URL}/api/records/${encodeURIComponent(id)}/report.pdf" target="_blank">PDF</a>
      <a class="btn small secondary" href="${API_URL}/api/records/${encodeURIComponent(id)}/report.json" target="_blank">JSON</a>
    </div><div id="vOut"></div>`;
  const run = async (sim) => {
    const v = await (await fetch(`${API_URL}/api/verify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ record_id: id, simulate_tamper: sim }) })).json();
    $("vOut").innerHTML = `<div class="vstatus ${esc(v.status)}">${v.valid ? "✔" : "✖"} ${esc(v.status)}${v.simulated_tamper ? " (simulated edit)" : ""}: ${esc(v.message)}<br><small>${esc(v.scope)}</small></div>`;
  };
  $("vOk").onclick = () => run(false); $("vBad").onclick = () => run(true);
  d.scrollIntoView({ behavior: "smooth" });
}

// ---------- init ----------
function tab(name) {
  $("viewCapture").style.display = name === "capture" ? "block" : "none";
  $("viewHistory").style.display = name === "history" ? "block" : "none";
  $("tabCapture").classList.toggle("active", name === "capture"); $("tabHistory").classList.toggle("active", name === "history");
  if (name === "history") loadHistory();
}
async function init() {
  $("tabCapture").onclick = () => tab("capture"); $("tabHistory").onclick = () => tab("history"); $("btnRefresh").onclick = loadHistory;
  try {
    const kits = await (await fetch(`${API_URL}/api/kits`)).json();
    $("kitSelect").innerHTML = kits.map((k) => `<option value="${esc(k.id)}">${esc(k.name)}</option>`).join("");
  } catch { $("kitSelect").innerHTML = `<option value="cobalt_thiocyanate">Cobalt Thiocyanate (offline list)</option>`; }
  const video = $("webcam");
  try { video.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }); }
  catch { video.style.display = "none"; }
  $("btnCapture").onclick = () => {
    if (!video.videoWidth) return showError("Camera unavailable. Use Upload from Gallery.");
    const c = document.createElement("canvas"); c.width = video.videoWidth; c.height = video.videoHeight;
    c.getContext("2d").drawImage(video, 0, 0); c.toBlob((b) => processBlob(b, "Live Capture"), "image/jpeg", 0.92);
  };
  $("btnGallery").onclick = () => $("galleryInput").click();
  $("galleryInput").onchange = (e) => { const f = e.target.files[0]; if (f) processBlob(f, "Gallery Upload"); e.target.value = ""; };
  window.addEventListener("online", flushQueue);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  await updatePending(); flushQueue();
}
init();
