import { useEffect, useMemo, useRef, useState } from "react";
import { ARM_NAMES, fmtVal, get, PARAM_LABEL, post, profileText } from "../api";

const ARMS = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A5x"];
const CAT_LABEL: Record<string, string> = {
  clean: "Clean", vendor_default: "Vendor default", single: "Single", multi: "Multiple", decoy: "Decoy", context: "Context pair", noise: "Noise",
};

export default function Compliance({ meta, focus }: { meta: any; focus: any }) {
  const [list, setList] = useState<any[]>([]);
  const [cid, setCid] = useState<string>(focus?.configId || "cfg-005");
  const [item, setItem] = useState<any>(null);
  const [arm, setArm] = useState("A5");
  const [recorded, setRecorded] = useState<any[]>([]);
  const [run, setRun] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  const [cat, setCat] = useState("all");

  useEffect(() => { get("/api/dataset").then(setList); }, []);
  useEffect(() => {
    setItem(null); setRun(null); setJob(null);
    get(`/api/dataset/${cid}`).then(setItem);
    get(`/api/runs/${cid}`).then((r) => setRecorded(r)).catch(() => setRecorded([]));
  }, [cid]);
  useEffect(() => {
    const r = recorded.filter((x) => x.arm === arm && (x.rep ?? 0) === 0)[0];
    if (!job || job.status === "error") setRun(r || null);
  }, [recorded, arm]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const t = setInterval(async () => {
      const j = await get(`/api/assess/${job.id}`);
      setJob(j);
      if (j.status === "done") setRun(j.result);
    }, 1000);
    return () => clearInterval(t);
  }, [job?.id, job?.status]);

  const runLive = async () => {
    try {
      const r = await post("/api/assess", { config_id: cid, arm });
      setRun(null);
      setJob({ id: r.job, status: "running", events: [] });
    } catch (e: any) {
      setJob({ id: "", status: "error", error: e.message });
    }
  };

  const filtered = list.filter((d) => cat === "all" || d.category === cat);
  const truth = new Set<string>(item?.summary?.violations || []);
  const pred = new Set<string>(run?.predicted_violations || []);

  return (
    <>
      <div className="page-h">
        <h1>Compliance console</h1>
        <span className="sub">Assessor, verifier-grounded Reflection Agent and repair, on one gNB configuration</span>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "250px 1fr 1fr" }}>
        <div className="panel">
          <div className="ph"><h3>Configurations</h3>
            <span className="r">
              <select className="inline" value={cat} onChange={(e) => setCat(e.target.value)}>
                <option value="all">All</option>
                {Object.entries(CAT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </span>
          </div>
          <div className="pb flush scroll" style={{ maxHeight: "calc(100vh - 150px)" }}>
            <table className="t small">
              <thead><tr><th>ID</th><th>Category</th><th>Truth</th></tr></thead>
              <tbody>
                {filtered.map((d) => (
                  <tr key={d.id} className={d.id === cid ? "sel" : ""} onClick={() => setCid(d.id)} style={{ cursor: "pointer" }}>
                    <td className="mono">{d.id}<div className="muted" style={{ fontSize: 11 }}>{d.split}</div></td>
                    <td>{CAT_LABEL[d.category]}</td>
                    <td>{d.summary.compliant ? <span className="st ok">OK</span> : <span className="st crit">{d.summary.violations.length}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="ph"><h3>{item?.identity?.name || cid}</h3>
            <span className="r">{item && <>{item.vendor} &middot; {CAT_LABEL[item.category]}</>}</span>
          </div>
          <div className="pb">
            {item && (
              <>
                <div className="small" style={{ marginBottom: 8 }}>
                  <b>Deployment profile:</b> {profileText(item.profile)}
                  {item.note && <div className="muted">{item.note}</div>}
                </div>
                <ParamTable item={item} pred={run ? pred : null} />
                <div className="sec-l">gnb.conf</div>
                <ConfigView text={item.text} lines={item.lines} truth={truth} pred={run ? pred : null} />
              </>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="ph"><h3>Agent run</h3>
            <span className="r">
              <select className="inline" value={arm} onChange={(e) => { setArm(e.target.value); setJob(null); }}>
                {ARMS.map((a) => <option key={a} value={a}>{a}: {ARM_NAMES[a]}</option>)}
              </select>
              <button className="btn pri sm" onClick={runLive} disabled={job?.status === "running"}>
                {job?.status === "running" ? "Running..." : "Run live"}
              </button>
            </span>
          </div>
          <div className="pb scroll" style={{ maxHeight: "calc(100vh - 150px)" }}>
            {job?.status === "running" && <LiveEvents events={job.events || []} />}
            {job?.status === "error" && <div className="note" style={{ marginBottom: 10, color: "var(--warn)" }}>{job.error}</div>}
            {run ? <Trace run={run} item={item} live={!!job} /> : job?.status !== "running" && (
              <div className="empty">No recorded run of {arm} on this configuration yet. Press "Run live" to assess it now with the local LLM.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function ParamTable({ item, pred }: { item: any; pred: Set<string> | null }) {
  return (
    <table className="t small">
      <thead><tr><th>Parameter</th><th>Line</th><th>Value</th><th>Ground truth</th>{pred && <th>Agent</th>}</tr></thead>
      <tbody>
        {Object.entries(item.labels).map(([p, l]: any) => {
          const v = l.verdict === "violation";
          const a = pred ? pred.has(p) : null;
          return (
            <tr key={p}>
              <td>{PARAM_LABEL[p] || p}</td>
              <td className="mono">{l.line}</td>
              <td className="mono">{fmtVal(l.value)}</td>
              <td>{v ? <span className="st crit" title={l.reasons.map((r: any) => `${r.rule_id}: ${r.text}`).join("\n")}>VIOLATION</span> : <span className="st ok">COMPLIANT</span>}</td>
              {pred && <td>{a ? (v ? <span className="st crit">FLAGGED</span> : <span className="st warn">FALSE POS.</span>) : (v ? <span className="st warn">MISSED</span> : <span className="muted">-</span>)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ConfigView({ text, lines, truth, pred }: any) {
  const byLine: Record<number, string> = {};
  for (const [p, ln] of Object.entries(lines || {})) if (ln) byLine[ln as number] = p;
  const rows = text.split("\n");
  const first = Math.min(...(Object.values(lines || {}).filter(Boolean) as number[])) - 4;
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current?.querySelector("#sec-start") as HTMLElement | null;
    if (el && box.current) box.current.scrollTop = el.offsetTop - box.current.offsetTop;
  }, [text]);
  return (
    <div className="code" style={{ maxHeight: 420 }} ref={box}>
      {rows.map((r: string, i: number) => {
        const ln = i + 1;
        const p = byLine[ln];
        const cls = p ? (truth.has(p) ? "hl-crit" : pred && pred.has(p) ? "hl-warn" : "") : "";
        const ci = r.indexOf("#");
        return (
          <div key={i} className={"ln " + cls} id={ln === first ? "sec-start" : undefined}>
            <span className="n">{ln}</span>
            <span className="c">{ci >= 0 ? <>{r.slice(0, ci)}<span className="cm">{r.slice(ci)}</span></> : r}</span>
          </div>
        );
      })}
    </div>
  );
}

function LiveEvents({ events }: { events: any[] }) {
  return (
    <div className="tl" style={{ marginBottom: 10 }}>
      {events.map((e, i) => (
        <div key={i} className="step ok"><div className="h">{e.kind}<span className="t">{e.t}s</span></div>
          <div className="small muted">
            {e.kind === "retrieval" && `${e.clauses.length} clauses: ${e.clauses.join(", ")}`}
            {e.kind === "assessment" && `round ${e.round}: ${(e.assessment?.findings || []).filter((f: any) => f.verdict === "violation").length} violation finding(s)`}
            {e.kind === "verifier" && `${e.issues.length} issue(s)`}
            {e.kind === "critic" && `${e.critic.length} claim(s)`}
          </div>
        </div>
      ))}
      <div className="step run"><div className="h">Waiting for the local LLM...</div></div>
    </div>
  );
}

const CHECK_NAME: Record<string, string> = { C1: "Schema", C2: "Grounding", C3: "Citation", C4: "Strength / applicability", C5: "Fix validity", critic: "Critic" };

function Trace({ run, item, live }: { run: any; item: any; live: boolean }) {
  const truth = new Set<string>(item?.summary?.violations || []);
  const pred = new Set<string>(run.predicted_violations || []);
  const exact = truth.size === pred.size && [...truth].every((x) => pred.has(x));
  const rounds = run.rounds || [];
  return (
    <div>
      <div className="row wrap" style={{ marginBottom: 10 }}>
        <span className={"st " + (exact ? "ok" : "crit")}>{exact ? "CORRECT" : "INCORRECT"}</span>
        {run.escalated && <span className="st warn">ESCALATED</span>}
        <span className="muted small">{run.model} &middot; {run.seconds?.toFixed(1)} s &middot; {run.tokens} tokens &middot; {live ? "live run" : `recorded (E1, repeat ${run.rep ?? 0})`}</span>
      </div>
      <div className="tl">
        {run.queries?.length > 0 && (
          <div className="step ok"><div className="h">Query generation<span className="t">{run.queries.length} queries</span></div>
            <ol className="small" style={{ margin: "4px 0 0", paddingLeft: 18 }}>{run.queries.map((q: string, i: number) => <li key={i}>{q.length > 160 ? q.slice(0, 160) + "..." : q}</li>)}</ol>
          </div>
        )}
        {run.retrieved?.length > 0 && (
          <div className="step ok"><div className="h">Retrieval<span className="t">BM25 + nomic-embed-text, RRF fusion</span></div>
            <div className="row wrap" style={{ marginTop: 4 }}>{run.retrieved.map((c: string) => <span key={c} className="st mute mono">{c}</span>)}</div>
          </div>
        )}
        {rounds.map((rd: any, i: number) => <Round key={i} rd={rd} truth={truth} />)}
        <div className={"step " + (exact ? "ok" : "crit")}>
          <div className="h">Result</div>
          <table className="t small" style={{ marginTop: 4 }}>
            <thead><tr><th>Confirmed finding</th><th>Clause</th><th>Status</th><th>Fix</th></tr></thead>
            <tbody>
              {(run.confirmed_findings || []).map((f: any, i: number) => (
                <tr key={i}>
                  <td>{PARAM_LABEL[f.parameter] || f.parameter} {truth.has(f.parameter) ? "" : <span className="st warn">FP</span>}</td>
                  <td className="mono">{f.clause_id}</td>
                  <td><span className={"st " + (f.status === "confirmed" ? "ok" : "mute")}>{f.status?.toUpperCase()}</span></td>
                  <td className="mono">{fmtVal(run.fixes?.[f.parameter])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!run.confirmed_findings?.length && <div className="small muted">No confirmed violations: configuration reported compliant.</div>}
          {[...truth].filter((p) => !pred.has(p)).length > 0 && (
            <div className="small" style={{ marginTop: 6 }}>Missed: {[...truth].filter((p) => !pred.has(p)).map((p) => <span key={p} className="st warn" style={{ marginRight: 4 }}>{PARAM_LABEL[p]}</span>)}</div>
          )}
          {run.diff && <><div className="sec-l">Proposed change</div><Diff text={run.diff} /></>}
          {item?.optimal_diff && <><div className="sec-l">Minimal repair (SMT, reference)</div><Diff text={item.optimal_diff} /></>}
          {run.audit && <div className="note mono" style={{ marginTop: 6 }}>audit entry {run.audit.entry_hash.slice(0, 16)}... prev {run.audit.prev_hash.slice(0, 16)}...</div>}
        </div>
      </div>
    </div>
  );
}

function Round({ rd, truth }: { rd: any; truth: Set<string> }) {
  const f = (rd.assessment?.findings || []).filter((x: any) => x && x.verdict !== "compliant");
  const issues = rd.issues || [];
  const crit = rd.critic || [];
  return (
    <>
      <div className={"step " + (rd.assessment ? "ok" : "crit")}>
        <div className="h">Assessor, round {rd.round}<span className="t">{rd.assessment ? `${f.length} non-compliant finding(s)` : "output could not be parsed"}</span></div>
        {f.length > 0 && (
          <table className="t small" style={{ marginTop: 4 }}>
            <thead><tr><th>Parameter</th><th>Verdict</th><th>Clause / quote</th></tr></thead>
            <tbody>
              {f.map((x: any, i: number) => (
                <tr key={i}>
                  <td>{PARAM_LABEL[x.parameter] || x.parameter}{!truth.has(x.parameter) && x.verdict === "violation" && <> <span className="st warn">FP</span></>}</td>
                  <td>{x.verdict}</td>
                  <td><span className="mono">{x.clause_id}</span> <span className="muted">"{(x.quote || "").slice(0, 120)}"</span> <span className="st mute">{x.normative_level}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {(issues.length > 0 || crit.length > 0 || rd.round !== undefined) && (issues.length > 0 || crit.length > 0) && (
        <div className={"step " + (issues.length ? "warn" : "ok")}>
          <div className="h">Reflection, round {rd.round}<span className="t">{issues.length} verifier issue(s), {crit.length} critic claim(s)</span></div>
          {issues.length > 0 && (
            <table className="t small" style={{ marginTop: 4 }}>
              <thead><tr><th>Check</th><th>Issue</th><th>Parameter</th><th>Detail</th></tr></thead>
              <tbody>{issues.map((x: any, i: number) => (
                <tr key={i}><td>{x.check} {CHECK_NAME[x.check] ? <span className="muted">{CHECK_NAME[x.check]}</span> : null}</td><td><span className="st warn">{x.type}</span></td><td>{PARAM_LABEL[x.parameter] || x.parameter}</td><td>{x.detail}</td></tr>
              ))}</tbody>
            </table>
          )}
          {crit.length > 0 && (
            <table className="t small" style={{ marginTop: 6 }}>
              <thead><tr><th>Critic claim</th><th>Parameter</th><th>Evidence check</th></tr></thead>
              <tbody>{crit.map((x: any, i: number) => (
                <tr key={i}><td><span className="st info">{x.type}</span><div className="muted">{(x.explanation || "").slice(0, 140)}</div></td><td>{PARAM_LABEL[x.parameter] || x.parameter}</td>
                  <td>{x.accepted === undefined ? <span className="muted">not checked (A4)</span> : x.accepted ? <span className="st ok">ACCEPTED</span> : <><span className="st mute">REJECTED</span><div className="muted">{x.rejected_reason}</div></>}</td></tr>
              ))}</tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}

function Diff({ text }: { text: string }) {
  if (!text.trim()) return <div className="small muted">No change.</div>;
  return (
    <div className="diff">
      {text.split("\n").map((l, i) => {
        const c = l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@") ? "h" : l.startsWith("+") ? "a" : l.startsWith("-") ? "d" : "";
        return <span key={i} className={c}>{l || " "}{"\n"}</span>;
      })}
    </div>
  );
}
