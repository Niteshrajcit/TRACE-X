import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export function riskLevelFromScore(score: number): RiskLevel {
  if (score >= 0.75) return "critical";
  if (score >= 0.5) return "high";
  if (score >= 0.25) return "medium";
  return "low";
}

export function RiskPill({ level, label }: { level: RiskLevel; label?: string }) {
  const text = label ?? level;
  return (
    <span className={`pill pill-risk-${level}`}>
      <span className="dot" />
      {text}
    </span>
  );
}

export function Pill({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "accent" | "decision" | "ok";
  children: ReactNode;
}) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function StatCard({
  label,
  value,
  unit,
  icon,
  trend,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  icon?: ReactNode;
  trend?: { direction: "up" | "down" | "flat"; label: string };
}) {
  return (
    <div className="stat-card">
      {icon && <span className="stat-icon">{icon}</span>}
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </span>
      {trend && <span className={`stat-trend ${trend.direction}`}>{trend.label}</span>}
    </div>
  );
}

export function Panel({
  title,
  meta,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`panel ${className}`}>
      {(title || actions) && (
        <div className="panel-header">
          {title && <h3>{title}</h3>}
          {meta && <span className="meta">{meta}</span>}
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="state-block">
      <span className="state-icon">{icon ?? <Inbox size={28} strokeWidth={1.5} />}</span>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state-block">
      <span className="state-icon">
        <Loader2 size={26} strokeWidth={1.5} className="spin" />
      </span>
      <p>{label}</p>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-block">
      <span className="state-icon" style={{ color: "var(--danger)" }}>
        <AlertTriangle size={26} strokeWidth={1.5} />
      </span>
      <h3>Could not load this data</h3>
      <p className="error-text">{message}</p>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export interface TimelineEvent {
  id: string;
  title: string;
  time?: string;
  description?: string;
  tone?: "default" | "done" | "decision" | "critical";
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="timeline">
      {events.map((event, i) => (
        <div key={event.id} className={`timeline-item ${event.tone ?? "done"}`}>
          <div className="timeline-rail">
            <span className="timeline-dot" />
            {i < events.length - 1 && <span className="timeline-line" />}
          </div>
          <div className="timeline-body">
            <div className="row between">
              <span className="timeline-title">{event.title}</span>
              {event.time && <span className="timeline-time">{event.time}</span>}
            </div>
            {event.description && <p className="timeline-desc">{event.description}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}
