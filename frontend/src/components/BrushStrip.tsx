/** Brush strip — compact sparkline below the speed chart with draggable
 * handles (visx Brush). Dragging the handles zooms the main chart into the
 * selected range. Reset via the button in the chart title or by changing
 * the range/resolution preset. */
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Brush } from "@visx/brush";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";

import type { WindPoint } from "../api";

const ACCENT = "#b45309";
const QC_BAD = "#b91c1c";
const QC_FAULTY = "#b45309";

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
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const xScale = useMemo(
    () => scaleLinear({ domain: [0, Math.max(0, data.length - 1)], range: [0, width] }),
    [data.length, width],
  );

  const yExtent = useMemo<[number, number]>(() => {
    const values = data
      .map((d) => d.mean_wind_ms)
      .filter((v): v is number => v != null);
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

  if (width === 0) return <div ref={containerRef} style={{ height }} className="brush-strip" />;

  return (
    <div ref={containerRef} style={{ height }} className="brush-strip">
      <svg width={width} height={height}>
        <LinePath
          data={data}
          x={(_, i) => xScale(i)}
          y={(d) => (d.mean_wind_ms != null ? yScale(d.mean_wind_ms) : height / 2)}
          stroke={ACCENT}
          strokeWidth={1}
          fill="none"
        />
        {/* QC ticks at the bottom mirror the speed-chart markers so the
         * overview shows the same data-quality story at a glance. */}
        <g>
          {data.map((d, i) => {
            const x = xScale(i);
            if (d.mean_wind_ms == null || d.missing_hours > 0) {
              return <circle key={d.timestamp} cx={x} cy={height - 2} r={1.5} fill={QC_BAD} />;
            }
            if (d.malformed_hours > 0) {
              return (
                <rect
                  key={d.timestamp}
                  x={x - 1.5}
                  y={height - 3.5}
                  width={3}
                  height={3}
                  fill={QC_BAD}
                />
              );
            }
            if (d.suspect_hours > 0) {
              return <circle key={d.timestamp} cx={x} cy={height - 2} r={1.5} fill={QC_FAULTY} />;
            }
            return null;
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
    </div>
  );
}
