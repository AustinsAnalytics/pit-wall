const $ = (s) => document.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const pct = (x, d = 0) => (100 * x).toFixed(d) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const show = (v) => (Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
let D = null;

function theme() {
  const saved = (() => { try { return localStorage.getItem("pw-theme"); } catch { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("pw-theme", document.documentElement.dataset.theme); } catch { /* private mode */ }
    charts();
  });
}

function seg(el, options, value, onChange) {
  el.innerHTML = "";
  options.forEach(([v, label]) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label; b.setAttribute("aria-pressed", String(v === value));
    b.onclick = () => { [...el.children].forEach((x) => x.setAttribute("aria-pressed", "false")); b.setAttribute("aria-pressed", "true"); onChange(v); };
    el.appendChild(b);
  });
}

function kpis() {
  const s = D.evals.summary, m = D.model.metrics;
  $("#k-pass").textContent = `${s.passed}/${s.questions}`;
  $("#k-traps").textContent = `${s.traps_passed}/${s.traps}`;
  $("#k-cite").textContent = `${s.cited_sql_reproduced}/${s.answers_citing_sql}`;
  $("#k-races").textContent = D.build.points_races;
  $("#k-rows").textContent = D.build.results_rows.toLocaleString();
  $("#k-auc").textContent = m.model.auc.toFixed(2);
  $("#k-auc-base").textContent = m.starting_spot_only.auc.toFixed(2);
  $("#asof").textContent = "Results through " + new Date(D.model.form_as_of).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function tables() {
  $("#t-tools").innerHTML = `<thead><tr><th>Tool</th><th>What it does</th></tr></thead><tbody>${D.tools.map((t) =>
    `<tr><td><code>${esc(t.name)}</code></td><td>${esc(t.description)}</td></tr>`).join("")}</tbody>`;
  const evals = (f) => {
    const rows = D.evals.results.filter((r) => f === "all" || (f === "traps" ? r.trap : !r.trap));
    $("#t-evals").innerHTML = `<thead><tr><th>#</th><th>Question</th><th>Tool</th><th>Answer</th><th>Trusted SQL</th><th>Correct</th><th>Cited SQL reproduces it</th><th class="r">ms</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${r.id}</td><td>${esc(r.question.replace("TRAP: ", ""))}${r.trap ? ' <span class="pill">trap</span>' : ""}</td>
      <td><code>${esc(r.tool)}</code></td><td>${esc(show(r.answer))}</td><td>${esc(show(r.trusted))}</td>
      <td class="${r.pass ? "pass" : "fail"}">${r.pass ? "✓" : "✗"}</td>
      <td>${r.cited_sql_reproduces === true ? '<span class="pass">✓</span>' : r.cited_sql_reproduces === false ? '<span class="fail">✗</span>' : '<span class="muted">asks / refuses</span>'}</td>
      <td class="r">${r.ms}</td></tr>`).join("")}</tbody>`;
  };
  seg($("#v-filter"), [["all", "All 25"], ["questions", "Business questions"], ["traps", "Traps"]], "all", evals);
  evals("all");
  const T = D.traps, lead22 = T.wins_leader_by_season.find((x) => x.season === 2022);
  const cards = [
    ["Exhibition races aren't wins", `Counting every race in the results table adds <b>${T.exhibition_wins_added} wins</b> from the Clash, the Daytona Duels and All-Star races, and changes ${T.driver_seasons_changed} driver-season totals. In 2022 it makes ${lead22.naive.join(" and ")} co-leaders; the correct answer is ${lead22.correct.join(", ")} alone. Ryan Preece's 2026: ${T.preece_2026_naive_vs_correct[0]} wins naive, ${T.preece_2026_naive_vs_correct[1]} correct.`],
    ["Names that mean two people", `${T.shared_last_names.filter((n) => n !== "Jr").length} last names belong to more than one driver in this data (${T.shared_last_names.filter((n) => n !== "Jr").join(", ")}), and "Jr" suffixes break naive last-name matching. The tools return the options instead of picking one.`],
    ["Tracks that host two races", `${T.two_race_tracks_2026} tracks held two points races in 2026. "Who won at Talladega?" has two answers; the race tool asks which one. "Charlotte" means the oval unless the Roval is named.`],
    ["Read-only, always", `The SQL tool runs one SELECT at a time on a read-only connection. Writes, stacked statements and settings are refused, and those refusals are part of the test suite. ${T.blank_status_rows_points_races} finishes with a blank status are treated as unknown, not as DNFs.`],
  ];
  $("#trap-cards").innerHTML = cards.map(([h, b]) => `<div class="card trap"><h3 style="margin-top:0">${h}</h3><p style="margin:0">${b}</p></div>`).join("");
  const m = D.model.metrics;
  $("#model-text").innerHTML = `On 2026 it beats the starting grid on every measure: AUC ${m.model.auc.toFixed(3)} vs ${m.starting_spot_only.auc.toFixed(3)}, log loss ${m.model.log_loss.toFixed(3)} vs ${m.starting_spot_only.log_loss.toFixed(3)}. Pick the model's 10 most likely drivers in each race and ${pct(m.model.top10_picks_hit_rate)} of them finish in the top 10, against ${pct(m.starting_spot_only.top10_picks_hit_rate)} for the first 10 cars on the grid. Racing is noisy, so the edge is modest, and the page says so.`;
  $("#t-metrics").innerHTML = `<thead><tr><th>2026 test (${D.model.test.races} races)</th><th class="r">AUC</th><th class="r">Log loss</th><th class="r">Brier</th></tr></thead><tbody>
    ${[["Model", m.model], ["Starting spot only", m.starting_spot_only], ["Same rate for everyone", m.constant_rate]].map(([n, x]) =>
      `<tr><td>${n}</td><td class="r">${x.auc.toFixed(3)}</td><td class="r">${x.log_loss.toFixed(3)}</td><td class="r">${x.brier.toFixed(3)}</td></tr>`).join("")}</tbody>`;
  const E = D.excitement.rows, ss = E.find((x) => x.track_type === "superspeedway"), it = E.find((x) => x.track_type === "intermediate");
  $("#fans-text").innerHTML = `<p>Superspeedways are a different sport: <b>${ss.avg_lead_changes} lead changes</b> a race, and <b>${ss.pct_photo_finish}%</b> decided by less than a tenth of a second. Intermediates, the most common track type (${it.races} races), average ${it.avg_lead_changes} lead changes and ${it.pct_photo_finish}% photo finishes.</p>
    <p>For a fan-engagement team this suggests where to point promotion: the superspeedway races are close to a coin flip at the line, which is exactly what drives tune-in late in a race. A natural next step with internal data would join these race traits to viewership and ticketing to test it.</p>`;
  $("#t-defs").innerHTML = `<tbody>${Object.entries(D.definitions).map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td>${esc(v)}</td></tr>`).join("")}</tbody>`;
  $("#ex-dillon").textContent = JSON.stringify(D.examples.dillon, null, 2);
  const b = { ...D.examples.byron }; delete b.driver_id;
  $("#ex-byron").textContent = JSON.stringify(b, null, 2);
  const t = { ...D.examples.top10[0] }; delete t.inputs;
  $("#ex-top10").textContent = JSON.stringify(t, null, 2);
}

function frame(el, h, m) {
  el.innerHTML = "";
  const w = Math.max(280, el.clientWidth);
  const svg = d3.select(el).append("svg").attr("width", w).attr("height", h);
  return { svg, g: svg.append("g").attr("transform", `translate(${m.l},${m.t})`), w: w - m.l - m.r, h: h - m.t - m.b };
}

function charts() {
  if (!D) return;
  const C = D.model.calibration;
  let f = frame($("#ch-calib"), 280, { t: 10, r: 16, b: 42, l: 52 });
  const x = d3.scaleLinear([0, 1], [0, f.w]), y = d3.scaleLinear([0, 1], [f.h, 0]);
  f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.h})`).call(d3.axisBottom(x).ticks(5).tickFormat((d) => pct(d)));
  f.g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(5).tickFormat((d) => pct(d)));
  f.g.append("line").attr("x1", x(0)).attr("y1", y(0)).attr("x2", x(1)).attr("y2", y(1)).attr("stroke", css("--rule")).attr("stroke-width", 2);
  f.g.selectAll("circle").data(C).join("circle").attr("cx", (d) => x(d.pred)).attr("cy", (d) => y(d.actual))
    .attr("r", (d) => 3 + Math.sqrt(d.n) / 3).attr("fill", css("--chart-1")).attr("opacity", 0.85)
    .append("title").text((d) => `Predicted ${pct(d.pred, 1)}, actual ${pct(d.actual, 1)} (${d.n} drivers)`);
  f.g.append("text").attr("x", f.w / 2).attr("y", f.h + 36).attr("text-anchor", "middle").text("Predicted chance of a top 10");
  const E = D.excitement.rows;
  f = frame($("#ch-fans"), 300, { t: 10, r: 60, b: 30, l: 110 });
  const yb = d3.scaleBand(E.map((d) => d.track_type), [0, f.h]).padding(0.3);
  const xb = d3.scaleLinear([0, d3.max(E, (d) => d.avg_lead_changes) * 1.1], [0, f.w]);
  f.g.append("g").attr("class", "axis").call(d3.axisLeft(yb).tickFormat((d) => d.replace("_", " ")));
  f.g.append("g").attr("class", "axis").attr("transform", `translate(0,${f.h})`).call(d3.axisBottom(xb).ticks(5));
  f.g.selectAll("rect").data(E).join("rect").attr("y", (d) => yb(d.track_type)).attr("height", yb.bandwidth())
    .attr("width", (d) => xb(d.avg_lead_changes)).attr("rx", 3).attr("fill", css("--chart-1"));
  f.g.selectAll(".lab").data(E).join("text").attr("class", "lab").attr("x", (d) => xb(d.avg_lead_changes) + 6)
    .attr("y", (d) => yb(d.track_type) + yb.bandwidth() / 2 + 4).text((d) => `${d.avg_lead_changes} · ${d.pct_photo_finish}% photo`);
}

fetch("data.json").then((r) => r.json()).then((d) => { D = d; kpis(); tables(); charts(); });
theme();
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(charts, 150); });
