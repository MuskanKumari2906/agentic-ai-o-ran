import { useEffect, useState } from "react";
import { fmtVal, get, PARAM_LABEL } from "../api";

export default function Audit() {
  const [d, setD] = useState<any>(null);
  const load = () => get("/api/audit").then(setD);
  useEffect(() => { load(); }, []);
  const v = d?.verify;
  return (
    <>
      <div className="page-h">
        <h1>Audit trail</h1>
        <span className="sub">Append-only, hash-chained record of every assessment run from the console</span>
        <div className="right">
          {v && (v.ok ? <span className="st ok">CHAIN INTACT &middot; {v.entries} ENTRIES</span> : <span className="st crit">CHAIN BROKEN AT ENTRY {v.broken_at}</span>)}
          <button className="btn" onClick={load}>Verify chain</button>
        </div>
      </div>
      <div className="panel">
        <div className="ph"><h3>Entries</h3><span className="r mono">{v?.head ? `head ${v.head.slice(0, 20)}...` : ""}</span></div>
        <div className="pb flush scroll" style={{ maxHeight: "calc(100vh - 160px)" }}>
          <table className="t small">
            <thead><tr><th>Time</th><th>Type</th><th>Config</th><th>Agent</th><th>Predicted violations</th><th>Fixes</th><th>Config SHA-256</th><th>Entry hash</th><th>Previous</th></tr></thead>
            <tbody>
              {(d?.entries || []).slice().reverse().map((e: any, i: number) => (
                <tr key={i}>
                  <td className="mono">{e.ts.replace("T", " ")}</td>
                  <td>{e.kind}</td>
                  <td className="mono">{e.record.config_id}</td>
                  <td>{e.record.arm}<div className="muted">{e.record.model}</div></td>
                  <td>{e.record.predicted?.length ? e.record.predicted.map((p: string) => PARAM_LABEL[p] || p).join(", ") : "none"}</td>
                  <td className="mono">{Object.entries(e.record.fixes || {}).map(([k, v]) => `${k}=${fmtVal(v)}`).join("; ") || "-"}</td>
                  <td className="mono muted">{e.record.config_sha256?.slice(0, 12)}</td>
                  <td className="mono">{e.entry_hash.slice(0, 12)}</td>
                  <td className="mono muted">{e.prev_hash.slice(0, 12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!d?.entries?.length && <div className="empty">No entries yet. Run an assessment from the compliance console.</div>}
        </div>
      </div>
    </>
  );
}
