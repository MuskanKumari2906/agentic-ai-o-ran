import { useEffect, useMemo, useState } from "react";
import Chart, { axis } from "../Chart";
import { get, hhmm, PARAM_LABEL, post } from "../api";
import { useTwin } from "../twinStore";

function series(rows: any[], key: string, name: string, extra: any = {}) {
  return { name, type: "line", showSymbol: false, lineStyle: { width: 1.4 }, data: rows.map((r) => [r.t / 60, r[key]]), ...extra };
}

function opt(rows: any[], s: any[], yName: string, extra: any = {}) {
  return {
    tooltip: { trigger: "axis", valueFormatter: (v: number) => (typeof v === "number" ? v.toFixed(2) : v) },
    legend: { top: 0, right: 8, itemWidth: 14, itemHeight: 2, textStyle: { fontSize: 11 } },
    xAxis: { type: "value", name: "sim min", nameLocation: "middle", nameGap: 20, min: rows.length ? rows[0].t / 60 : 0, ...axis },
    yAxis: { type: "value", name: yName, ...axis, ...extra },
    series: s,
  };
}

export default function Assurance({ go }: { go: (p: string, f?: any) => void }) {
  const snap = useTwin();
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => {
    const load = () => get("/api/twin/telemetry?last=1440").then(setRows).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  const o1 = useMemo(() => opt(rows, [series(rows, "dl_gbps", "DL throughput (Gbps)"),
    { ...series(rows, "load", "Offered load factor"), yAxisIndex: 1, lineStyle: { width: 1, type: "dashed" } }], "Gbps"), [rows]);
  const o1b = useMemo(() => ({ ...o1, yAxis: [{ type: "value", name: "Gbps", ...axis }, { type: "value", name: "load", max: 1, ...axis, splitLine: { show: false } }] }), [o1]);
  const o2 = useMemo(() => opt(rows, [series(rows, "lat_p50", "p50"), series(rows, "lat_p95", "p95")], "ms", { type: "log", min: 1 }), [rows]);
  const o3 = useMemo(() => opt(rows, [series(rows, "unciphered", "Active UEs on unciphered user plane", { areaStyle: { opacity: 0.12 } }),
    series(rows, "spoofable", "UEs with RRC on NIA0", { areaStyle: { opacity: 0.12 } })], "UEs"), [rows]);
  const o4 = useMemo(() => opt(rows, [series(rows, "noncompliant_sites", "Non-compliant gNBs", { step: "end" }),
    series(rows, "sites_off_air", "gNBs off air (remediation)", { step: "end" })], "gNBs", { minInterval: 1 }), [rows]);
  const o5 = useMemo(() => opt(rows, [series(rows, "attack_success", "Successful RRC injections (cum.)"),
    { ...series(rows, "intercepted_gb", "Intercepted traffic (GB, cum.)"), yAxisIndex: 1 }], "attacks"), [rows]);
  const o5b = useMemo(() => ({ ...o5, yAxis: [{ type: "value", name: "count", ...axis }, { type: "value", name: "GB", ...axis, splitLine: { show: false } }] }), [o5]);

  const sm = snap?.summary || {};
  const health = (s: any) => {
    if (!s.on_air) return { score: 0, cls: "off" };
    let sc = 100 - 25 * s.violations.length - (Math.max(...s.load) > 0.9 ? 10 : 0);
    sc = Math.max(0, sc);
    return { score: sc, cls: sc >= 90 ? "ok" : sc >= 60 ? "warn" : "crit" };
  };

  if (!snap) return <><Header /><div className="panel"><div className="empty">Start a simulation on the Network topology page.</div></div></>;

  return (
    <>
      <Header />
      <div className="grid" style={{ gridTemplateColumns: "1fr 360px" }}>
        <div className="grid g2">
          <Panel title="Throughput and offered load"><Chart option={o1b} /></Panel>
          <Panel title="Packet latency across active UEs"><Chart option={o2} /></Panel>
          <Panel title="Security exposure"><Chart option={o3} /></Panel>
          <Panel title="Compliance state"><Chart option={o4} /></Panel>
          <Panel title="Attacks"><Chart option={o5b} /></Panel>
          <Panel title="Run summary">
            <table className="t small">
              <tbody>
                <tr><td>Simulated time</td><td className="num">{sm.sim_hours} h</td><td>Service availability</td><td className="num">{(100 * sm.service_availability).toFixed(3)}%</td></tr>
                <tr><td>Mean throughput</td><td className="num">{sm.throughput_gbps_mean} Gbps</td><td>Goodput ratio</td><td className="num">{(100 * sm.goodput_ratio).toFixed(2)}%</td></tr>
                <tr><td>Latency p50 / p95 / p99</td><td className="num">{sm.latency_p50_ms} / {sm.latency_p95_ms} / {sm.latency_p99_ms} ms</td><td>Handovers</td><td className="num">{sm.handovers}</td></tr>
                <tr><td>Unciphered active UE-hours</td><td className="num">{sm.unciphered_active_ue_hours}</td><td>Spoofable UE-hours</td><td className="num">{sm.spoofable_ue_hours}</td></tr>
                <tr><td>Traffic sent unciphered</td><td className="num">{sm.gb_unciphered} GB</td><td>Traffic intercepted</td><td className="num">{sm.gb_intercepted} GB</td></tr>
                <tr><td>RRC injection attempts / success</td><td className="num">{sm.attack_attempts} / {sm.attack_success}</td><td>Downgrades at handover</td><td className="num">{sm.downgrades_at_handover}</td></tr>
                <tr><td>Config changes (malicious)</td><td className="num">{sm.drift_events} ({sm.malicious_injections})</td><td>Detections</td><td className="num">{sm.detections}</td></tr>
                <tr><td>Fixes pushed (unnecessary)</td><td className="num">{sm.pushes} ({sm.unnecessary_pushes})</td><td>Left for manual audit</td><td className="num">{sm.missed_until_audit}</td></tr>
                <tr><td>Remediation outage</td><td className="num">{sm.remediation_outage_ue_hours} UE-h</td><td>Attach failures</td><td className="num">{sm.attach_fail_ue_hours} UE-h</td></tr>
                <tr><td>MTTD</td><td className="num">{sm.mttd_s ?? "-"} s</td><td>MTTR</td><td className="num">{sm.mttr_s ?? "-"} s</td></tr>
              </tbody>
            </table>
          </Panel>
        </div>
        <div className="panel">
          <div className="ph"><h3>gNB health</h3><span className="r">{hhmm(snap.hour)}</span></div>
          <div className="pb">
            <div className="health">
              {snap.sites.map((s: any) => {
                const h = health(s);
                return (
                  <div key={s.idx} className={"h " + h.cls} onClick={() => go("network", { site: s.idx })}
                    title={s.violations.map((v: string) => PARAM_LABEL[v] || v).join(", ")}>
                    <div className="n">{s.name}</div>
                    <div className="s">{h.score}</div>
                  </div>
                );
              })}
            </div>
            <p className="note" style={{ marginTop: 10 }}>
              Health score: 100, minus 25 per security violation, minus 10 if any sector is above 90 % load; 0 when off air.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}

function Header() {
  const [msg, setMsg] = useState("");
  const exp = async () => {
    try {
      const r = await post("/api/twin/export");
      setMsg(`Written to ${r.dir} (${Object.values(r.files).map((f: any) => f.rows).reduce((a: number, b: number) => a + b, 0)} rows)`);
    } catch { setMsg("No simulation running"); }
  };
  return (
    <div className="page-h"><h1>Assurance</h1><span className="sub">Network, security and attack telemetry from the running twin (10 s granularity)</span>
      <div className="right">{msg && <span className="muted small">{msg}</span>}<button className="btn" onClick={exp}>Export telemetry (Parquet)</button></div>
    </div>
  );
}

function Panel({ title, children }: any) {
  return <div className="panel"><div className="ph"><h3>{title}</h3></div><div className="pb">{children}</div></div>;
}
