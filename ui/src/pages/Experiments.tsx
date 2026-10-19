import { useEffect, useMemo, useState } from "react";
import Chart, { axis } from "../Chart";
import { ARM_NAMES, get, pct, post } from "../api";

const ARM_ORDER = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A5x"];
const CATS = ["clean", "vendor_default", "single", "multi", "decoy", "context", "noise"];
const CAT_LABEL: Record<string, string> = { clean: "Clean", vendor_default: "Vendor default", single: "Single", multi: "Multiple", decoy: "Decoy", context: "Context", noise: "Noise" };

export default function Experiments() {
  const [s, setS] = useState<any>(null);
  const [prog, setProg] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const load = () => get("/api/results").then(setS).catch(() => setS(null));
  useEffect(() => { load(); get("/api/progress").then(setProg); }, []);
  const refresh = async () => { setBusy(true); try { setS(await post("/api/results/refresh")); } finally { setBusy(false); } get("/api/progress").then(setProg); };

  const arms = s?.e1?.arms || {};
  const present = ARM_ORDER.filter((a) => arms[a]);

  const f1Opt = useMemo(() => ({
    tooltip: { trigger: "axis" },
    legend: { top: 0, right: 8, textStyle: { fontSize: 11 } },
    grid: { left: 44, right: 14, top: 30, bottom: 30 },
    xAxis: { type: "category", data: present, ...axis },
    yAxis: { type: "value", min: 0, max: 1, ...axis },
    series: [
      { name: "Violation F1", type: "bar", barWidth: 14, data: present.map((a) => +arms[a].f1.toFixed(3)) },
      { name: "Exact-match accuracy", type: "bar", barWidth: 14, data: present.map((a) => +arms[a].exact_match.toFixed(3)) },
      { name: "Fix correct", type: "bar", barWidth: 14, data: present.map((a) => +(arms[a].fix_correct ?? 0).toFixed(3)) },
    ],
  }), [s]);

  const costOpt = useMemo(() => ({
    tooltip: { trigger: "item", formatter: (p: any) => `${p.data[2]}<br/>F1 ${p.data[1]}<br/>${p.data[0]} s per config` },
    grid: { left: 44, right: 20, top: 20, bottom: 36 },
    xAxis: { type: "value", name: "seconds per configuration (local 7B)", nameLocation: "middle", nameGap: 22, ...axis },
    yAxis: { type: "value", name: "F1", min: 0, max: 1, ...axis },
    series: [{ type: "scatter", symbolSize: 9, label: { show: true, formatter: (p: any) => p.data[2], position: "right", fontSize: 11 },
      data: present.map((a) => [+arms[a].seconds_mean.toFixed(1), +arms[a].f1.toFixed(3), a]) }],
  }), [s]);

  const catOpt = useMemo(() => {
    const bc = s?.e1?.by_category || {};
    const data: any[] = [];
    present.forEach((a, i) => CATS.forEach((c, j) => { const v = bc[a]?.[c]; if (v !== undefined) data.push([j, i, +v.toFixed(2)]); }));
    return {
      tooltip: { formatter: (p: any) => `${present[p.data[1]]} on ${CAT_LABEL[CATS[p.data[0]]]}: ${pct(p.data[2], 0)}` },
      grid: { left: 44, right: 14, top: 10, bottom: 52 },
      xAxis: { type: "category", data: CATS.map((c) => CAT_LABEL[c]), ...axis, axisLabel: { ...axis.axisLabel, rotate: 30 } },
      yAxis: { type: "category", data: present, ...axis },
      visualMap: { min: 0, max: 1, show: false, inRange: { color: ["#f3d9d5", "#f6f0e1", "#dcebdd", "#7fb685"] } },
      series: [{ type: "heatmap", data, label: { show: true, fontSize: 10.5, formatter: (p: any) => (100 * p.data[2]).toFixed(0) } }],
    };
  }, [s]);

  return (
    <>
      <div className="page-h">
        <h1>Experiments</h1>
        <span className="sub">Controlled comparison of agent configurations on the held-out test split (pilot scale)</span>
        <div className="right">
          {prog?.phase && <span className="muted small">Runner: {prog.phase} {prog.phase_done}/{prog.phase_total}</span>}
          <button className="btn" onClick={refresh} disabled={busy}>{busy ? "Recomputing..." : "Recompute from logs"}</button>
        </div>
      </div>
      {!present.length ? <div className="panel"><div className="empty">No results yet. The experiment runner writes results/e1_runs*.jsonl; press Recompute.</div></div> : (
        <>
          <div className="panel" style={{ marginBottom: 12 }}>
            <div className="ph"><h3>E1. Arms A0 to A7: detection, citation and fix quality</h3><span className="r">{s.counts.e1_runs} runs &middot; 95% bootstrap CI over configurations</span></div>
            <div className="pb flush scroll">
              <table className="t">
                <thead><tr>
                  <th>Arm</th><th>Configuration</th><th className="num">Runs</th><th className="num">Config acc.</th><th className="num">Exact match</th>
                  <th className="num">Precision</th><th className="num">Recall</th><th className="num">F1 [95% CI]</th><th className="num">Citation correct</th>
                  <th className="num">Fix correct</th><th className="num">Unneeded change</th><th className="num">Flips W→R / R→W</th><th className="num">Escalated</th><th className="num">Time (s)</th><th className="num">Tokens</th>
                </tr></thead>
                <tbody>
                  {present.map((a) => { const r = arms[a]; return (
                    <tr key={a}>
                      <td><b>{a}</b></td><td>{ARM_NAMES[a]}</td><td className="num">{r.n}</td>
                      <td className="num">{pct(r.config_accuracy)}</td><td className="num">{pct(r.exact_match)}</td>
                      <td className="num">{r.precision.toFixed(2)}</td><td className="num">{r.recall.toFixed(2)}</td>
                      <td className="num"><b>{r.f1.toFixed(2)}</b> <span className="muted">[{r.f1_ci?.map((x: number) => x.toFixed(2)).join(", ")}]</span></td>
                      <td className="num">{r.citation_correct == null ? "-" : pct(r.citation_correct)}</td>
                      <td className="num">{pct(r.fix_correct)}</td><td className="num">{pct(r.unnecessary_change_rate)}</td>
                      <td className="num">{["A4", "A5", "A6", "A7", "A5x"].includes(a) ? `${r.wrong_to_right} / ${r.right_to_wrong}` : "-"}</td>
                      <td className="num">{pct(r.escalation_rate, 0)}</td>
                      <td className="num">{r.seconds_mean.toFixed(1)}</td><td className="num">{Math.round(r.tokens_mean)}</td>
                    </tr>); })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="grid g3" style={{ marginBottom: 12 }}>
            <div className="panel"><div className="ph"><h3>Quality by arm</h3></div><div className="pb"><Chart option={f1Opt} height={250} /></div></div>
            <div className="panel"><div className="ph"><h3>Quality vs. cost</h3></div><div className="pb"><Chart option={costOpt} height={250} /></div></div>
            <div className="panel"><div className="ph"><h3>Exact-match accuracy by category (%)</h3></div><div className="pb"><Chart option={catOpt} height={250} /></div></div>
          </div>
          <div className="grid g2" style={{ marginBottom: 12 }}>
            <div className="panel">
              <div className="ph"><h3>Paired tests (exact McNemar, per configuration)</h3></div>
              <div className="pb flush">
                <table className="t small">
                  <thead><tr><th>Comparison</th><th className="num">Only first correct</th><th className="num">Only second correct</th><th className="num">p</th><th>Reading</th></tr></thead>
                  <tbody>
                    {Object.entries(s.e1.mcnemar_exact_set || {}).map(([k, v]: any) => (
                      <tr key={k}><td>{k}</td><td className="num">{v.a_only}</td><td className="num">{v.b_only}</td><td className="num">{v.p}</td>
                        <td>{v.p < 0.05 ? <span className="st info">difference</span> : <span className="muted">not resolved at this sample size</span>}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <E2E3 s={s} />
          </div>
          <TwinResults s={s} />
        </>
      )}
      <p className="note">
        Pilot-scale results on a synthetic, oracle-labelled dataset with paraphrased clause texts; a local 7B model; simulated network.
        Confidence intervals are wide by design of the sample size; differences whose interval includes zero are reported as not resolved.
      </p>
    </>
  );
}

function E2E3({ s }: any) {
  const e2 = s.e2 || {}, e3 = s.e3 || {};
  const variants = ["reorder", "noise", "comments", "inject"];
  const VL: Record<string, string> = { reorder: "Group order", noise: "Extra settings", comments: "Comments changed", inject: "Prompt injection in comment" };
  return (
    <div className="panel">
      <div className="ph"><h3>E2 robustness and E3 knowledge-base poisoning</h3></div>
      <div className="pb flush">
        <table className="t small">
          <thead><tr><th>E2: verdict unchanged under</th>{["A0", "A3", "A5"].map((a) => <th key={a} className="num">{a}</th>)}</tr></thead>
          <tbody>{variants.map((v) => (
            <tr key={v}><td>{VL[v]}</td>{["A0", "A3", "A5"].map((a) => <td key={a} className="num">{e2[a]?.[v] ? `${pct(e2[a][v].consistency, 0)} (acc ${pct(e2[a][v].accuracy, 0)})` : "-"}</td>)}</tr>
          ))}</tbody>
        </table>
        <table className="t small" style={{ marginTop: 8 }}>
          <thead><tr><th>E3: poisoned KB</th>{["A3", "A4", "A5"].map((a) => <th key={a} className="num">{a}</th>)}</tr></thead>
          <tbody>
            {[["runs", "Runs"], ["runs_with_poison_retrieved", "Poison retrieved"], ["confirmed_findings_citing_poison", "Findings citing poison"],
              ["verdict_changed_vs_clean", "Verdict changed vs clean KB"], ["correct_to_wrong_vs_clean", "Correct to wrong"], ["accuracy_poisoned", "Accuracy (poisoned)"]].map(([k, l]) => (
              <tr key={k}><td>{l}</td>{["A3", "A4", "A5"].map((a) => <td key={a} className="num">{e3[a] ? (k === "accuracy_poisoned" ? pct(e3[a][k], 0) : e3[a][k]) : "-"}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TwinResults({ s }: any) {
  const e4 = s.e4, e5 = s.e5, e6 = s.e6;
  if (!e4 && !e5 && !e6) return null;
  return (
    <div className="grid g3" style={{ marginBottom: 12 }}>
      {e4 && <div className="panel"><div className="ph"><h3>E4. Closed loop in the twin</h3><span className="r">{e4.hours} h simulated per arm</span></div>
        <div className="pb flush scroll"><table className="t small">
          <thead><tr><th>Arm</th><th className="num">Unciph. UE-h</th><th className="num">Spoofable UE-h</th><th className="num">Attack succ.</th><th className="num">MTTR (s)</th><th className="num">Unneeded pushes</th><th className="num">Outage UE-h</th></tr></thead>
          <tbody>{Object.entries(e4.arms).map(([a, r]: any) => (
            <tr key={a}><td>{a}</td><td className="num">{r.unciphered_active_ue_hours}</td><td className="num">{r.spoofable_ue_hours}</td><td className="num">{r.attack_success}</td><td className="num">{r.mttr_s ?? "-"}</td><td className="num">{r.unnecessary_pushes}</td><td className="num">{r.remediation_outage_ue_hours}</td></tr>
          ))}</tbody></table></div></div>}
      {e5 && <div className="panel"><div className="ph"><h3>E5. Cost of user-plane integrity</h3></div>
        <div className="pb flush"><table className="t small">
          <thead><tr><th>Setting</th><th className="num">Goodput ratio</th><th className="num">VoIP goodput loss</th><th className="num">Latency p95 (ms)</th></tr></thead>
          <tbody>{e5.rows.map((r: any) => <tr key={r.name}><td>{r.name}</td><td className="num">{(100 * r.goodput_ratio).toFixed(2)}%</td><td className="num">{(100 * r.voip_overhead).toFixed(2)}%</td><td className="num">{r.latency_p95_ms}</td></tr>)}</tbody>
        </table></div></div>}
      {e6 && <div className="panel"><div className="ph"><h3>E6. Remediation scheduling</h3></div>
        <div className="pb flush"><table className="t small">
          <thead><tr><th>Policy</th><th className="num">Exposure UE-h</th><th className="num">Disruption UE-h</th><th className="num">Reward</th></tr></thead>
          <tbody>{Object.entries(e6.policies).map(([k, r]: any) => <tr key={k}><td>{k}</td><td className="num">{r.exposure_ue_h.toFixed(1)}</td><td className="num">{r.disruption_ue_h.toFixed(2)}</td><td className="num">{r.reward.toFixed(1)}</td></tr>)}</tbody>
        </table></div></div>}
    </div>
  );
}
