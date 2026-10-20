import { useEffect, useState } from "react";
import { get, hhmm, profileText } from "./api";
import { useTwin } from "./twinStore";
import Network from "./pages/Network";
import Assurance from "./pages/Assurance";
import Compliance from "./pages/Compliance";
import Experiments from "./pages/Experiments";
import Inventory from "./pages/Inventory";
import Audit from "./pages/Audit";

const PAGES = [
  { grp: "Operations", items: [["network", "Network topology"], ["assurance", "Assurance"]] },
  { grp: "Security", items: [["compliance", "Compliance console"], ["audit", "Audit trail"]] },
  { grp: "Research", items: [["experiments", "Experiments"], ["inventory", "Configs & clauses"]] },
] as const;

export default function App() {
  const [page, setPage] = useState<string>(() => location.hash.slice(1) || "network");
  const [meta, setMeta] = useState<any>(null);
  const [prog, setProg] = useState<any>(null);
  const [focus, setFocus] = useState<{ configId?: string; site?: number } | null>(null);
  const snap = useTwin();

  useEffect(() => { location.hash = page; }, [page]);
  useEffect(() => {
    const on = () => { const h = location.hash.slice(1); if (h) setPage(h); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    get("/api/meta").then(setMeta).catch(() => {});
    const load = () => get("/api/progress").then(setProg).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const go = (p: string, f?: any) => { setFocus(f || null); setPage(p); };
  const models: string[] = meta?.models || [];
  const backend = meta?.backend;
  const llmOk = !!backend && backend.kind !== "replay";

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand"><b>SecTwin</b><span>O-RAN Security Operations</span></div>
        <div className="ctx">
          <span><span className="k">Network</span>{snap ? `${snap.sites.length} gNB / ${snap.ues.x.length} UE` : "not running"}</span>
          {snap && <span><span className="k">Sim time</span>{hhmm(snap.hour)} ({(snap.t / 60).toFixed(0)} min)</span>}
          {snap?.scenario && <span><span className="k">Profile</span>{profileText(snap.scenario.profile || { baseline: "operator_hardened" })}</span>}
          {snap?.agent && <span><span className="k">SMO agent</span>{snap.agent.arm} ({snap.agent.mode})</span>}
        </div>
        <div className="spacer" />
        {prog?.phase && prog.phase !== "finished" && (
          <span className="pill" title={prog.last}>Experiments {prog.phase}: {prog.phase_done}/{prog.phase_total}</span>
        )}
        <span className={"pill " + (llmOk ? "ok" : "")} title={llmOk ? "Live assessments available" : "Recorded runs are replayed; live assessments need Ollama or an API key"}>{backend ? (llmOk ? `LLM: ${backend.label}` : backend.label) : "..."}</span>
      </div>
      <nav className="nav">
        {PAGES.map((g) => (
          <div key={g.grp}>
            <div className="grp">{g.grp}</div>
            {g.items.map(([id, label]) => (
              <button key={id} className={page === id ? "on" : ""} onClick={() => go(id)}>{label}</button>
            ))}
          </div>
        ))}
        <div className="foot">
          Pinnacle P32, SSN College of Engineering.<br />
          Simulated network. Clause texts are paraphrases pending check against official 3GPP / O-RAN documents.
        </div>
      </nav>
      <main className="main">
        {page === "network" && <Network go={go} focus={focus} />}
        {page === "assurance" && <Assurance go={go} />}
        {page === "compliance" && <Compliance meta={meta} focus={focus} />}
        {page === "experiments" && <Experiments />}
        {page === "inventory" && <Inventory go={go} />}
        {page === "audit" && <Audit />}
      </main>
    </div>
  );
}
