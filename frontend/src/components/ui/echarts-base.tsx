"use client";

/**
 * Minimal, real ECharts wrapper — init/resize/dispose lifecycle only. Deliberately
 * not a full "compound component" abstraction layer (no per-chart-type builder
 * DSL): with a handful of charts on one dashboard, a thin wrapper around the real
 * library is less code to maintain than reproducing its own component system.
 *
 * Chart types/components are registered once, here, tree-shaken to only what
 * this dashboard actually uses (boxplot + sankey + their shared infra) rather
 * than importing all of ECharts.
 */

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BoxplotChart, LineChart, SankeyChart } from "echarts/charts";
import {
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ComposeOption } from "echarts/core";
import type { BoxplotSeriesOption, LineSeriesOption, SankeySeriesOption } from "echarts/charts";
import type {
  GraphicComponentOption,
  GridComponentOption,
  LegendComponentOption,
  MarkLineComponentOption,
  TitleComponentOption,
  TooltipComponentOption,
} from "echarts/components";

echarts.use([
  BoxplotChart,
  LineChart,
  SankeyChart,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export type EChartsOption = ComposeOption<
  | BoxplotSeriesOption
  | LineSeriesOption
  | SankeySeriesOption
  | GraphicComponentOption
  | GridComponentOption
  | LegendComponentOption
  | MarkLineComponentOption
  | TitleComponentOption
  | TooltipComponentOption
>;

/** Shared frosted-glass tooltip chrome, matching the app's dark/gold surface tokens. */
export const TOOLTIP_STYLE = {
  backgroundColor: "rgba(10,10,10,0.92)",
  borderColor: "rgba(234,179,8,0.25)",
  borderWidth: 1,
  borderRadius: 10,
  padding: [10, 12] as [number, number],
  textStyle: { color: "#fff", fontSize: 13 },
  extraCssText: "backdrop-filter: blur(10px); box-shadow: 0 8px 32px rgba(0,0,0,0.5);",
};

export function EChartsBase({
  option,
  height = 280,
  className,
  onEvents,
}: {
  option: EChartsOption;
  height?: number;
  className?: string;
  onEvents?: Record<string, (params: unknown) => void>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onEvents) return;
    for (const [name, handler] of Object.entries(onEvents)) chart.on(name, handler);
    return () => {
      for (const name of Object.keys(onEvents)) chart.off(name);
    };
  }, [onEvents]);

  return <div ref={ref} style={{ height }} className={className ?? "w-full"} />;
}
