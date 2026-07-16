function el(id) {
  return document.getElementById(id);
}

function fmt(v, opts = {}) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string" && Number.isNaN(Number(v))) return v;
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (opts.pct) return (n * 100).toFixed(2) + "%";
  if (opts.pctPoints) return n.toFixed(2) + "%";
  const d = opts.digits ?? 2;
  return n.toLocaleString("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: d,
  });
}

function clsNum(v) {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n) || n === 0) return "";
  return n > 0 ? "num-pos" : "num-neg";
}

function displayCell(col) {
  if (col.display !== null && col.display !== undefined && col.display !== "") {
    if (typeof col.display === "number") return fmt(col.display);
    return String(col.display);
  }
  if (col.fmt === "pct" && typeof col.value === "number")
    return fmt(col.value, { pct: true });
  if (col.fmt === "pct_points" && typeof col.value === "number")
    return fmt(col.value, { pctPoints: true });
  if (col.fmt === "text") return col.value ?? "—";
  return fmt(col.value);
}

/** Color class for "123 (+1.2%)" style strings */
function clsFromDisplay(display, value) {
  if (typeof display === "string") {
    const m = display.match(/\(([+-]?\d+(?:\.\d+)?)%\)/);
    if (m) {
      const n = Number(m[1]);
      if (n > 0) return "num-pos";
      if (n < 0) return "num-neg";
    }
    if (display.includes("(+") || /\(\+/.test(display)) return "num-pos";
    if (/\(-\d/.test(display)) return "num-neg";
  }
  return clsNum(value);
}

/** Tab roles: pre | live | fii | structure | history | guide */
function switchTab(name) {
  const tabName = name || "pre";
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.getAttribute("data-tab") === tabName);
  });
  document.querySelectorAll(".panel").forEach((p) => {
    p.classList.remove("active");
    p.style.display = "none";
  });
  const panel = el("panel-" + tabName);
  if (panel) {
    panel.classList.add("active");
    panel.style.display = "block";
  } else {
    console.error("Panel not found:", "panel-" + tabName);
  }
  if (tabName === "guide") loadDocs();
  if (tabName === "history") loadHistory().catch(() => {});
  if (window.__lastSnap) {
    if (tabName === "pre") renderPre(window.__lastSnap);
    if (tabName === "live") renderLive(window.__lastSnap);
    if (tabName === "fii") renderFii(window.__lastSnap);
    if (tabName === "structure") renderStructure(window.__lastSnap);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}
window.switchTab = switchTab;

/** Which column_groups go to which tab (no cross-duplication) */
const TAB_GROUPS = {
  pre: ["Meta", "Gap", "US", "Asia", "Europe"],
  live: ["India"], // Nifty BN Sensex VIX only
};

function renderGroupTables(containerId, groups, filterNames) {
  const root = el(containerId);
  if (!root) return;
  root.innerHTML = "";
  const list = (groups || []).filter((g) =>
    filterNames ? filterNames.includes(g.group) : true
  );
  if (!list.length) {
    root.innerHTML =
      '<div class="edge-empty">No rows yet — click <strong>↻ Refresh</strong>.</div>';
    return;
  }
  list.forEach((g) => {
    const block = document.createElement("div");
    block.className = "group-block";
    let titleCls = "group-title";
    if (g.group === "Europe") titleCls += " g-Europe";
    if (g.group === "Gap") titleCls += " g-Gap";
    if (String(g.group).includes("OI")) titleCls += " oi";
    block.innerHTML = `<div class="${titleCls}">${g.group}</div>`;
    const table = document.createElement("table");
    table.className = "sheet";
    table.innerHTML = `
      <thead>
        <tr>
          <th>Column</th>
          <th>Value</th>
          <th>Kyun important</th>
          <th>Kab dekhna</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody></tbody>`;
    const tbody = table.querySelector("tbody");
    (g.columns || []).forEach((col) => {
      // Live tab: only India index keys (not FII columns if mixed)
      if (filterNames && filterNames.includes("India") && g.group === "India") {
        const allow = ["nifty", "banknifty", "sensex", "vix"];
        if (!allow.includes(col.key)) return;
      }
      const tr = document.createElement("tr");
      const val = displayCell(col);
      tr.innerHTML = `
        <td class="col-key">${col.label}<div style="font-size:10px;color:#999">${col.key}</div></td>
        <td class="col-val ${clsFromDisplay(val, col.value)}">${val}</td>
        <td class="col-why">${col.why || ""}</td>
        <td class="col-when">${col.when || ""}</td>
        <td>${col.src || ""}</td>`;
      tbody.appendChild(tr);
    });
    block.appendChild(table);
    root.appendChild(block);
  });
}

function renderEdgeBlocksInto(containerId, blocks) {
  const root = el(containerId);
  if (!root) return;
  root.innerHTML = "";
  const list = blocks || [];
  if (!list.length) {
    root.innerHTML =
      '<div class="edge-empty">No data — click <strong>↻ Refresh</strong> (Upstox token may be required).</div>';
    return;
  }
  list.forEach((block) => {
    const wrap = document.createElement("div");
    wrap.className = "edge-block";
    const note = block.note
      ? `<span class="note-sm">${block.note}</span>`
      : block.oi_date
        ? `<span class="note-sm">OI date ${block.oi_date}</span>`
        : "";
    wrap.innerHTML = `<div class="edge-block-head"><span>${block.section || ""}</span>${note}</div>`;
    const grid = document.createElement("div");
    grid.className = "edge-grid";
    const cards = block.cards || [];
    if (!cards.length) {
      grid.innerHTML =
        '<div class="edge-empty" style="grid-column:1/-1">Empty block.</div>';
    }
    cards.forEach((c) => {
      const card = document.createElement("div");
      card.className = "edge-card";
      const sig = c.signal
        ? `<div class="ec-signal${
            /⚠️|risk|Defensive|short build|stress/i.test(c.signal) ? "" : " ok"
          }">${c.signal}</div>`
        : "";
      card.innerHTML = `
        <div class="ec-title">${c.title || ""}</div>
        <div class="ec-value ${clsFromDisplay(String(c.value), null)}">${c.value ?? "—"}</div>
        <div class="ec-meaning">${c.meaning || ""}</div>
        <div class="ec-why"><strong>Why:</strong> ${c.why || ""}</div>
        ${sig}`;
      grid.appendChild(card);
    });
    wrap.appendChild(grid);
    root.appendChild(wrap);
  });
}

function proBlocksBySection(data, matcher) {
  const pe = (data && data.pro_edge) || {};
  return (pe.blocks || []).filter((b) => matcher(String(b.section || "")));
}

function setText(id, text) {
  const n = el(id);
  if (n) n.textContent = text;
}

function paintPlaybook(elRoot, conclusion, gapLine) {
  if (!elRoot || !conclusion) return;
  elRoot.className = "playbook " + (conclusion.color || "neutral");
  const badge = elRoot.querySelector(".pb-badge");
  if (badge && conclusion.bias) badge.textContent = conclusion.bias;
}

function renderPre(data) {
  setText("preDateDay", `${data.date || "—"} · ${data.day || ""}`);
  setText(
    "preTrading",
    data.is_trading ? "YES ✅" : `NO ❌ ${data.holiday || data.reason || ""}`
  );
  setText(
    "preGift",
    data.gift_display || fmt(data.gift) || "—"
  );
  setText(
    "preGapPts",
    data.gap_pts != null
      ? data.gap_pct != null
        ? `${fmt(data.gap_pts)} pts (${data.gap_pct >= 0 ? "+" : ""}${(data.gap_pct * 100).toFixed(2)}%)`
        : fmt(data.gap_pts) + " pts"
      : "—"
  );
  setText(
    "preGapPct",
    data.gap_pct != null
      ? `${data.gap_pct >= 0 ? "+" : ""}${(Number(data.gap_pct) * 100).toFixed(2)}%`
      : "—"
  );
  const gapCat = el("preGapCat");
  if (gapCat) {
    gapCat.textContent = data.gap_category || "—";
    gapCat.className = "tag " + (data.gap_category || "");
  }

  // Pre playbook = FII conclusion + gap
  const c =
    data.fii_conclusion ||
    (data.pro_edge && data.pro_edge.fii_conclusion) ||
    {};
  const pb = el("prePlaybook");
  if (pb) {
    pb.className = "playbook " + (c.color || "neutral");
    setText("prePlayHead", c.headline || "FII conclusion pending — open Refresh");
    setText(
      "prePlayBody",
      (c.plan_pre || c.one_liner || "—") +
        (data.gap_category
          ? ` · Gap: ${data.gap_category}`
          : "")
    );
  }
  renderGroupTables("preGroups", data.column_groups, TAB_GROUPS.pre);
}

function renderLive(data) {
  setText("liveCardNifty", data.nifty_display || fmt(data.nifty) || "—");
  setText("liveCardBN", data.banknifty_display || fmt(data.banknifty) || "—");
  setText("liveCardSensex", data.sensex_display || fmt(data.sensex) || "—");
  setText("liveCardVix", data.vix_display || fmt(data.vix) || "—");
  ["liveCardNifty", "liveCardBN", "liveCardSensex", "liveCardVix"].forEach(
    (id) => {
      const n = el(id);
      if (n) n.className = "big " + clsFromDisplay(n.textContent, null);
    }
  );

  // OI board readout drives live playbook
  const boards = ((data.pro_edge || {}).oi_board || {}).boards || [];
  const niftyBoard = boards.find((b) => b.label === "Nifty" && b.ok);
  const c =
    data.fii_conclusion ||
    (data.pro_edge && data.pro_edge.fii_conclusion) ||
    {};
  const pb = el("livePlaybook");
  if (pb) {
    const read = (niftyBoard && niftyBoard.read) || {};
    const bias = read.bias || c.bias || "RANGE";
    pb.className =
      "playbook " +
      (bias.includes("BOUNCE") || bias.includes("SUPPORT")
        ? "bull"
        : bias.includes("REJECT") || bias.includes("CAP")
          ? "bear"
          : c.color || "neutral");
    setText(
      "livePlayHead",
      read.headline ||
        (c.bias ? `Scalp: ${c.bias} · 25–35 pts` : "OI board loading…")
    );
    setText(
      "livePlayBody",
      (read.what_next || c.plan_live || "") +
        (read.what_now ? " · " + read.what_now : "")
    );
  }

  renderOiBoard("liveAtmHost", data);
  const orb = proBlocksBySection(data, (s) =>
    /futures ORB|ORB & futures|Index futures ORB/i.test(s)
  );
  renderEdgeBlocksInto("liveOrbBlocks", orb);
}

/** Classic Call | Strike | Put board — only Live Market */
function renderOiBoard(hostId, data) {
  const host = el(hostId);
  if (!host) return;
  host.innerHTML = "";
  const boards = ((data.pro_edge || {}).oi_board || {}).boards || [];
  if (!boards.length) {
    host.innerHTML =
      '<div class="edge-empty">OI chain: set UPSTOX_ACCESS_TOKEN + Refresh. Call left · Strike middle · Put right.</div>';
    return;
  }

  boards.forEach((b) => {
    const wrap = document.createElement("div");
    wrap.className = "sheet-wrap oi-board";
    wrap.style.marginBottom = "16px";

    if (!b.ok) {
      wrap.innerHTML = `<div class="sheet-title">${b.label}</div><div class="edge-empty">${b.error || "No chain"}</div>`;
      host.appendChild(wrap);
      return;
    }

    const read = b.read || {};
    wrap.innerHTML = `
      <div class="sheet-title">
        ${b.label} · Spot ${b.spot != null ? Number(b.spot).toFixed(2) : "—"}
        · exp ${b.expiry || "—"} · PCR ${b.pcr ?? "—"}
        <div class="oi-legend">
          <span class="lg atm">ATM</span>
          <span class="lg support">Support (put wall)</span>
          <span class="lg resist">Resist (call wall)</span>
          <span class="lg maxpain">Max pain</span>
        </div>
      </div>
      <div class="oi-read">
        <div><strong>Ab kya:</strong> ${read.what_now || "—"}</div>
        <div><strong>Aage plan (25–35 pt):</strong> ${read.what_next || "—"}</div>
        <div class="muted">Day OI Δ — CE ${b.tot_ce_day || "—"} · PE ${b.tot_pe_day || "—"}</div>
      </div>
      <div class="table-scroll">
        <table class="sheet compact oi-chain">
          <thead>
            <tr>
              <th class="ce">CE OI</th>
              <th class="ce">CE Δ day</th>
              <th class="ce">CE LTP</th>
              <th class="mid">STRIKE</th>
              <th class="pe">PE LTP</th>
              <th class="pe">PE Δ day</th>
              <th class="pe">PE OI</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
      <p class="note">ATM row pe 5/15/30m OI change tooltips · Green strike = strong support · Red = strong resistance · Purple mark = max pain</p>
    `;
    const tb = wrap.querySelector("tbody");
    (b.rows || []).forEach((r) => {
      const tr = document.createElement("tr");
      if (r.mark_class) tr.className = "row-" + r.mark_class.split(" ")[0];
      const marks = (r.marks || []).join(" · ");
      const strikeCell = `
        <div class="strike-cell ${r.mark_class || ""}">
          <span class="stk">${Number(r.strike).toLocaleString("en-IN")}</span>
          ${marks ? `<span class="stk-mark">${marks}</span>` : ""}
        </div>`;
      const tip =
        r.ce_oi_5m || r.pe_oi_5m
          ? `title="ATM windows — CE OI 5m ${r.ce_oi_5m || "—"} · 15m ${r.ce_oi_15m || "—"} · 30m ${r.ce_oi_30m || "—"} | PE OI 5m ${r.pe_oi_5m || "—"} · 15m ${r.pe_oi_15m || "—"} · 30m ${r.pe_oi_30m || "—"}"`
          : "";
      tr.innerHTML = `
        <td class="ce col-val ${clsFromDisplay(String(r.ce_oi_day), null)}">${r.ce_oi != null ? Number(r.ce_oi).toLocaleString("en-IN") : "—"}</td>
        <td class="ce col-val ${clsFromDisplay(String(r.ce_oi_day), null)}">${r.ce_oi_day || "—"}</td>
        <td class="ce">${r.ce_ltp != null ? Number(r.ce_ltp).toFixed(2) : "—"}</td>
        <td class="mid" ${tip}>${strikeCell}</td>
        <td class="pe">${r.pe_ltp != null ? Number(r.pe_ltp).toFixed(2) : "—"}</td>
        <td class="pe col-val ${clsFromDisplay(String(r.pe_oi_day), null)}">${r.pe_oi_day || "—"}</td>
        <td class="pe col-val ${clsFromDisplay(String(r.pe_oi_day), null)}">${r.pe_oi != null ? Number(r.pe_oi).toLocaleString("en-IN") : "—"}</td>
      `;
      tb.appendChild(tr);
    });
    host.appendChild(wrap);
  });
}

function renderFii(data) {
  const c =
    data.fii_conclusion ||
    (data.pro_edge && data.pro_edge.fii_conclusion) ||
    {};
  const box = el("fiiConclusion");
  if (box) {
    box.className = "playbook " + (c.color || "neutral");
    setText("fiiBiasBadge", c.bias || "FII");
    setText("fiiHeadline", c.headline || "No conclusion yet — Refresh after 7:30 PM");
    setText("fiiOneLiner", c.one_liner || "—");
    setText("fiiPlanPre", c.plan_pre || "—");
    setText("fiiPlanLive", c.plan_live || "—");
    setText("fiiConf", c.confidence != null ? c.confidence + "%" : "—");
    const ul = el("fiiBullets");
    if (ul) {
      ul.innerHTML = "";
      (c.bullets || []).forEach((b) => {
        const li = document.createElement("li");
        li.textContent = b;
        ul.appendChild(li);
      });
    }
  }

  const cash =
    (data.columns || []).find((col) => col.key === "fii_cash_net")?.display ||
    fmt(data.fii_cash_net ?? data.fii_net);
  setText("fiiCash", cash || "—");
  const n = el("fiiCash");
  if (n) n.className = "big " + clsNum(data.fii_cash_net ?? data.fii_net);

  const book = proBlocksBySection(data, (s) => /FII book/i.test(s));
  const score = proBlocksBySection(data, (s) => /scorecard|edge scorecard/i.test(s));
  renderEdgeBlocksInto("fiiBookBlocks", book);
  renderEdgeBlocksInto("fiiScoreBlocks", score);
  renderOi(data);
}

function renderAtmTables(hostId, data) {
  const host = el(hostId);
  if (!host) return;
  host.innerHTML = "";
  const pe = (data && data.pro_edge) || {};
  const list = pe.underlyings || [];
  if (!list.length) {
    host.innerHTML =
      '<div class="edge-empty">ATM±3 table: Upstox token + Refresh. Shows OI & premium Δ 5/15/30m + day.</div>';
    return;
  }
  list.forEach((u) => {
    const wrap = document.createElement("div");
    wrap.className = "sheet-wrap";
    wrap.style.marginBottom = "12px";
    const atm =
      u.atm_strike != null
        ? Number(u.atm_strike).toLocaleString("en-IN")
        : "—";
    wrap.innerHTML = `
      <div class="sheet-title">${u.label || ""} · ATM ${atm} ±3 · exp ${u.expiry || "—"}
        ${u.pcr_now != null ? ` · PCR ${u.pcr_now}` : ""}
        ${u.atm_pcr != null ? ` · ATM PCR ${u.atm_pcr}` : ""}
        <div style="font-weight:400;font-size:11px;color:#5f6368;margin-top:4px">
          Yellow = ATM · OI/Prem Δ vs 5m · 15m · 30m · day open (~9:15)
        </div>
      </div>
      <div class="table-scroll">
        <table class="sheet compact"><thead>
          <tr>
            <th>Strike</th><th>Side</th><th>OI</th><th>Prem</th>
            <th>OI 5m</th><th>OI 15m</th><th>OI 30m</th><th>OI day</th>
            <th>P 5m</th><th>P 15m</th><th>P 30m</th><th>P day</th>
          </tr>
        </thead><tbody></tbody></table>
      </div>`;
    const tb = wrap.querySelector("tbody");
    (u.rows || []).forEach((r) => {
      const tr = document.createElement("tr");
      if (r.is_atm) tr.style.background = "#fef9c3";
      const cells = [
        r.strike,
        r.side,
        r.oi_now != null ? Number(r.oi_now).toLocaleString("en-IN") : "—",
        r.prem_now != null ? Number(r.prem_now).toFixed(2) : "—",
        r.oi_5m, r.oi_15m, r.oi_30m, r.oi_day,
        r.prem_5m, r.prem_15m, r.prem_30m, r.prem_day,
      ];
      tr.innerHTML = cells
        .map((c, i) => {
          const cls = i >= 4 ? clsFromDisplay(String(c), null) : "";
          return `<td class="${cls}">${c ?? "—"}</td>`;
        })
        .join("");
      tb.appendChild(tr);
    });
    host.appendChild(wrap);
  });
}

async function loadStructureDiag() {
  const box = el("structureDiag");
  if (!box) return;
  try {
    const r = await fetch("/api/upstox-status", { cache: "no-store" });
    const j = await r.json();
    if (!j.ok) {
      box.textContent = "Diag failed: " + (j.error || "");
      return;
    }
    const parts = [
      `token: ${j.token_set ? "YES" : "NO"}`,
      `Upstox quotes: ${j.upstox_quotes_ok ? "OK" : "fail"}`,
      `contracts: ${j.option_contracts}`,
      `expiries: ${(j.expiries || []).join(", ") || "—"}`,
      `chain strikes: ${j.option_chain_strikes}`,
    ];
    if (!j.token_set && j.yahoo_nifty) {
      parts.push(`⚠ Live Nifty is Yahoo (${j.yahoo_nifty}) — Structure needs token`);
    }
    if (j.last_error && Object.keys(j.last_error).length) {
      parts.push(`API err: ${JSON.stringify(j.last_error).slice(0, 180)}`);
    }
    parts.push(j.hint || "");
    box.textContent = parts.join(" · ");
    box.style.color = j.option_chain_strikes > 0 ? "#137333" : "#b06000";
  } catch (e) {
    box.textContent = "Diag error: " + e.message;
  }
}

function renderStructure(data) {
  loadStructureDiag();
  // Only summary — full Call|Strike|Put board is on Live Market only
  const blocks = proBlocksBySection(data, (s) =>
    /OI snapshot|Option structure/i.test(s)
  );
  renderEdgeBlocksInto("structureBlocks", blocks);
  const atm = el("structureAtm");
  if (atm) {
    atm.innerHTML =
      '<div class="edge-empty"><strong>Full OI chain (Call | Strike | Put)</strong> ab sirf <em>Live Market</em> tab pe hai — ATM / Support green / Resist red / Max pain mark ke saath.</div>';
  }
}

function renderSnapshot(data) {
  if (!data) return;
  window.__lastSnap = data;
  renderPre(data);
  renderLive(data);
  renderFii(data);
  renderStructure(data);

  const status = el("status");
  if (status) {
    if (!data.upstox_enabled) {
      status.textContent = "OK · set Upstox token for live + structure";
      status.className = "pill warn";
    } else if ((data.errors || []).length) {
      status.textContent = "Partial · " + data.errors.join(", ");
      status.className = "pill warn";
    } else {
      status.textContent = "Ready · tabs by role";
      status.className = "pill ok";
    }
  }
}

function renderOi(data) {
  const week = (data && data.fii_week) || {};
  const sessions = week.sessions || [];
  const summary = week.summary || {};

  const oiMeta = el("oiMeta");
  if (oiMeta) {
    oiMeta.textContent = data && data.oi_date
      ? `Latest OI file: ${data.oi_date} · FII only · last ${sessions.length} sessions · NSE CSV ~7–7:30 PM IST`
      : "Click Refresh to load FII OI week trend from NSE";
  }

  // accuracy cards
  const biasAcc = el("biasAcc");
  const flowAcc = el("flowAcc");
  const biasHits = el("biasHits");
  const flowHits = el("flowHits");
  const explain = el("matchExplain");
  if (biasAcc) {
    biasAcc.textContent =
      summary.bias_accuracy_pct != null
        ? summary.bias_accuracy_pct + "%"
        : "—";
  }
  if (flowAcc) {
    flowAcc.textContent =
      summary.flow_accuracy_pct != null
        ? summary.flow_accuracy_pct + "%"
        : "—";
  }
  if (biasHits) {
    biasHits.textContent =
      summary.bias_total != null
        ? `${summary.bias_hits}/${summary.bias_total} next-day calls correct`
        : "Need ≥2 sessions with next-day close";
  }
  if (flowHits) {
    flowHits.textContent =
      summary.flow_total != null
        ? `${summary.flow_hits}/${summary.flow_total} next-day calls correct`
        : "ΔNet needs prior day OI";
  }
  if (explain && summary.explain) {
    explain.textContent = summary.explain;
  }

  const tbody = el("oiRows");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!sessions.length) {
    tbody.innerHTML =
      '<tr><td colspan="13">No FII OI week data. Click <strong>↻ Refresh</strong>.</td></tr>';
    return;
  }

  sessions.forEach((r, idx) => {
    const tr = document.createElement("tr");
    if (idx === 0) tr.style.background = "#fef7e0";
    const dLong = r.delta_long;
    const dShort = r.delta_short;
    const dNet = r.delta_net;
    tr.innerHTML = `
      <td><strong>${r.oi_date || "—"}</strong></td>
      <td class="col-val">${r.fii_idx_fut_long_display || fmt(r.fii_idx_fut_long)}</td>
      <td class="col-val">${r.fii_idx_fut_short_display || fmt(r.fii_idx_fut_short)}</td>
      <td class="col-val ${clsNum(r.fii_idx_fut_net)}">${fmt(r.fii_idx_fut_net, { digits: 0 })}</td>
      <td class="col-val ${clsNum(dLong)}">${dLong != null ? fmt(dLong, { digits: 0 }) : "—"}</td>
      <td class="col-val ${clsNum(dShort)}">${dShort != null ? fmt(dShort, { digits: 0 }) : "—"}</td>
      <td class="col-val ${clsNum(dNet)}">${dNet != null ? fmt(dNet, { digits: 0 }) : "—"}</td>
      <td>${r.bias_signal || "—"}</td>
      <td style="font-size:11px">${r.flow_signal || "—"}</td>
      <td>${r.next_session || "—"} ${r.next_day_dir ? "(" + r.next_day_dir + ")" : ""}</td>
      <td class="col-val ${clsNum(r.next_day_return_pct)}">${
        r.next_day_return_pct != null
          ? (r.next_day_return_pct > 0 ? "+" : "") + r.next_day_return_pct.toFixed(2) + "%"
          : "—"
      }</td>
      <td>${r.bias_match_label || "—"}</td>
      <td>${r.flow_match_label || "—"}</td>`;
    tbody.appendChild(tr);
  });
}

// Prefer *_display columns (price + chg%) when present
const HIST_COLS = [
  ["date", "Date"],
  ["day", "Day"],
  ["nifty_display", "Nifty", "nifty"],
  ["banknifty_display", "BankNifty", "banknifty"],
  ["sensex_display", "Sensex", "sensex"],
  ["vix_display", "VIX", "vix"],
  ["gift_display", "GIFT", "gift"],
  ["gap_pct", "Gap%"],
  ["gap_category", "GapCat"],
  ["dow_display", "Dow", "dow"],
  ["spx_display", "S&P", "spx"],
  ["nasdaq_display", "Nasdaq", "nasdaq"],
  ["nikkei_display", "Nikkei", "nikkei"],
  ["hsi_display", "HSI", "hsi"],
  ["ftse_display", "FTSE", "ftse"],
  ["dax_display", "DAX", "dax"],
  ["cac_display", "CAC", "cac"],
  ["stoxx50_display", "STOXX50", "stoxx50"],
  ["fii_cash_net", "FII Cash"],
  ["dii_cash_net", "DII Cash"],
  ["fii_idx_fut_long_display", "FII Long (n/%)"],
  ["fii_idx_fut_short_display", "FII Short (n/%)"],
  ["fii_idx_fut_ratio", "L/S Ratio"],
  ["oi_date", "OI Date"],
];

function renderHistory(payload) {
  const head = el("histHead");
  const tbody = el("histRows");
  if (!head || !tbody) return;

  head.innerHTML =
    "<tr>" + HIST_COLS.map((c) => `<th>${c[1]}</th>`).join("") + "</tr>";
  tbody.innerHTML = "";
  (payload.daily || []).forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = HIST_COLS.map((col) => {
      const k = col[0];
      const fallback = col[2];
      let v = r[k];
      if ((v === null || v === undefined || v === "") && fallback) v = r[fallback];
      if (k === "gap_pct" && typeof v === "number")
        v = `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
      else if (typeof v === "number") v = fmt(v);
      else if (v === null || v === undefined || v === "") v = "—";
      const cls = clsFromDisplay(String(v), typeof r[k] === "number" ? r[k] : r[fallback]);
      return `<td class="${cls}">${v}</td>`;
    }).join("");
    tbody.appendChild(tr);
  });
  if (!(payload.daily || []).length) {
    tbody.innerHTML =
      '<tr><td colspan="20">No history yet — click Refresh.</td></tr>';
  }
  const ret = payload.retention || {};
  const note = el("retentionNote");
  if (note) {
    note.textContent = `Columns = one field each. Daily ${ret.daily_days ?? 90}d then weekly rollup (${ret.weekly_weeks ?? 104}w). Local free storage.`;
  }
}

async function loadDocs() {
  const body = el("docsBody");
  if (!body) return;
  try {
    const r = await fetch("/api/docs");
    const j = await r.json();
    if (j.ok && j.html) body.innerHTML = j.html;
    else if (j.ok && j.markdown)
      body.innerHTML = `<pre style="white-space:pre-wrap;font-family:inherit">${escapeHtml(j.markdown)}</pre>`;
    else body.textContent = "Docs empty";
  } catch (e) {
    body.textContent = "Could not load docs: " + e.message;
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadLatest() {
  const r = await fetch("/api/latest");
  if (r.status === 404) {
    await doRefresh();
    return;
  }
  const j = await r.json();
  if (j.ok) renderSnapshot(j.data);
}

async function loadHistory() {
  const r = await fetch("/api/history");
  const j = await r.json();
  if (j.ok) renderHistory(j);
}

async function doRefresh() {
  const btn = el("btnRefresh");
  const status = el("status");
  if (btn) btn.disabled = true;
  if (status) {
    status.textContent = "Refreshing…";
    status.className = "pill";
  }
  try {
    const r = await fetch("/api/refresh", { method: "POST" });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "refresh failed");
    renderSnapshot(j.data);
    await loadHistory();
  } catch (e) {
    if (status) {
      status.textContent = "Error: " + e.message;
      status.className = "pill err";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function wireUi() {
  // Tabs — event delegation (works even if buttons re-rendered)
  const nav = document.querySelector(".tabs");
  if (nav) {
    nav.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tab]");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      switchTab(btn.getAttribute("data-tab"));
    });
  }

  // Also bind each tab directly
  document.querySelectorAll(".tab[data-tab]").forEach((tab) => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      switchTab(tab.getAttribute("data-tab"));
    });
  });

  const btn = el("btnRefresh");
  if (btn) btn.addEventListener("click", (e) => {
    e.preventDefault();
    doRefresh();
  });

  // ensure sheet panel visible initially
  switchTab("pre");
}

// Boot when DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

async function boot() {
  wireUi();
  try {
    await loadLatest();
    await loadHistory();
    await pollLiveIndices(); // first Upstox live tick ASAP
  } catch (e) {
    const status = el("status");
    if (status) {
      status.textContent = String(e);
      status.className = "pill err";
    }
  }
}

// Full heavy refresh every 5 min (FII OI, pro edge, etc.)
setInterval(() => {
  if (document.hidden) return;
  doRefresh().catch(() => {});
}, 5 * 60 * 1000);

function paintLiveTicker(j) {
  const setLive = (id, text, chg) => {
    const n = el(id);
    if (!n) return;
    n.textContent = text || "—";
    n.className = clsFromDisplay(String(text || ""), chg);
  };
  setLive("liveNifty", j.nifty_display, j.nifty_chg_pct);
  setLive("liveBN", j.banknifty_display, j.banknifty_chg_pct);
  setLive("liveSensex", j.sensex_display, j.sensex_chg_pct);
  setLive("liveVix", j.vix_display, j.vix_chg_pct);
  setLive("liveGift", j.gift_display, j.gift_chg_pct);
  const ts = el("liveTs");
  if (ts) ts.textContent = j.last_updated || "";
  const src = el("liveSrc");
  const dot = el("liveDot");
  if (src) {
    const s = (j.source || "").toLowerCase();
    if (s.includes("upstox") && j.upstox) {
      src.textContent = "UPSTOX LIVE";
      src.className = "live-src upstox";
      if (dot) dot.className = "live-dot on";
    } else if (s.includes("yahoo")) {
      src.textContent = "YAHOO FALLBACK";
      src.className = "live-src yahoo";
      if (dot) dot.className = "live-dot warn";
    } else {
      src.textContent = j.upstox === false ? "NO TOKEN" : "LIVE";
      src.className = "live-src";
      if (dot) dot.className = "live-dot err";
    }
  }
  const st = el("status");
  if (st && j.upstox) {
    st.textContent = "Upstox live · " + (j.last_updated || "");
    st.className = "pill ok";
  } else if (st && j.upstox === false) {
    st.textContent = "Set UPSTOX_ACCESS_TOKEN for live";
    st.className = "pill warn";
  }
}

/** Upstox-first live poll — keeps strip + Sheet India cells updating */
async function pollLiveIndices() {
  if (document.hidden) return;
  try {
    const r = await fetch("/api/live", { cache: "no-store" });
    const j = await r.json();
    if (!j || j.ok === false) {
      const dot = el("liveDot");
      if (dot) dot.className = "live-dot err";
      if (j && j.error) {
        const src = el("liveSrc");
        if (src) {
          src.textContent = "ERR";
          src.className = "live-src";
        }
      }
      return;
    }
    paintLiveTicker(j);

    const snap = window.__lastSnap || {};
    ["nifty", "banknifty", "sensex", "vix", "gift"].forEach((k) => {
      if (j[k] != null) snap[k] = j[k];
      if (j[`${k}_display`]) snap[`${k}_display`] = j[`${k}_display`];
      if (j[`${k}_chg_pct`] != null) snap[`${k}_chg_pct`] = j[`${k}_chg_pct`];
      const patch = (c) => {
        if (c.key === k) {
          c.value = j[k];
          c.display = j[`${k}_display`] || c.display;
        }
      };
      (snap.columns || []).forEach(patch);
      (snap.column_groups || []).forEach((g) => (g.columns || []).forEach(patch));
    });
    if (j.last_updated) {
      snap.last_updated = j.last_updated + " · " + (j.source || "live");
    }
    window.__lastSnap = snap;

    // Live tab cards + India group only when Live tab active
    const liveOn = el("panel-live")?.classList.contains("active");
    if (liveOn) {
      renderLive(snap);
    }
    // Keep pre GIFT if live gift updated
    if (j.gift_display && el("panel-pre")?.classList.contains("active")) {
      setText("preGift", j.gift_display);
    }
  } catch (e) {
    const dot = el("liveDot");
    if (dot) dot.className = "live-dot err";
  }
}

// Continuous live: every 10s (Upstox quotes only — cheap)
// Continuous live: every 3s — Upstox quotes (no manual refresh)
const LIVE_MS = 3 * 1000;
setInterval(pollLiveIndices, LIVE_MS);
setTimeout(pollLiveIndices, 500);
