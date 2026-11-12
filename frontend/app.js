/* Climbing Conditions Advisor - static frontend.
 * Reads only small precomputed JSON files (paths are RELATIVE so the site works
 * under https://<user>.github.io/<repository>/). No server, no runtime LLM.
 * Preferences (region, mode, language, optional GitHub token) stay in localStorage.
 */
(() => {
  "use strict";
  const LS = {
    get: (k, d) => { try { return localStorage.getItem("cca." + k) ?? d; } catch { return d; } },
    set: (k, v) => { try { v == null || v === "" ? localStorage.removeItem("cca." + k) : localStorage.setItem("cca." + k, v); } catch {} },
  };
  const $ = (s) => document.querySelector(s);
  const state = {
    site: null, i18n: {}, data: null, index: null, selectedDay: 0,
    lang: LS.get("lang", (navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en"),
    mode: LS.get("mode", "comfort"), region: LS.get("region", null),
  };
  const STALE_HOURS = 6;

  // ---------- helpers ----------
  const t = (path, params) => {
    let s = path.split(".").reduce((o, k) => (o || {})[k], state.i18n[state.lang]);
    if (s == null) s = path.split(".").reduce((o, k) => (o || {})[k], state.i18n.en) ?? path;
    return params ? s.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? "") : s;
  };
  const tz = () => state.data?.region?.timezone || "Europe/Brussels";
  const fmt = (iso, opts) => new Intl.DateTimeFormat(state.lang === "fr" ? "fr-BE" : "en-GB",
    { timeZone: tz(), ...opts }).format(new Date(iso));
  const fmtTime = (iso) => fmt(iso, { hour: "2-digit", minute: "2-digit" });
  const fmtDay = (iso) => fmt(iso, { weekday: "short", day: "numeric", month: "short" });
  const fmtFull = (iso) => iso ? fmt(iso, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";
  const dateOnly = (d) => new Date(d + "T12:00:00Z").toISOString();
  const color = (s) => s == null ? "#9aa49f" : `hsl(${Math.round(s * 12)}, 62%, ${s >= 5 && s < 7.5 ? 42 : 40}%)`;
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const getJSON = async (path) => {
    const r = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  };
  const driversText = (list) => {
    const items = (list || []).filter((d) => d !== "missing").map((d) => t("drivers." + d));
    if (!items.length) return (list || []).includes("missing") ? t("app.score_unavailable") : t("drivers.good");
    const joined = items.length > 1 ? items.slice(0, -1).join(", ") + " " + t("drivers.and") + " " + items.at(-1) : items[0];
    return t("drivers.limited_by", { list: joined });
  };
  const ageText = (ms) => {
    const h = ms / 3.6e6;
    return h < 48 ? `${Math.max(1, Math.round(h))} ${t("app.hours_short")}` : `${Math.round(h / 24)} ${t("app.days_short")}`;
  };

  // ---------- rendering ----------
  function applyStatic() {
    document.documentElement.lang = state.lang;
    document.title = t("app.title");
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)));
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
    const sel = $("#region");
    sel.innerHTML = (state.site?.regions || []).map((r) =>
      `<option value="${esc(r.id)}"${r.id === state.region ? " selected" : ""}>${esc(r.name[state.lang] || r.name.en)}</option>`).join("");
    $("#refresh").hidden = !LS.get("token", "");
  }

  function render() {
    applyStatic();
    const d = state.data;
    const banner = $("#banner");
    if (!d) {
      banner.hidden = false; banner.textContent = t("app.no_data");
      return;
    }
    const m = d.meta;
    // freshness banner: always the real timestamp of the data
    const msgs = [];
    const age = Date.now() - new Date(m.processed_utc).getTime();
    msgs.push(age > STALE_HOURS * 3.6e6 ? t("app.age_old", { time: fmtFull(m.processed_utc), age: ageText(age) })
                                        : t("app.age_fresh", { time: fmtFull(m.processed_utc) }));
    if (m.forecast_fallback || m.observation_fallback || m.forecast_stale) msgs.push(t("app.fallback_used") + ".");
    banner.hidden = false;
    banner.classList.toggle("ok", age <= STALE_HOURS * 3.6e6);
    banner.textContent = msgs.join(" ");

    const mode = state.mode;
    const now = d.now[mode];
    $("#nowScore").textContent = now?.score ?? "–";
    $("#nowRing").style.setProperty("--c", color(now?.score));
    $("#nowKind").textContent = now?.kind ? (now.kind === "fc" ? t("app.forecast") : now.kind === "obs" ? t("app.observed") : t("app.modelled")) : "";
    $("#nowDrivers").textContent = now ? driversText(now.drivers) : "";

    const days = d.days[mode] || [];
    const day = days[state.selectedDay] || days[0];
    const today = days[0];
    const pill = $("#todayScore");
    pill.textContent = `${t("app.today")}: ${today?.score ?? t("app.score_unavailable")}`;
    pill.style.background = color(today?.score);
    $("#todayWindow").textContent = today?.best_window
      ? `${t("app.best_window")}: ${fmtTime(today.best_window.start)}–${fmtTime(today.best_window.end)} (${today.best_window.score})`
      : t("app.no_window");

    // tips for the selected day
    const tipsEl = $("#tips");
    const tips = day?.tips || [];
    const heading = state.selectedDay === 0 ? t("app.today") : fmtDay(dateOnly(day.date));
    tipsEl.innerHTML = `<li class="tip-day">${esc(heading)}</li>` + (day?.remaining === false
      ? `<li class="muted">${esc(t("app.day_over"))}</li>`
      : tips.length ? tips.map((tip) => `<li>${esc(tipText(tip))}</li>`).join("")
                    : `<li class="muted">${esc(t("app.no_tips"))}</li>`);

    // outlook
    $("#outlook").innerHTML = days.map((x, i) => `
      <button class="day" data-day="${i}" aria-pressed="${i === state.selectedDay}">
        <div class="dname">${esc(i === 0 ? t("app.today") : fmtDay(dateOnly(x.date)))}</div>
        <div class="dscore" style="color:${color(x.score)}">${x.score ?? "–"}</div>
        <div class="dwin">${x.best_window ? esc(fmtTime(x.best_window.start) + "–" + fmtTime(x.best_window.end) + " · " + x.best_window.score) : esc(t("app.no_window"))}</div>
        <div class="ddrv">${esc((x.drivers || []).map((k) => t("drivers." + k)).join(", "))}</div>
      </button>`).join("");
    document.querySelectorAll(".day").forEach((b) => b.addEventListener("click", () => { state.selectedDay = +b.dataset.day; render(); }));

    renderChart(d, mode);
    renderMeta(d);
  }

  function tipText(tip) {
    const p = { ...(tip.params || {}) };
    if (p.dry_at) p.dry_at = fmt(p.dry_at, { weekday: "short", hour: "2-digit", minute: "2-digit" });
    if (p.window_day) p.window_day = fmtDay(p.window_day);
    if (p.window_start) p.window_start = fmtTime(p.window_start);
    if (p.window_end) p.window_end = fmtTime(p.window_end);
    return t("tips." + tip.key, p);
  }

  function renderChart(d, mode) {
    const h = d.hourly, svg = $("#chart");
    const nowIso = d.now[mode]?.t;
    const startIdx = Math.max(0, h.t.findIndex((x) => x >= nowIso) - 24);
    const idx = [...h.t.keys()].slice(startIdx);
    const bw = 7, gap = 1, H = 150, top = 14, W = idx.length * (bw + gap) + 4;
    svg.setAttribute("viewBox", `0 0 ${W} ${H + 20}`);
    svg.style.width = `${Math.max(W, 300)}px`;
    let out = "";
    for (const v of [5, 10]) out += `<line x1="0" x2="${W}" y1="${top + H - (v / 10) * H}" y2="${top + H - (v / 10) * H}" stroke="currentColor" opacity=".12"/>`;
    idx.forEach((i, k) => {
      const x = 2 + k * (bw + gap), s = h.score[mode][i];
      const local = new Date(h.t[i]);
      const hourLocal = +fmt(h.t[i], { hour: "2-digit", hourCycle: "h23" });
      if (hourLocal === 0) {
        out += `<line x1="${x - 1}" x2="${x - 1}" y1="0" y2="${top + H}" stroke="currentColor" opacity=".25"/>`;
        out += `<text x="${x + 2}" y="10" font-size="9" fill="currentColor" opacity=".7">${esc(fmtDay(local.toISOString()))}</text>`;
      }
      if (s != null) {
        const bh = Math.max(2, (s / 10) * H), op = h.kind[i] === "fc" ? 0.55 : 1;
        out += `<rect data-i="${i}" x="${x}" y="${top + H - bh}" width="${bw}" height="${bh}" rx="1.5" fill="${color(s)}" opacity="${op}"><title>${esc(fmtFull(h.t[i]))}: ${s}</title></rect>`;
      } else {
        out += `<rect data-i="${i}" x="${x}" y="${top + H - 2}" width="${bw}" height="2" fill="#9aa49f" opacity=".5"/>`;
      }
      if ((h.precip_mm[i] || 0) >= 0.1) out += `<circle cx="${x + bw / 2}" cy="${top + H + 8}" r="${Math.min(3.5, 1.2 + h.precip_mm[i])}" fill="#3b82c4"/>`;
      if (h.t[i] === nowIso) out += `<line x1="${x}" x2="${x}" y1="0" y2="${top + H}" stroke="currentColor" stroke-dasharray="3 3" opacity=".8"/>`;
    });
    svg.innerHTML = out;
    svg.onclick = svg.onmousemove = (e) => {
      const i = e.target?.dataset?.i;
      if (i == null) return;
      const v = (k, u, n = 1) => h[k][i] == null ? "–" : `${(+h[k][i]).toFixed(n)}${u}`;
      $("#hourDetail").textContent = `${fmtFull(h.t[i])} (${h.kind[i] === "fc" ? t("app.forecast") : t("app.observed")}) · `
        + `${h.score[mode][i] ?? "–"}/10 · ${v("temp_c", "°C")} · ${v("rh", "%", 0)} · ${v("wind_ms", " m/s")} · `
        + `${v("precip_mm", " mm", 1)} · ${t("drivers.wetness")}: ${v("wet_mm", " mm", 2)} · ${driversText(h.drivers[mode][i])}`;
    };
  }

  function renderMeta(d) {
    const m = d.meta, st = m.station;
    const rows = [
      [t("app.model_run"), m.model_run_utc ? `${fmtFull(m.model_run_utc)} · ${m.forecast_label}` : `${m.forecast_label || "–"}`],
      [t("app.observation_time"), m.observation_last_utc ? `${fmtFull(m.observation_last_utc)} · ${m.observation_label}` : "–"],
      [t("app.station"), st ? `${st.name} (${st.code}), ${st.altitude} m, ${st.km} km` : "–"],
      [t("app.last_updated"), fmtFull(m.processed_utc)],
    ];
    const notes = [];
    if (m.observation_provisional) notes.push(t("app.provisional"));
    if (m.forecast_provider === "ecmwf") notes.push(t("app.interpolated_note"));
    (m.warnings || []).forEach((w) => notes.push(w));
    $("#meta").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")
      + (notes.length ? `<dt></dt><dd class="muted small">${notes.map(esc).join("<br>")}</dd>` : "");
    const names = { temp_c: "temperature", dewpoint_c: "dewpoint", rh: "humidity", precip_mm: "precipitation",
                    wind_ms: "wind", cloud_pct: "cloud", sw_wm2: "radiation" };
    $("#sources").innerHTML = `<tr><th></th><th>${esc(t("app.observed"))}</th><th>${esc(t("app.forecast"))}</th></tr>`
      + Object.entries(m.sources).map(([k, s]) => `<tr><td>${esc(t("vars." + names[k]))}</td><td>${esc(s.observed || "–")}</td><td>${esc(s.forecast || "–")}</td></tr>`).join("");
    $("#omAttr").hidden = !JSON.stringify(m.sources).includes("Open-Meteo");
  }

  // ---------- data loading ----------
  async function loadRegion() {
    const entry = (state.index?.regions || []).find((r) => r.id === state.region);
    state.data = null;
    if (entry?.available) {
      try { state.data = await getJSON(`data/${state.region}/latest.json`); } catch (e) { console.error(e); }
    }
    const days = state.data?.days?.[state.mode] || [];
    state.selectedDay = Math.max(0, days.findIndex((x) => x.remaining !== false));
    render();
  }

  async function init() {
    const [site, en, fr] = await Promise.all([getJSON("site-config.json"), getJSON("i18n/en.json"), getJSON("i18n/fr.json")]);
    state.site = site; state.i18n = { en, fr };
    if (!site.modes.includes(state.mode)) state.mode = site.modes[0];
    if (!site.regions.some((r) => r.id === state.region)) state.region = site.regions[0]?.id;
    try { state.index = await getJSON("data/index.json"); } catch { state.index = { regions: [] }; }
    bind();
    await loadRegion();
  }

  // ---------- optional "Refresh" (dispatches the update workflow with the user's own token) ----------
  function repoName() {
    const saved = LS.get("repo", "");
    if (saved) return saved;
    if (state.site?.repo) return state.site.repo;
    const host = location.hostname;
    if (host.endsWith(".github.io")) {
      const owner = host.split(".")[0], seg = location.pathname.split("/").filter(Boolean)[0];
      return seg ? `${owner}/${seg}` : `${owner}/${host}`;
    }
    return "";
  }

  async function refresh() {
    const token = LS.get("token", ""), repo = repoName(), btn = $("#refresh"), banner = $("#banner");
    if (!token || !repo) { $("#settings").showModal(); return; }
    btn.disabled = true;
    const before = state.index?.processed_utc;
    try {
      // GitHub REST: POST /repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches
      const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${state.site.workflow}/dispatches`, {
        method: "POST",
        headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28" },
        body: JSON.stringify({ ref: state.site.branch || "main" }),
      });
      if (r.status !== 204) throw new Error(`HTTP ${r.status}`);
      banner.hidden = false; banner.textContent = t("app.refreshing");
      const t0 = Date.now();
      while (Date.now() - t0 < 12 * 60 * 1000) {
        await new Promise((ok) => setTimeout(ok, 20000));
        try {
          const idx = await getJSON("data/index.json");
          if (idx.processed_utc !== before) { state.index = idx; await loadRegion(); banner.textContent += " " + t("app.refresh_done"); return; }
        } catch {}
      }
      banner.textContent = t("app.refresh_timeout");
    } catch (e) {
      banner.hidden = false; banner.textContent = `${t("app.refresh_error")} (${e.message}).`;
    } finally { btn.disabled = false; }
  }

  function bind() {
    $("#region").addEventListener("change", (e) => { state.region = e.target.value; LS.set("region", state.region); loadRegion(); });
    document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { state.mode = b.dataset.mode; LS.set("mode", state.mode); render(); }));
    document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => { state.lang = b.dataset.lang; LS.set("lang", state.lang); render(); }));
    $("#refresh").addEventListener("click", refresh);
    $("#settingsBtn").addEventListener("click", () => {
      $("#repoInput").value = repoName(); $("#tokenInput").value = LS.get("token", "");
      $("#settings").showModal();
    });
    $("#saveSettings").addEventListener("click", () => {
      LS.set("repo", $("#repoInput").value.trim()); LS.set("token", $("#tokenInput").value.trim()); render();
    });
  }

  init().catch((e) => {
    console.error(e);
    const b = $("#banner"); b.hidden = false; b.textContent = "Could not load the app configuration: " + e.message;
  });
})();
