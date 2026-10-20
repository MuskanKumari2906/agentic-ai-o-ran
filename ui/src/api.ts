export async function get<T = any>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export async function post<T = any>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status} ${path}`;
    try { const j = await r.json(); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const PARAM_LABEL: Record<string, string> = {
  ciphering_algorithms: "Ciphering algorithms",
  integrity_algorithms: "Integrity algorithms",
  drb_ciphering: "DRB ciphering",
  drb_integrity: "DRB integrity",
  f1c_protection: "F1-C protection",
  n2_protection: "N2 protection",
  n3_protection: "N3 protection",
  xn_protection: "Xn protection",
  e2_protection: "E2 protection",
  o1_transport: "O1 transport",
  tls_min_version: "TLS minimum",
};

export const ARM_NAMES: Record<string, string> = {
  A0: "Rule-based scanner",
  A1: "LLM only",
  A2: "LLM + RAG",
  A3: "Agentic RAG",
  A4: "A3 + LLM reflection",
  A5: "A3 + verifier-grounded reflection",
  A6: "A3 + verifier only",
  A7: "A5 + SMT repair",
  A5x: "A5, cross-family critic",
};

export function fmtVal(v: any): string {
  if (v === null || v === undefined) return "-";
  if (Array.isArray(v)) return "(" + v.join(", ") + ")";
  return String(v);
}

export function hhmm(hour: number): string {
  const h = Math.floor(hour) % 24;
  const m = Math.floor((hour - Math.floor(hour)) * 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function profileText(p: any): string {
  if (!p) return "";
  return `${p.baseline === "operator_hardened" ? "Operator hardened" : "Standards minimum"}, ${p.emergency_unauth_supported ? "emergency sessions required" : "no emergency requirement"}`;
}

export function pct(x: number | null | undefined, d = 1): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "-";
  return (100 * x).toFixed(d) + "%";
}
