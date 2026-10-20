import { useEffect, useMemo, useRef, useState } from "react";
import { fmtVal, get, hhmm, post, PARAM_LABEL } from "../api";
import { useTwin } from "../twinStore";

const DEFAULT = {
  n_sites: 19, n_ues: 1500, isd: 500, start_hour: 18, seed: 1,
  mob_static: 30, mob_ped: 50, mob_veh: 20,
  traffic: "urban",
  baseline: "operator_hardened", emergency: false,
  drift_rate_per_site_hour: 0.4, nonconformant_nia0_share: 0.2,
  arm: "A5", detection: "notify", approval_delay_s: 120, remediation_policy: "immediate",
  sniffer: true, rrc_injector: true, o1_mitm: true, backhaul_tap: false,
  mode: "replay", speed: 20,
};

const TRAFFIC: Record<string, any> = {
  urban: { video: 0.32, web: 0.32, voip: 0.12, iot: 0.10, bulk: 0.08, fwa: 0.06 },
  fwa: { video: 0.20, web: 0.20, voip: 0.08, iot: 0.07, bulk: 0.10, fwa: 0.35 },
  iot: { video: 0.15, web: 0.20, voip: 0.10, iot: 0.45, bulk: 0.05, fwa: 0.05 },
};

const ATT_COLORS: Record<string, string> = { sniffer: "#a86300", rrc_injector: "#c0392b", backhaul_tap: "#6b5b95" };

function buildScenario(f: any) {
  const attackers: any[] = [];
  if (f.sniffer) attackers.push({ kind: "sniffer", x: 0, y: 0, radius: 380 });
  if (f.rrc_injector) attackers.push({ kind: "rrc_injector", x: f.isd * 1.0, y: f.isd * 0.6, radius: 330 });
  if (f.o1_mitm) attackers.push({ kind: "o1_mitm", rate_per_hour: 1.5 });
  if (f.backhaul_tap) attackers.push({ kind: "backhaul_tap", site: 2 });
  return {
    n_sites: +f.n_sites, n_ues: +f.n_ues, isd: +f.isd, start_hour: +f.start_hour, seed: +f.seed,
    mobility: { static: +f.mob_static, pedestrian: +f.mob_ped, vehicular: +f.mob_veh },
    traffic_mix: TRAFFIC[f.traffic],
    profile: { baseline: f.baseline, emergency_unauth_supported: !!f.emergency },
    drift_rate_per_site_hour: +f.drift_rate_per_site_hour, nonconformant_nia0_share: +f.nonconformant_nia0_share,
    arm: f.arm, detection: f.detection, approval_delay_s: +f.approval_delay_s,
    remediation_policy: f.remediation_policy, attackers,
  };
}

export default function Network({ go, focus }: { go: (p: string, f?: any) => void; focus: any }) {
  const snap = useTwin();
  const [form, setForm] = useState<any>(DEFAULT);
  const [sel, setSel] = useState<number | null>(focus?.site ?? null);
  const [tool, setTool] = useState<string | null>(null);
  const [siteCfg, setSiteCfg] = useState<any>(null);
  const running = snap?.running;

  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const start = async () => {
    await post("/api/twin/start", { scenario: buildScenario(form), mode: form.mode });
    await post("/api/twin/control", { action: "speed", value: +form.speed });
    setSel(null);
  };
  const ctl = (action: string, extra: any = {}) => post("/api/twin/control", { action, ...extra });

  useEffect(() => {
    if (sel === null || !running) { setSiteCfg(null); return; }
    get(`/api/twin/site/${sel}`).then(setSiteCfg).catch(() => setSiteCfg(null));
  }, [sel, running, snap?.sites?.[sel ?? 0]?.item, snap?.sites?.[sel ?? 0]?.compliant]);

  const site = sel !== null && snap ? snap.sites[sel] : null;
  const net = snap?.net || {};
  const sm = snap?.summary || {};

  return (
    <>
      <div className="page-h">
        <h1>Network topology</h1>
        <span className="sub">Live digital twin: radio, mobility, traffic, AS security selection, attacks, SMO compliance loop</span>
        <div className="right">
          {running ? (
            <>
              <div className="seg">
                {[5, 20, 60, 180].map((v) => (
                  <button key={v} className={snap?.speed === v ? "on" : ""} onClick={() => ctl("speed", { value: v })}>{v}x</button>
                ))}
              </div>
              <button className="btn" onClick={() => ctl("pause")}>Pause</button>
              <button className="btn" onClick={() => ctl("resume")}>Resume</button>
              <button className="btn danger" onClick={() => ctl("stop")}>Stop</button>
            </>
          ) : (
            <button className="btn pri" onClick={start}>Start simulation</button>
          )}
        </div>
      </div>

      <div className="kpis" style={{ marginBottom: 12 }}>
        <Kpi l="DL throughput" v={net.dl_gbps?.toFixed(2)} u="Gbps" />
        <Kpi l="Latency p50 / p95" v={net.lat_p50 !== undefined ? `${net.lat_p50} / ${net.lat_p95}` : undefined} u="ms" />
        <Kpi l="Connected UEs" v={net.connected} />
        <Kpi l="Unciphered UP" v={net.unciphered} u="active UEs" cls={net.unciphered > 0 ? "warn" : "ok"} />
        <Kpi l="Spoofable RRC" v={net.spoofable} u="UEs" cls={net.spoofable > 0 ? "crit" : "ok"} />
        <Kpi l="Non-compliant gNBs" v={net.noncompliant_sites} cls={net.noncompliant_sites > 0 ? "crit" : "ok"} />
        <Kpi l="Off air" v={net.sites_off_air} cls={net.sites_off_air > 0 ? "warn" : ""} />
        <Kpi l="Attack success" v={net.attack_success} cls={net.attack_success > 0 ? "crit" : ""} />
        <Kpi l="MTTD / MTTR" v={sm.mttd_s != null ? `${Math.round(sm.mttd_s)} / ${sm.mttr_s != null ? Math.round(sm.mttr_s) : "-"}` : undefined} u="s" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: running ? "1fr 330px" : "300px 1fr", gap: 12 }}>
        {!running && <ScenarioForm form={form} set={set} start={start} />}
        <div className="panel">
          <div className="ph">
            <h3>Radio access network</h3>
            <span className="r">
              {snap && <>ISD {snap.isd} m &middot; {hhmm(snap.hour)} &middot; load factor {((net.load ?? 0) * 100).toFixed(0)}%</>}
            </span>
          </div>
          <div className="pb flush">
            <MapCanvas snap={snap} sel={sel} onSelect={setSel} tool={tool}
              onPlace={(x: number, y: number) => {
                if (!tool) return;
                ctl("add_attacker", { attacker: { kind: tool, x, y, radius: tool === "sniffer" ? 380 : 330 } });
                setTool(null);
              }} />
          </div>
          {running && (
            <div className="row" style={{ padding: "6px 10px", borderTop: "1px solid var(--line-2)" }}>
              <span className="muted small">Place attacker:</span>
              <button className={"btn sm" + (tool === "sniffer" ? " pri" : "")} onClick={() => setTool(tool === "sniffer" ? null : "sniffer")}>Passive sniffer</button>
              <button className={"btn sm" + (tool === "rrc_injector" ? " pri" : "")} onClick={() => setTool(tool === "rrc_injector" ? null : "rrc_injector")}>RRC injector</button>
              <button className="btn sm" onClick={() => ctl("clear_attackers")}>Clear attackers</button>
              <span className="muted small" style={{ marginLeft: "auto" }}>{tool ? "Click on the map to place" : "Click a site for details"}</span>
            </div>
          )}
        </div>
        {running && (
          <SitePanel site={site} siteCfg={siteCfg} snap={snap}
            onDrift={() => site && ctl("inject_drift", { site: site.idx })}
            onMal={() => site && ctl("inject_malicious", { site: site.idx })}
            onOpen={() => site?.item && go("compliance", { configId: site.item })} />
        )}
      </div>

      {running && (
        <div className="grid g2" style={{ marginTop: 12 }}>
          <AgentPanel snap={snap} />
          <EventLog events={snap?.events || []} sites={snap?.sites || []} />
        </div>
      )}
    </>
  );
}

function Kpi({ l, v, u, cls = "" }: { l: string; v: any; u?: string; cls?: string }) {
  return (
    <div className={"kpi " + cls}>
      <div className="l">{l}</div>
      <div className="v">{v ?? "-"}{u && v !== undefined && <small>{u}</small>}</div>
    </div>
  );
}

function F({ form, set, k, l, type = "number", step }: any) {
  return <div className="fld"><label>{l}</label><input type={type} value={form[k]} step={step} onChange={set(k)} /></div>;
}
function S({ form, set, k, l, opts }: any) {
  return (
    <div className="fld"><label>{l}</label>
      <select value={form[k]} onChange={set(k)}>{opts.map(([v, t]: any) => <option key={v} value={v}>{t}</option>)}</select>
    </div>
  );
}
function C({ form, set, k, l }: any) {
  return <div className="fld"><label>{l}</label><input type="checkbox" checked={!!form[k]} onChange={set(k)} /></div>;
}

function ScenarioForm({ form, set, start }: any) {
  const p = { form, set };
  return (
    <div className="panel">
      <div className="ph"><h3>Scenario</h3></div>
      <div className="pb">
        <div className="sec-l">Topology</div>
        <S {...p} k="n_sites" l="gNB sites (3 sectors each)" opts={[[7, "7"], [19, "19"], [37, "37"]]} />
        <F {...p} k="n_ues" l="UEs" />
        <F {...p} k="isd" l="Inter-site distance (m)" />
        <F {...p} k="start_hour" l="Start time (hour)" step="0.5" />
        <div className="sec-l">Users</div>
        <F {...p} k="mob_static" l="Static (%)" />
        <F {...p} k="mob_ped" l="Pedestrian (%)" />
        <F {...p} k="mob_veh" l="Vehicular (%)" />
        <S {...p} k="traffic" l="Traffic mix" opts={[["urban", "Urban busy hour"], ["fwa", "FWA heavy"], ["iot", "IoT dense"]]} />
        <F {...p} k="nonconformant_nia0_share" l="UEs accepting NIA0 (share)" step="0.05" />
        <div className="sec-l">Security policy</div>
        <S {...p} k="baseline" l="Baseline" opts={[["operator_hardened", "Operator hardened"], ["standards_minimum", "Standards minimum"]]} />
        <C {...p} k="emergency" l="Unauth. emergency required" />
        <F {...p} k="drift_rate_per_site_hour" l="Config drift (/site/h)" step="0.05" />
        <div className="sec-l">Threats</div>
        <C {...p} k="sniffer" l="Passive sniffer (centre)" />
        <C {...p} k="rrc_injector" l="RRC injector / fake gNB" />
        <C {...p} k="o1_mitm" l="O1 man-in-the-middle" />
        <C {...p} k="backhaul_tap" l="Backhaul tap (site 2)" />
        <div className="sec-l">SMO compliance service</div>
        <S {...p} k="arm" l="Agent configuration" opts={["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"].map((a) => [a, a])} />
        <S {...p} k="mode" l="Agent execution" opts={[["replay", "Replay measured runs"], ["live", "Live LLM"]]} />
        <S {...p} k="detection" l="Detection" opts={[["notify", "O1 change notification"], ["poll", "Periodic poll"]]} />
        <F {...p} k="approval_delay_s" l="Human approval (s)" />
        <S {...p} k="remediation_policy" l="Remediation" opts={[["immediate", "Immediate"], ["window", "Maintenance window"], ["rl", "RL scheduler"], ["none", "Detect only"]]} />
        <F {...p} k="speed" l="Speed (x real time)" />
        <button className="btn pri" style={{ width: "100%", marginTop: 6 }} onClick={start}>Start simulation</button>
        <p className="note" style={{ marginTop: 8 }}>
          Replay mode uses the outcome and latency measured for the selected agent on that exact configuration
          in experiment E1. Live mode calls the local LLM for every assessment.
        </p>
      </div>
    </div>
  );
}

function MapCanvas({ snap, sel, onSelect, tool, onPlace }: any) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [w, setW] = useState(900);
  const H = 560;
  useEffect(() => {
    const ro = new ResizeObserver((e) => setW(Math.floor(e[0].contentRect.width)));
    if (ref.current?.parentElement) ro.observe(ref.current.parentElement);
    return () => ro.disconnect();
  }, []);

  const tf = useMemo(() => {
    if (!snap) return null;
    const [x0, x1, y0, y1] = snap.bounds;
    const s = Math.min((w - 20) / (x1 - x0), (H - 20) / (y1 - y0));
    const ox = (w - s * (x1 - x0)) / 2 - s * x0;
    const oy = (H - s * (y1 - y0)) / 2 + s * y1;
    return { s, X: (x: number) => ox + s * x, Y: (y: number) => oy - s * y, ix: (px: number) => (px - ox) / s, iy: (py: number) => (oy - py) / s };
  }, [snap?.bounds?.join(","), w]);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = w * dpr; c.height = H * dpr;
    c.style.height = H + "px";
    const g = c.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, H);
    if (!snap || !tf) {
      g.fillStyle = "#8a94a3"; g.font = "13px IBM Plex Sans";
      g.fillText("Simulation not running. Configure a scenario and press Start.", 24, 40);
      return;
    }
    const R = snap.isd / Math.sqrt(3);
    // cells
    for (const s of snap.sites) {
      const cx = tf.X(s.x), cy = tf.Y(s.y);
      g.beginPath();
      for (let k = 0; k < 6; k++) {
        const a = Math.PI / 6 + k * Math.PI / 3;
        const px = cx + tf.s * R * Math.cos(a), py = cy - tf.s * R * Math.sin(a);
        k ? g.lineTo(px, py) : g.moveTo(px, py);
      }
      g.closePath();
      g.fillStyle = !s.on_air ? "#e3e3e3" : s.compliant ? "#f1f6f1" : "#fbe8e5";
      g.fill();
      g.strokeStyle = !s.compliant ? "#d98b80" : "#c9d3cb";
      g.lineWidth = 1;
      g.stroke();
      // sector load wedges
      const az = [30, 150, 270];
      for (let k = 0; k < 3; k++) {
        const a0 = ((az[k] - 60) * Math.PI) / 180, a1 = ((az[k] + 60) * Math.PI) / 180;
        g.beginPath();
        g.moveTo(cx, cy);
        g.arc(cx, cy, tf.s * R * 0.42, -a1, -a0);
        g.closePath();
        g.fillStyle = `rgba(11,111,164,${0.08 + 0.5 * (s.load[k] || 0)})`;
        g.fill();
      }
      // sector boundaries
      g.strokeStyle = "rgba(90,105,120,.25)";
      for (const b of [90, 210, 330]) {
        const a = (b * Math.PI) / 180;
        g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + tf.s * R * Math.cos(a), cy - tf.s * R * Math.sin(a)); g.stroke();
      }
    }
    // UEs
    const u = snap.ues;
    for (let i = 0; i < u.x.length; i++) {
      const f = u.flags[i];
      const px = tf.X(u.x[i]), py = tf.Y(u.y[i]);
      if (f & 8) { g.strokeStyle = "#333"; g.lineWidth = 1; g.beginPath(); g.moveTo(px - 2, py - 2); g.lineTo(px + 2, py + 2); g.moveTo(px + 2, py - 2); g.lineTo(px - 2, py + 2); g.stroke(); continue; }
      g.fillStyle = f & 4 ? "#6b5b95" : f & 2 ? "#c0392b" : f & 1 ? "#d98a0b" : u.active[i] ? "#3f7199" : "#a9b8c6";
      g.fillRect(px - 1.4, py - 1.4, 2.8, 2.8);
    }
    // sites
    for (const s of snap.sites) {
      const cx = tf.X(s.x), cy = tf.Y(s.y);
      g.fillStyle = s.on_air ? "#1d242c" : "#888";
      g.beginPath(); g.moveTo(cx, cy - 6); g.lineTo(cx - 5, cy + 4); g.lineTo(cx + 5, cy + 4); g.closePath(); g.fill();
      if (!s.compliant) { g.fillStyle = "#c0392b"; g.beginPath(); g.arc(cx + 7, cy - 6, 3.2, 0, 2 * Math.PI); g.fill(); }
      g.fillStyle = "#4d5866"; g.font = "10px IBM Plex Sans";
      g.fillText(s.name.replace("gNB-", ""), cx + 7, cy + 12);
      if (s.idx === sel) { g.strokeStyle = "#0b6fa4"; g.lineWidth = 2; g.beginPath(); g.arc(cx, cy, 14, 0, 2 * Math.PI); g.stroke(); }
    }
    // attackers
    for (const a of snap.attackers) {
      if (a.kind === "o1_mitm") continue;
      let ax = a.x, ay = a.y;
      if (a.kind === "backhaul_tap") { const s = snap.sites[a.site]; if (!s) continue; ax = s.x; ay = s.y; }
      const col = ATT_COLORS[a.kind] || "#c0392b";
      const px = tf.X(ax), py = tf.Y(ay);
      if (a.kind !== "backhaul_tap") {
        g.setLineDash([5, 4]); g.strokeStyle = col; g.lineWidth = 1.3;
        g.beginPath(); g.arc(px, py, tf.s * a.radius, 0, 2 * Math.PI); g.stroke(); g.setLineDash([]);
      }
      g.fillStyle = col; g.fillRect(px - 4, py - 4, 8, 8);
      g.font = "10.5px IBM Plex Sans"; g.fillStyle = col;
      g.fillText(a.kind === "sniffer" ? "Passive sniffer" : a.kind === "rrc_injector" ? "RRC injector" : "Backhaul tap", px + 7, py - 6);
    }
    if (snap.attackers.some((a: any) => a.kind === "o1_mitm")) {
      g.fillStyle = "#6b5b95"; g.font = "11px IBM Plex Sans";
      g.fillText("O1 MITM active on management network", 10, 18);
    }
    // scale bar
    const L = 500 * tf.s;
    g.strokeStyle = "#4d5866"; g.lineWidth = 1;
    g.beginPath(); g.moveTo(w - 20 - L, H - 18); g.lineTo(w - 20, H - 18); g.moveTo(w - 20 - L, H - 22); g.lineTo(w - 20 - L, H - 14); g.moveTo(w - 20, H - 22); g.lineTo(w - 20, H - 14); g.stroke();
    g.fillStyle = "#4d5866"; g.font = "10.5px IBM Plex Sans"; g.fillText("500 m", w - 20 - L / 2 - 14, H - 24);
  }, [snap, tf, sel, w]);

  const click = (e: React.MouseEvent) => {
    if (!snap || !tf) return;
    const r = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const x = tf.ix(e.clientX - r.left), y = tf.iy(e.clientY - r.top);
    if (tool) { onPlace(x, y); return; }
    let best = -1, bd = 1e18;
    for (const s of snap.sites) { const d = (s.x - x) ** 2 + (s.y - y) ** 2; if (d < bd) { bd = d; best = s.idx; } }
    onSelect(Math.sqrt(bd) < snap.isd * 0.6 ? best : null);
  };

  return (
    <div className="map-wrap">
      <canvas ref={ref} onClick={click} style={{ width: w }} />
      {snap && (
        <div className="map-ovl legend">
          <span><i style={{ background: "#3f7199" }} />UE active</span>
          <span><i style={{ background: "#a9b8c6" }} />idle</span>
          <span><i style={{ background: "#d98a0b" }} />unciphered user plane</span>
          <span><i style={{ background: "#c0392b" }} />RRC on NIA0 (spoofable)</span>
          <span><i style={{ background: "#6b5b95" }} />denied by attack</span>
          <span><i className="sq" style={{ background: "#fbe8e5", border: "1px solid #d98b80" }} />non-compliant gNB</span>
          <span><i className="sq" style={{ background: "rgba(11,111,164,.45)" }} />sector load</span>
        </div>
      )}
    </div>
  );
}

function SitePanel({ site, siteCfg, snap, onDrift, onMal, onOpen }: any) {
  if (!site) {
    const bad = snap?.sites?.filter((s: any) => !s.compliant) || [];
    return (
      <div className="panel">
        <div className="ph"><h3>gNB inventory</h3><span className="r">{snap?.sites?.length} sites</span></div>
        <div className="pb flush scroll" style={{ maxHeight: 600 }}>
          <table className="t">
            <thead><tr><th>gNB</th><th>Status</th><th className="num">UEs</th><th className="num">Load</th></tr></thead>
            <tbody>
              {snap?.sites?.map((s: any) => (
                <tr key={s.idx}>
                  <td>{s.name}<div className="muted small">{s.vendor}</div></td>
                  <td>{!s.on_air ? <span className="st mute">OFF AIR</span> : s.compliant ? <span className="st ok">COMPLIANT</span> : <span className="st crit">{s.violations.length} VIOLATION{s.violations.length > 1 ? "S" : ""}</span>}</td>
                  <td className="num">{s.ues}</td>
                  <td className="num">{(100 * Math.max(...s.load)).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {bad.length === 0 && <div className="note" style={{ padding: 10 }}>All gNBs compliant with the selected profile.</div>}
        </div>
      </div>
    );
  }
  const viol = new Set(site.violations);
  return (
    <div className="panel">
      <div className="ph">
        <h3>{site.name}</h3>
        <span className="r">{!site.on_air ? <span className="st mute">OFF AIR</span> : site.compliant ? <span className="st ok">COMPLIANT</span> : <span className="st crit">NON-COMPLIANT</span>}</span>
      </div>
      <div className="pb">
        <div className="row small muted" style={{ marginBottom: 8 }}>
          <span>Vendor {site.vendor}</span><span>&middot;</span><span>{site.ues} UEs</span><span>&middot;</span>
          <span>config {site.item || "baseline"}</span>
        </div>
        <div className="sec-l">Sector load</div>
        {site.load.map((l: number, k: number) => (
          <div key={k} className="row small" style={{ marginBottom: 4 }}>
            <span style={{ width: 62 }}>Sector {k + 1}</span>
            <div className="bar" style={{ flex: 1 }}><span style={{ width: `${100 * l}%`, background: l > 0.85 ? "#a86300" : undefined }} /></div>
            <span style={{ width: 34, textAlign: "right" }}>{(100 * l).toFixed(0)}%</span>
          </div>
        ))}
        <div className="sec-l">AS security negotiated</div>
        <table className="t small">
          <thead><tr><th>UE class</th><th>Ciphering</th><th>Integrity</th></tr></thead>
          <tbody>
            <tr><td>NEA/NIA 0-2</td><Alg v={site.sel_c[0]} /><Alg v={site.sel_i[0]} /></tr>
            <tr><td>NEA/NIA 0-3</td><Alg v={site.sel_c[1]} /><Alg v={site.sel_i[1]} /></tr>
          </tbody>
        </table>
        <div className="row small" style={{ marginTop: 6 }}>
          <span>DRB ciphering {site.drb_c ? <span className="st ok">ON</span> : <span className="st crit">OFF</span>}</span>
          <span>DRB integrity {site.drb_i ? <span className="st ok">ON</span> : <span className="st mute">OFF</span>}</span>
        </div>
        <div className="sec-l">Interfaces</div>
        <table className="t small">
          <tbody>
            {Object.entries(site.iface).map(([k, v]: any) => (
              <tr key={k}><td>{PARAM_LABEL[k] || k}</td><td className="mono">{fmtVal(v)}</td>
                <td>{viol.has(k) ? <span className="st crit">VIOLATION</span> : <span className="st ok">OK</span>}</td></tr>
            ))}
          </tbody>
        </table>
        {site.violations.length > 0 && (
          <>
            <div className="sec-l">Violations (ground truth)</div>
            {site.violations.map((v: string) => <div key={v} className="small"><span className="dot" style={{ background: "#c0392b" }} />{PARAM_LABEL[v] || v}</div>)}
          </>
        )}
        <div className="sec-l">Actions</div>
        <div className="row wrap">
          <button className="btn sm" onClick={onDrift}>Inject config drift</button>
          <button className="btn sm danger" onClick={onMal}>Malicious push via O1</button>
          {site.item && <button className="btn sm" onClick={onOpen}>Open in console</button>}
        </div>
        {siteCfg && (
          <>
            <div className="sec-l">Security section of gnb.conf</div>
            <pre className="code" style={{ maxHeight: 220, margin: 0, padding: 8 }}>{siteCfg.excerpt}</pre>
          </>
        )}
      </div>
    </div>
  );
}

function Alg({ v }: { v: string | null }) {
  if (!v) return <td><span className="st crit">NO ALG</span></td>;
  const bad = v.endsWith("0");
  return <td><span className={"st " + (bad ? "crit" : "ok")}>{v.toUpperCase()}</span></td>;
}

function AgentPanel({ snap }: any) {
  const a = snap?.agent;
  return (
    <div className="panel">
      <div className="ph"><h3>SMO compliance service</h3>
        <span className="r">{a ? `${a.arm}, ${a.mode}` : "-"} &middot; queue {a?.queue?.length ?? 0} &middot; pending pushes {snap?.pending?.length ?? 0}</span>
      </div>
      <div className="pb flush scroll" style={{ maxHeight: 260 }}>
        {a?.current && <div className="small" style={{ padding: "6px 10px", background: "#f4f8fb", borderBottom: "1px solid var(--line-2)" }}>
          Assessing gNB-{String(a.current.site).padStart(3, "0")} ({a.current.item}) since t={Math.round(a.current.t_start)} s
        </div>}
        <table className="t small">
          <thead><tr><th>Done</th><th>gNB</th><th>Agent verdict</th><th>Ground truth</th><th>Outcome</th></tr></thead>
          <tbody>
            {(a?.history || []).slice().reverse().map((h: any, i: number) => {
              const p = new Set(h.pred), t = new Set(h.truth);
              const exact = p.size === t.size && [...p].every((x) => t.has(x));
              const missed = [...t].filter((x) => !p.has(x)).length, fp = [...p].filter((x) => !t.has(x)).length;
              return (
                <tr key={i}>
                  <td className="mono">{Math.round(h.t_done)} s</td>
                  <td>{String(h.site).padStart(3, "0")}</td>
                  <td>{h.pred.length ? h.pred.map((x: string) => PARAM_LABEL[x] || x).join(", ") : <span className="muted">compliant</span>}</td>
                  <td>{h.truth.length ? h.truth.map((x: string) => PARAM_LABEL[x] || x).join(", ") : <span className="muted">compliant</span>}</td>
                  <td>{exact ? <span className="st ok">CORRECT</span> : <>{missed > 0 && <span className="st crit">{missed} MISSED</span>} {fp > 0 && <span className="st warn">{fp} FALSE POS.</span>}</>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!a?.history?.length && <div className="empty">No assessments yet. Config changes trigger O1 notifications.</div>}
      </div>
    </div>
  );
}

const EVT: Record<string, [string, string]> = {
  config_change: ["CONFIG CHANGE", "warn"], assessment_started: ["ASSESSING", "info"], assessment_done: ["ASSESSED", "info"],
  remediation_push: ["FIX PUSHED", "ok"], rrc_injection_success: ["RRC INJECTION", "crit"], downgrade_at_handover: ["HO DOWNGRADE", "crit"],
  manual_audit_fix: ["AUDIT FIX", "mute"], escalated_to_human: ["ESCALATED", "warn"], assessment_skipped: ["NOT ASSESSABLE", "mute"],
  notice: ["NOTICE", "warn"],
};

function EventLog({ events, sites }: any) {
  const name = (i: number | null) => (i === null || i === undefined ? "-" : sites[i]?.name?.replace("gNB-", "") ?? i);
  const detail = (e: any) => {
    switch (e.kind) {
      case "config_change": return `${e.cause}: ${e.item}${e.compliant ? " (compliant)" : ` -> ${e.violations.map((v: string) => PARAM_LABEL[v] || v).join(", ")}`}`;
      case "assessment_done": return `predicted ${e.predicted.length ? e.predicted.map((v: string) => PARAM_LABEL[v] || v).join(", ") : "compliant"} in ${e.seconds} s`;
      case "remediation_push": return `${e.source}: ${Object.entries(e.fixes).map(([k, v]: any) => `${k}=${fmtVal(v)}`).join("; ")}; outage ${e.outage_s} s${e.compliant_after ? "" : "; still non-compliant"}`;
      case "rrc_injection_success": return `${e.ues} UE(s) released by forged RRC message`;
      case "downgrade_at_handover": return `${e.ues} UE(s) lost user-plane ciphering at handover into this gNB (last 30 s)`;
      case "assessment_started": return `${e.arm} (${e.mode})`;
      default: return e.reason || "";
    }
  };
  return (
    <div className="panel">
      <div className="ph"><h3>Event log</h3><span className="r">{events.length} recent</span></div>
      <div className="pb flush scroll" style={{ maxHeight: 260 }}>
        <table className="t evt">
          <thead><tr><th>Sim time</th><th>gNB</th><th>Event</th><th>Detail</th></tr></thead>
          <tbody>
            {events.slice().reverse().map((e: any, i: number) => {
              const [lab, cls] = EVT[e.kind] || [e.kind, "mute"];
              return <tr key={i}><td>{hhmm(e.hour)}:{String(Math.floor(e.t % 60)).padStart(2, "0")}</td><td>{name(e.site)}</td><td><span className={"st " + cls}>{lab}</span></td><td>{detail(e)}</td></tr>;
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
