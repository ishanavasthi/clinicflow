"use client";

import { useReducedMotion } from "framer-motion";
import { useCallStore } from "@/stores/callStore";

const DEPARTMENTS = [
  "Emergency",
  "General Medicine",
  "Pediatrics",
  "Orthopedics",
  "Cardiology",
];

// Fixed SVG geometry for the switchboard.
const W = 320;
const H = 220;
const HUB = { x: 78, y: H / 2 };
const NODE = { x: 196, w: 118, h: 30 };
const ys = DEPARTMENTS.map((_, i) => 22 + i * ((H - 44) / (DEPARTMENTS.length - 1)));

function connectorPath(y: number): string {
  return `M ${HUB.x} ${HUB.y} C ${HUB.x + 60} ${HUB.y}, ${NODE.x - 60} ${y}, ${NODE.x} ${y}`;
}

/**
 * The signature element: a routing switchboard. Reception is the hub wired to
 * every department; when the agent routes a caller, that connector lights up
 * with a traveling pulse and the node highlights (rose for an emergency).
 */
export function DepartmentFlow() {
  const routing = useCallStore((s) => s.routing);
  const reduced = useReducedMotion();
  const active = routing?.department ?? null;
  const emergency = routing?.emergency ?? false;

  return (
    <div className="flex flex-col gap-3">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="Department routing switchboard"
      >
        {/* Connectors */}
        {DEPARTMENTS.map((dept, i) => {
          const isActive = dept === active;
          const isEmergency = isActive && emergency;
          const color = isEmergency
            ? "var(--emergency)"
            : isActive
              ? "var(--primary)"
              : "var(--border)";
          const path = connectorPath(ys[i]);
          return (
            <g key={`edge-${dept}`}>
              <path
                d={path}
                fill="none"
                stroke={color}
                strokeWidth={isActive ? 2 : 1}
                opacity={isActive ? 1 : 0.5}
              />
              {isActive && !reduced && (
                <circle r={3.2} fill={color}>
                  <animateMotion
                    dur={isEmergency ? "0.9s" : "1.5s"}
                    repeatCount="indefinite"
                    path={path}
                  />
                </circle>
              )}
            </g>
          );
        })}

        {/* Hub */}
        <g>
          <circle
            cx={HUB.x}
            cy={HUB.y}
            r={26}
            fill="var(--card)"
            stroke="var(--primary)"
            strokeWidth={1.5}
          />
          <text
            x={HUB.x}
            y={HUB.y + 3}
            textAnchor="middle"
            className="fill-foreground"
            fontSize={9}
            fontWeight={600}
          >
            Reception
          </text>
        </g>

        {/* Department nodes */}
        {DEPARTMENTS.map((dept, i) => {
          const isActive = dept === active;
          const isEmergency = isActive && emergency;
          const stroke = isEmergency
            ? "var(--emergency)"
            : isActive
              ? "var(--primary)"
              : "var(--border)";
          const fill = isEmergency
            ? "color-mix(in oklch, var(--emergency) 16%, var(--card))"
            : isActive
              ? "color-mix(in oklch, var(--primary) 14%, var(--card))"
              : "var(--card)";
          return (
            <g key={`node-${dept}`}>
              <rect
                x={NODE.x}
                y={ys[i] - NODE.h / 2}
                width={NODE.w}
                height={NODE.h}
                rx={9}
                fill={fill}
                stroke={stroke}
                strokeWidth={isActive ? 1.5 : 1}
                opacity={isActive ? 1 : 0.85}
              />
              <text
                x={NODE.x + NODE.w / 2}
                y={ys[i] + 3.5}
                textAnchor="middle"
                fontSize={10}
                className={isActive ? "fill-foreground" : "fill-muted-foreground"}
                fontWeight={isActive ? 600 : 400}
              >
                {dept}
              </text>
            </g>
          );
        })}
      </svg>

      <p
        className={`text-xs ${emergency ? "font-medium text-emergency" : "text-muted-foreground"}`}
      >
        {routing
          ? `${emergency ? "Emergency routing" : "Routed"}: ${routing.reason}`
          : "Awaiting routing decision."}
      </p>
    </div>
  );
}
