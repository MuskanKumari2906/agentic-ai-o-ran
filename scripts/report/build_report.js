// Builds docs/SecTwin_Implementation_Report.docx from results/*.json and docs/figures/*.png.
// Narrative text that interprets results lives in narrative.json (written after the runs finish);
// every number in tables comes straight from the result files.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, ImageRun, LevelFormat, BorderStyle, PageBreak, Footer, PageNumber, TableOfContents,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const RES = path.join(ROOT, "results");
const FIG = path.join(ROOT, "docs", "figures");
const load = (f) => { const p = path.join(RES, f); return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null; };
const S = load("summary.json") || {};
const E4 = load("e4_twin.json"), E5 = load("e5_cost.json"), E6 = load("e6_rl.json"), NS3 = load("ns3_validation.json");
const NARR = fs.existsSync(path.join(__dirname, "narrative.json")) ? JSON.parse(fs.readFileSync(path.join(__dirname, "narrative.json"), "utf8")) : {};

const FONT = "Calibri";
const W = 9026; // A4 content width in DXA with 1" margins
const pct = (x, d = 1) => (x === null || x === undefined ? "-" : (100 * x).toFixed(d) + "%");
const fx = (x, d = 2) => (x === null || x === undefined ? "-" : Number(x).toFixed(d));

const P = (text, opts = {}) => new Paragraph({ spacing: { after: 120, line: 276 }, ...opts, children: runs(text) });
function runs(text) {
  // **bold** segments
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((t) => t.startsWith("**") ? new TextRun({ text: t.slice(2, -2), bold: true, font: FONT }) : new TextRun({ text: t, font: FONT }));
}
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 280, after: 140 }, children: [new TextRun({ text: t, font: FONT })] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 200, after: 100 }, children: [new TextRun({ text: t, font: FONT })] });
const B = (t) => new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 60 }, children: runs(t) });
const Cap = (t) => new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: t, italics: true, size: 18, font: FONT, color: "4D5866" })] });

function table(header, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: "C9CED6" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (t, i, head) => new TableCell({
    borders, width: { size: widths[i], type: WidthType.DXA },
    shading: head ? { fill: "E8ECF0", type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({ children: [new TextRun({ text: String(t), bold: !!head, size: 17, font: FONT })] })],
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, i, false)) }))],
  });
}

function img(file, wPx, hPx) {
  const p = path.join(FIG, file);
  if (!fs.existsSync(p)) return null;
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 40 },
    children: [new ImageRun({ type: "png", data: fs.readFileSync(p), transformation: { width: wPx, height: hPx },
      altText: { title: file, description: file, name: file } })] });
}

const NAMES = { A0: "Rule-based literal scanner", A1: "LLM only", A2: "LLM + RAG", A3: "Agentic RAG (single agent)",
  A4: "A3 + LLM-only reflection", A5: "A3 + verifier-grounded reflection", A6: "A3 + verifier only",
  A7: "A5 + SMT minimal repair", A5x: "A5 with cross-family critic" };
const ORDER = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A5x"];

const body = [];
// ------------------------------------------------------------------ title
body.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "IMPLEMENTATION AND PILOT RESULTS (ADDENDUM TO THE RESEARCH PROPOSAL)", size: 18, color: "4D5866", font: FONT })] }));
body.push(new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: "SecTwin: A Verifier-Grounded Reflection Agent and Security Digital Twin for O-RAN Compliance", bold: true, size: 34, font: FONT })] }));
body.push(P("Project: Pinnacle Research Project (P32), Agentic AI for O-RAN in 6G. SSN College of Engineering, Department of Information Technology."));
body.push(P(`Document generated ${new Date().toISOString().slice(0, 10)} from the experiment logs in results/. Every number in a table is computed from logged runs.`));

// ------------------------------------------------------------------ 1 summary
body.push(H1("1. Summary"));
(NARR.summary || ["The narrative summary is written after all experiment phases finish; see the tables below for current numbers."]).forEach((t) => body.push(B(t)));
body.push(P("**Status labels used in this addendum** follow the proposal: [PUBLISHED] for cited sources, [PROPOSED] for design choices, [HYPOTHESIS] for expectations, [UNVERIFIED] for unconfirmed material. Results below are **pilot scale** and **simulated** where stated."));

// ------------------------------------------------------------------ 2 built
body.push(H1("2. What was built"));
body.push(table(["Component", "What it does", "Where"], [
  ["Config layer", "libconfig parser for OAI-style gNB files, security view, profile-aware oracle (ground truth), line-level patcher", "sectwin/conf"],
  ["Knowledge base", "34 clauses (TS 33.501 and O-RAN WG11 paraphrases, synthetic Operator Security Baseline, distractors) with SHA-256 provenance manifest", "sectwin/kb"],
  ["Dataset", "62 labelled configurations: clean, vendor default, single, multiple, decoy, context pair, noise; 45 test / 17 dev", "sectwin/dataset, data/"],
  ["Retrieval", "Clause-aware hybrid BM25 + nomic-embed-text with reciprocal-rank fusion", "sectwin/retrieval"],
  ["Agents", "Assessor, query generator, A0 scanner, verifier C1-C5, LLM critic, arms A0-A7 and A5x; local Qwen2.5-7B and Llama-3.1-8B via Ollama", "sectwin/agents"],
  ["SMT repair", "Clause compiler + z3 Optimize: minimal configuration change that satisfies the cited clauses", "sectwin/repair"],
  ["Network twin", "Hexagonal multi-site 5G network, TR 38.901 UMa radio, handover, traffic, throughput/latency, AS security negotiation from each gNB's config, attackers, config drift, SMO loop", "sectwin/twin"],
  ["RL scheduler", "PPO policy deciding when to push verified fixes (exposure vs. disruption)", "sectwin/rl"],
  ["Dashboard", "Network topology, assurance, compliance console, audit trail, experiments, inventory", "ui/, sectwin/api"],
], [1700, 5300, 2026]));
body.push(Cap("Table 1. Components. All software runs locally on one laptop GPU (RTX 4060, 8 GB)."));

// ------------------------------------------------------------------ 3 method
body.push(H1("3. Method"));
body.push(H2("3.1 Ground truth and deployment profiles"));
body.push(P("[PROPOSED] A profile has two dimensions: whether unauthenticated emergency sessions are a regulatory requirement (from TS 33.501), and the baseline, either standards minimum or a stricter, explicitly synthetic Operator Security Baseline (OSB-1 to OSB-5). The same file can therefore be compliant under one profile and non-compliant under another; eight context-pair items test exactly this. drb_integrity = \"no\" is compliant under every profile because user-plane integrity is optional to use; it is the main decoy (gap G4 in the proposal)."));
body.push(P("The oracle that labels the dataset is never available to an arm. The verifier's re-scan in C5 uses the naive A0 scanner, and A7's repair compiles only the clauses an arm itself cited."));
body.push(H2("3.2 Reflection Agent"));
body.push(table(["Check", "Deterministic test (no LLM)"], [
  ["C1 schema", "Output validates against the Assessment schema"],
  ["C2 grounding", "Flagged parameter exists with the stated value and line"],
  ["C3 citation", "Clause was retrieved, its hash matches the trusted manifest, and the quote is in the clause text (fuzzy >= 90)"],
  ["C4 strength / applicability", "A violation needs a shall / shall-not usage sentence about this parameter; rejects 'shall support' capability sentences, conditional 'when ... is used' requirements for switched-off features, algorithm sentences cited against on/off switches, and requirements already met by the current value"],
  ["C5 fix", "Legal value, file still parses, only flagged lines change, literal re-scan finds nothing new"],
  ["LLM critic", "Looks for missed violations and scope errors; each claim must itself pass C3 and C4 before it is fed back"],
], [2300, 6726]));
body.push(Cap("Table 2. Two-stage Reflection Agent. Findings still unverified after three rounds are dropped and the case is escalated."));
body.push(H2("3.3 Arms and metrics"));
body.push(table(["Arm", "Configuration"], ORDER.map((a) => [a, NAMES[a]]), [900, 8126]));
body.push(P("Metrics: configuration-level accuracy, exact match of the violation set, parameter-level precision / recall / F1, citation correctness (clause exists, quote found, and the clause is one of the oracle's governing clauses for that parameter), fix correctness on non-compliant files (all violations resolved, none introduced, every UE capability class can still attach), unnecessary-change rate on compliant files, reflection flips (wrong-to-right vs right-to-wrong per parameter), latency and tokens. Uncertainty: 95% bootstrap intervals over configurations and exact McNemar tests on paired per-configuration outcomes."));

// ------------------------------------------------------------------ 4 results
body.push(H1("4. Results: compliance agents"));
const e1 = S.e1 || {};
if (e1.arms) {
  body.push(H2("4.1 E1: detection, citation and fix quality"));
  const rows = ORDER.filter((a) => e1.arms[a]).map((a) => { const r = e1.arms[a]; const ci = r.f1_ci || [null, null];
    return [a, r.n, pct(r.config_accuracy), pct(r.exact_match), fx(r.precision), fx(r.recall), `${fx(r.f1)} [${fx(ci[0])}, ${fx(ci[1])}]`,
      pct(r.citation_correct), pct(r.fix_correct), pct(r.unnecessary_change_rate), ["A4", "A5", "A6", "A7", "A5x"].includes(a) ? `${r.wrong_to_right}/${r.right_to_wrong}` : "-", r.seconds_mean.toFixed(0)]; });
  body.push(table(["Arm", "Runs", "Cfg acc.", "Exact", "Prec.", "Rec.", "F1 [95% CI]", "Cite ok", "Fix ok", "Unneeded", "Flips W>R/R>W", "s"], rows,
    [520, 520, 720, 680, 600, 600, 1400, 760, 720, 840, 1006, 660]));
  body.push(Cap("Table 3. E1 on the held-out test split. Fix ok is measured on non-compliant files, Unneeded on compliant files."));
  const f = img("e1_quality.png", 600, 221); if (f) { body.push(f); body.push(Cap("Figure 1. Detection quality by arm.")); }
  const g = img("e1_categories.png", 470, 220); if (g) { body.push(g); body.push(Cap("Figure 2. Exact-match accuracy by configuration category.")); }
  (NARR.e1 || []).forEach((t) => body.push(P(t)));
  if (e1.mcnemar_exact_set) {
    body.push(table(["Comparison", "Only first correct", "Only second correct", "p (exact McNemar)"],
      Object.entries(e1.mcnemar_exact_set).map(([k, v]) => [k, v.a_only, v.b_only, v.p]), [3000, 2000, 2000, 2026]));
    body.push(Cap("Table 4. Paired tests on per-configuration exact-match correctness."));
  }
}
if (S.e2 && Object.keys(S.e2).length) {
  body.push(H2("4.2 E2: metamorphic robustness and prompt injection"));
  const V = ["reorder", "noise", "comments", "inject"];
  body.push(table(["Arm", "Group order", "Extra settings", "Comments changed", "Injected auditor note"],
    Object.entries(S.e2).map(([a, vs]) => [a, ...V.map((v) => vs[v] ? `${pct(vs[v].consistency, 0)} (acc ${pct(vs[v].accuracy, 0)})` : "-")]),
    [900, 2000, 2000, 2000, 2126]));
  body.push(Cap("Table 5. Share of runs whose verdict is unchanged versus the original file (accuracy on the variant in brackets)."));
  (NARR.e2 || []).forEach((t) => body.push(P(t)));
}
if (S.e3 && Object.keys(S.e3).length) {
  body.push(H2("4.3 E3: poisoned knowledge base"));
  body.push(table(["Arm", "Runs", "Poison retrieved", "Findings citing poison", "Verdict changed", "Correct to wrong", "Accuracy"],
    Object.entries(S.e3).map(([a, r]) => [a, r.runs, r.runs_with_poison_retrieved, r.confirmed_findings_citing_poison, r.verdict_changed_vs_clean, r.correct_to_wrong_vs_clean, pct(r.accuracy_poisoned, 0)]),
    [800, 800, 1300, 1700, 1500, 1500, 1426]));
  body.push(Cap("Table 6. Five fake or tampered clauses added to the corpus; the trusted manifest is unchanged."));
  (NARR.e3 || []).forEach((t) => body.push(P(t)));
}

// ------------------------------------------------------------------ 5 twin
body.push(H1("5. Network digital twin"));
body.push(P("[PROPOSED] The twin answers the question the proposal could not: what a compliance error costs in a running network. Each gNB carries a full configuration file; at every attach and handover the gNB selects the first algorithm in its configured list that the UE supports (TS 33.501 6.7.3). A wrong configuration therefore produces null-ciphered user traffic, RRC signalling on NIA0 (spoofable), or UEs that cannot attach."));
body.push(table(["Aspect", "Model"], [
  ["Layout", "Hexagonal tri-sector macro grid, configurable sites (7/19/37) and inter-site distance; 3.5 GHz, 100 MHz, 49 dBm per sector"],
  ["Propagation", "TR 38.901 UMa path loss (LOS-probability weighted), 6 dB shadowing, 50 m decorrelation, 0.5 inter-site correlation, 3GPP sector pattern"],
  ["Link and scheduling", "0.75 x Shannon capped at 7.4 b/s/Hz, rank 2 above 12 dB, 14% overhead; water-filling time-share scheduler per cell"],
  ["Mobility", "Static, pedestrian (0.8-1.8 m/s), vehicular (8-17 m/s) random waypoint; A3 handover (4 dB, L3 filter, TTT); T310-style RLF"],
  ["Traffic", "Video, web, VoIP, IoT, bulk, fixed wireless access with a diurnal busy-hour profile; TCP-limited queues"],
  ["Security", "Algorithm selection from each gNB's file at attach and handover; PDCP MAC-I overhead when UP integrity is on; IPsec processing on N3"],
  ["Threats", "Passive sniffer, RRC injector (succeeds only against NIA0), backhaul tap (N3 without IPsec), O1 man-in-the-middle pushing malicious configs over plaintext O1"],
  ["SMO loop", "O1 change notification, one assessment at a time on the GPU, human approval delay, remediation policy, outage on push, 24 h manual audit"],
], [1900, 7126]));
body.push(Cap("Table 7. Twin model summary (system-level simulator, not a protocol stack)."));
if (NS3) {
  const f = img("ns3_sinr_cdf.png", 420, 250); if (f) { body.push(f); body.push(Cap("Figure 3. Downlink SINR distribution of the twin against ns-3 5G-LENA (3GPP calibration example) on the same layout.")); }
  const keys = Object.keys(NS3.sinr);
  const lab = { twin: "SecTwin", ns3_default: "ns-3 default", ns3_matched: "ns-3 1x1 omni", ns3_closest: "ns-3 closest" };
  const wq = Math.floor((9026 - 3000) / keys.length);
  body.push(table(["Quantity", ...keys.map((k) => lab[k] || k)], Object.entries(NS3.rows).map(([k, r]) => [k, ...keys.map((c) => r[c] ?? "-")]), [3000, ...keys.map(() => wq)]));
  body.push(Cap("Table 8. Radio cross-check against ns-3 5G-LENA (3GPP outdoor calibration example)."));
  (NS3.notes || []).forEach((t) => body.push(B(t)));
  (NARR.ns3 || []).forEach((t) => body.push(P(t)));
}
if (E5) {
  body.push(H2("5.1 E5: cost of security features"));
  body.push(table(["Setting", "Goodput ratio", "VoIP header overhead", "Latency p50 / p95 / p99 (ms)"],
    E5.rows.map((r) => [r.name, pct(r.goodput_ratio, 2), pct(r.voip_overhead, 2), `${r.latency_p50_ms} / ${r.latency_p95_ms} / ${r.latency_p99_ms}`]), [3400, 1700, 1800, 2126]));
  body.push(Cap("Table 9. Busy hour, 19 sites, 1500 UEs, 20 simulated minutes per setting."));
  (NARR.e5 || []).forEach((t) => body.push(P(t)));
}
if (E4) {
  body.push(H2("5.2 E4: closed loop, compliance agent inside the network"));
  body.push(table(["Arm", "Unciph. UE-h", "Spoofable UE-h", "GB intercepted", "Attacks succeeded", "MTTR (s)", "Pushes (unneeded)", "Outage UE-h", "Left to audit"],
    Object.entries(E4.arms).map(([a, r]) => [a, r.unciphered_active_ue_hours, r.spoofable_ue_hours, r.gb_intercepted, r.attack_success, r.mttr_s ?? "-", `${r.pushes} (${r.unnecessary_pushes})`, r.remediation_outage_ue_hours, r.missed_until_audit]),
    [700, 1050, 1100, 1050, 1050, 900, 1200, 1000, 976]));
  body.push(Cap(`Table 10. ${E4.hours} simulated hours per arm with an identical seed (same mobility, traffic, drift and attacks). Agent outcomes and latencies are replayed from E1 measurements.`));
  const f = img("e4_closed_loop.png", 620, 180); if (f) { body.push(f); body.push(Cap("Figure 4. Exposure and disruption per arm.")); }
  const g = img("e4_timeline.png", 520, 194); if (g) { body.push(g); body.push(Cap("Figure 5. Active UEs on an unciphered user plane over time.")); }
  (NARR.e4 || []).forEach((t) => body.push(P(t)));
}
if (E6) {
  body.push(H2("5.3 E6: learning when to remediate"));
  body.push(table(["Policy", "Exposure UE-h", "Disruption UE-h", "Pushes", "Reward (mean ± sd)"],
    Object.entries(E6.policies).map(([k, r]) => [k, fx(r.exposure_ue_h, 1), fx(r.disruption_ue_h, 2), fx(r.pushes, 1), `${fx(r.reward, 1)} ± ${fx(r.reward_std, 1)}`]), [2600, 1500, 1600, 1100, 2226]));
  if (E6.paired_vs_ppo) {
    body.push(table(["PPO compared with", "Mean reward gain", "95% CI", "PPO better in"],
      Object.entries(E6.paired_vs_ppo).map(([k, v]) => [k, fx(v.mean_reward_gain, 1), `[${fx(v.ci95[0], 1)}, ${fx(v.ci95[1], 1)}]`, pct(v.ppo_better_share, 0)]), [2800, 2000, 2200, 2026]));
  }
  body.push(Cap(`Table 11. ${E6.episodes || 200} paired 24-hour episodes. ${E6.note || ""}`));
  const f = img("e6_rl.png", 560, 185); if (f) { body.push(f); body.push(Cap("Figure 6. Exposure and disruption by remediation policy.")); }
  (NARR.e6 || []).forEach((t) => body.push(P(t)));
}

// ------------------------------------------------------------------ 6 limits
body.push(H1("6. Limitations and threats to validity"));
[
  "Clause texts for TS 33.501 and O-RAN WG11 are paraphrases [UNVERIFIED]; the C3 quote check runs on whatever text is in the knowledge base, so replacing it with the official sentences needs no code change, but all citation results must be re-run afterwards.",
  "The dataset is synthetic and oracle-labelled, with one annotator (the oracle). The proposal's two-annotator protocol has not been carried out.",
  "Pilot scale: 45 test configurations and one to two repeats per arm. Intervals are wide; differences whose interval includes zero are reported as unresolved.",
  "The local 7B model is much smaller than the models in the closest published work; absolute accuracy is not comparable, only relative effects between arms.",
  "The twin is a system-level simulator; absolute KPIs are indicative. Comparisons between arms and policies on identical seeds are the meaningful output.",
  "The interface_security block and the Operator Security Baseline are project constructs, not part of OAI or any standard.",
  "The RL environment's severity weights are a modelling choice; the learned policy is valid for this environment only.",
].forEach((t) => body.push(B(t)));

// ------------------------------------------------------------------ 7 reproduce
body.push(H1("7. Reproducing the results"));
[
  "python -m sectwin.dataset.generate",
  "bash scripts/run_shard.sh 0/2  and  bash scripts/run_shard.sh 1/2   (E1-E3, resumable)",
  "python -m sectwin.eval.twin_experiments e5 ;  python -m sectwin.rl.train 400000 ;  python -m sectwin.eval.twin_experiments e4 6",
  "python -m sectwin.eval.analyze ;  python scripts/make_figures.py ;  node scripts/report/build_report.js",
  "python -m uvicorn sectwin.api.server:app --port 8600   (dashboard at http://localhost:8600)",
].forEach((t) => body.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: t, font: "Consolas", size: 18 })] })));

const doc = new Document({
  creator: "SecTwin", title: "SecTwin: Implementation and Pilot Results",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, font: FONT, color: "1D242C" }, paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 23, bold: true, font: FONT, color: "0B5F8C" }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{
    properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "SecTwin pilot results  |  page ", size: 16, color: "7A8594" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "7A8594" })] })] }) },
    children: body,
  }],
});

const out = path.join(ROOT, "docs", "SecTwin_Implementation_Report.docx");
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log("written", out); });
