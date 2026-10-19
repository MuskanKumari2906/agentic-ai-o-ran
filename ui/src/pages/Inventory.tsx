import { useEffect, useState } from "react";
import { get, PARAM_LABEL, profileText } from "../api";

export default function Inventory({ go }: { go: (p: string, f?: any) => void }) {
  const [tab, setTab] = useState<"configs" | "clauses">("configs");
  const [data, setData] = useState<any[]>([]);
  const [kb, setKb] = useState<any>(null);
  const [q, setQ] = useState("");
  useEffect(() => { get("/api/dataset").then(setData); get("/api/kb").then(setKb); }, []);

  const counts: Record<string, number> = {};
  data.forEach((d) => (counts[d.category] = (counts[d.category] || 0) + 1));

  return (
    <>
      <div className="page-h">
        <h1>Configs & clauses</h1>
        <span className="sub">Labelled gNB configuration dataset and the clause knowledge base with provenance</span>
        <div className="right">
          <div className="seg">
            <button className={tab === "configs" ? "on" : ""} onClick={() => setTab("configs")}>Dataset ({data.length})</button>
            <button className={tab === "clauses" ? "on" : ""} onClick={() => setTab("clauses")}>Knowledge base ({kb?.clauses?.length ?? 0})</button>
          </div>
        </div>
      </div>
      {tab === "configs" ? (
        <div className="panel">
          <div className="ph"><h3>Dataset</h3>
            <span className="r">{Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>
          </div>
          <div className="pb flush scroll" style={{ maxHeight: "calc(100vh - 160px)" }}>
            <table className="t small">
              <thead><tr><th>ID</th><th>gNB</th><th>Split</th><th>Category</th><th>Vendor</th><th>Profile</th><th>Injected changes</th><th>Ground-truth violations</th><th /></tr></thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.id}</td><td>{d.name}</td><td>{d.split}</td><td>{d.category}</td><td>{d.vendor}</td>
                    <td>{profileText(d.profile)}</td>
                    <td className="mono">{d.mutations.join(", ") || "-"}</td>
                    <td>{d.summary.violations.length ? d.summary.violations.map((v: string) => <span key={v} className="st crit" style={{ marginRight: 3 }}>{PARAM_LABEL[v]}</span>) : <span className="st ok">COMPLIANT</span>}</td>
                    <td><button className="btn sm" onClick={() => go("compliance", { configId: d.id })}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="panel">
          <div className="ph"><h3>Clause knowledge base</h3>
            <span className="r"><input placeholder="Filter" value={q} onChange={(e) => setQ(e.target.value)} style={{ border: "1px solid #c3cad2", padding: "2px 6px", borderRadius: 2 }} /></span>
          </div>
          <div className="pb flush scroll" style={{ maxHeight: "calc(100vh - 160px)" }}>
            <table className="t small">
              <thead><tr><th>Clause</th><th>Source</th><th>Text</th><th>Status</th><th>SHA-256</th></tr></thead>
              <tbody>
                {kb?.clauses?.filter((c: any) => !q || (c.clause_id + c.text + c.title).toLowerCase().includes(q.toLowerCase())).map((c: any) => (
                  <tr key={c.clause_id}>
                    <td className="mono">{c.clause_id}<div className="muted" style={{ fontFamily: "var(--sans)" }}>{c.title}</div></td>
                    <td>{c.doc}<div className="muted">{c.version}</div></td>
                    <td style={{ maxWidth: 560 }}>{c.text}</td>
                    <td>{c.status === "synthetic-policy" ? <span className="st info">SYNTHETIC POLICY</span> : <span className="st warn">PARAPHRASE, UNVERIFIED</span>}</td>
                    <td className="mono muted">{c.sha256.slice(0, 12)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="note" style={{ padding: 10 }}>
              3GPP and O-RAN entries are paraphrases written for this project and must be replaced by the exact sentences of the official
              specifications before any result is published. OSB entries form a synthetic operator security baseline. The SHA-256 manifest is the
              trusted corpus used by the provenance check (C3).
            </p>
          </div>
        </div>
      )}
    </>
  );
}
