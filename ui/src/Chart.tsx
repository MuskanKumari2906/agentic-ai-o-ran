import { useEffect, useRef } from "react";
import * as echarts from "echarts";

const BASE = {
  textStyle: { fontFamily: "IBM Plex Sans, Segoe UI, sans-serif", color: "#4d5866", fontSize: 11 },
  animation: false,
  grid: { left: 48, right: 14, top: 26, bottom: 26, containLabel: false },
  color: ["#0b6fa4", "#c0392b", "#a86300", "#2e7d32", "#6b5b95", "#5f6b7a", "#00897b", "#8d6e63", "#3949ab"],
};

export const axis = {
  axisLine: { lineStyle: { color: "#c3cad2" } },
  axisTick: { lineStyle: { color: "#c3cad2" } },
  splitLine: { lineStyle: { color: "#eceef1" } },
  axisLabel: { color: "#6d7785", fontSize: 10.5 },
  nameTextStyle: { color: "#6d7785", fontSize: 10.5 },
};

export default function Chart({ option, height = 220 }: { option: any; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => inst.current?.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); inst.current?.dispose(); };
  }, []);
  useEffect(() => {
    inst.current?.setOption({ ...BASE, ...option }, true);
  }, [option]);
  return <div ref={ref} style={{ width: "100%", height }} />;
}
