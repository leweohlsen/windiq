/** Brush strip — compact sparkline below the speed chart with draggable
 * handles (visx Brush). Dragging the handles zooms the main chart into the
 * selected range. Reset via the button in the chart title or by changing
 * the range/resolution preset. */
import { useMemo } from "react";
import { Brush } from "@visx/brush";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";

import type { WindPoint } from "../api";
import { useChartSize } from "./chart/useChartSize";

const ACCENT = "#b45309";
const INTERPOLATED = "#f59e0b";

export function BrushStrip({
  data,
  zoomDomain,
  onZoomChange,
  height = 40,
}: {
  data: WindPoint[];
  zoomDomain: [string, string] | null;
  onZoomChange: (domain: [string, string] | null) => void;
  height?: number;
}) {
  const { ref, width } = useChartSize();

  const xScale = useMemo(
    () => scaleLinear({ domain: [0, Math.max(0, data.length - 1)], range: [0, width] }),
    [data.length, width],
  );

  const yExtent = useMemo<[number, number]>(() => {
    const values = data.map((d) => d.mean_wind_ms).filter((v): v is number => v != null);
    if (values.length === 0) return [0, 1];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = (max - min) * 0.1 || 1;
    return [Math.max(0, min - pad), max + pad];
  }, [data]);

  const yScale = useMemo(
    () => scaleLinear({ domain: yExtent, range: [height - 4, 4] }),
    [yExtent, height],
  );

  const initialBrushPosition = useMemo(() => {
    if (!zoomDomain) return undefined;
    const startIdx = data.findIndex((d) => d.timestamp >= zoomDomain[0]);
    const endIdx = data.findIndex((d) => d.timestamp >= zoomDomain[1]);
    if (startIdx === -1 || endIdx === -1) return undefined;
    return { start: { x: startIdx }, end: { x: endIdx } };
  }, [zoomDomain, data]);

  const handleBrushEnd = (bounds: { x0: number; x1: number } | null) => {
    if (!bounds) {
      onZoomChange(null);
      return;
    }
    const startIdx = Math.max(0, Math.floor(bounds.x0));
    const endIdx = Math.min(data.length - 1, Math.ceil(bounds.x1));
    if (startIdx >= endIdx) {
      onZoomChange(null);
      return;
    }
    const startPoint = data[startIdx];
    const endPoint = data[endIdx];
    if (!startPoint || !endPoint) {
      onZoomChange(null);
      return;
    }
    onZoomChange([startPoint.timestamp, endPoint.timestamp]);
  };

  return (
    <div ref={ref} style={{ height }} className="brush-strip">
      {width > 0 && (
        <svg width={width} height={height}>
          <LinePath
            data={data}
            x={(_, i) => xScale(i)}
            y={(d) => (d.mean_wind_ms != null ? yScale(d.mean_wind_ms) : height / 2)}
            stroke={ACCENT}
            strokeWidth={1}
            fill="none"
          />
          {/* Interpolation ticks at the bottom mirror the speed-chart markers
           * so the overview shows the same story at a glance. */}
          <g>
            {data.map((d, i) => {
              if (d.interpolated_hours === 0 && d.mean_wind_ms != null) return null;
              return (
                <circle
                  key={d.timestamp}
                  cx={xScale(i)}
                  cy={height - 2}
                  r={1.5}
                  fill={d.mean_wind_ms == null ? ACCENT : INTERPOLATED}
                />
              );
            })}
          </g>
          <Brush
            xScale={xScale}
            yScale={yScale}
            width={width}
            height={height}
            handleSize={6}
            disableDraggingSelection={false}
            initialBrushPosition={initialBrushPosition}
            onBrushEnd={handleBrushEnd}
            selectedBoxStyle={{
              fill: ACCENT,
              fillOpacity: 0.15,
              stroke: ACCENT,
              strokeWidth: 1,
            }}
            useWindowMoveEvents
          />
        </svg>
      )}
    </div>
  );
}
