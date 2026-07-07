"use client";

import { Check, ChevronDown, Circle, Loader2, Wrench } from "lucide-react";
import { useEffect, useRef } from "react";

type ToolReasoningProps = {
  name: string;
  status: "idle" | "executing" | "done" | "error";
  args?: Record<string, string | number | boolean | null | undefined>;
};

function formatValue(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") return "未填写";
  return String(value);
}

export function ToolReasoning({ name, status, args }: ToolReasoningProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const entries = Object.entries(args ?? {});
  const isRunning = status === "executing";

  useEffect(() => {
    if (!detailsRef.current) return;
    detailsRef.current.open = isRunning || status === "error";
  }, [isRunning, status]);

  return (
    <details ref={detailsRef} className={`tool-card ${status}`} open={isRunning}>
      <summary>
        <span className="tool-status">
          {isRunning ? <Loader2 className="spin" size={14} /> : status === "done" ? <Check size={14} /> : <Circle size={14} />}
        </span>
        <Wrench size={14} />
        <span>{name}</span>
        <ChevronDown className="tool-chevron" size={14} />
      </summary>
      {entries.length > 0 ? (
        <div className="tool-args">
          {entries.map(([key, value]) => (
            <div key={key}>
              <span>{key}</span>
              <strong>{formatValue(value)}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </details>
  );
}
