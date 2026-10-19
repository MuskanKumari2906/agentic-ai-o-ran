// Single WebSocket connection to the twin, shared by every page.
import { useEffect, useState } from "react";

type Listener = (s: any) => void;
let snap: any = null;
let ws: WebSocket | null = null;
const listeners = new Set<Listener>();

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/twin`);
  ws.onmessage = (e) => {
    try {
      snap = JSON.parse(e.data);
      listeners.forEach((l) => l(snap));
    } catch {}
  };
  ws.onclose = () => setTimeout(connect, 1500);
}

export function useTwin() {
  const [s, setS] = useState<any>(snap);
  useEffect(() => {
    connect();
    listeners.add(setS);
    return () => { listeners.delete(setS); };
  }, []);
  return s;
}
