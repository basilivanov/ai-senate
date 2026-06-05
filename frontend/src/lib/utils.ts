import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function formatDuration(ms?: number) {
  if (!ms || ms <= 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}m ${r}s`;
}

export function phaseLabel(phase?: string) {
  if (!phase) return "—";
  const map: Record<string, string> = {
    queued: "Queued",
    round_1_review: "Round 1 — Independent Review",
    round_1_consensus: "Round 1 — Consensus",
    round_2_cross_review: "Round 2 — Cross Review",
    round_2_consensus: "Round 2 — Consensus",
    writer: "Writer",
    round_3_final_check: "Round 3 — Final Check",
    done: "Done",
  };
  return map[phase] || phase;
}

export function statusColor(status?: string) {
  switch (status) {
    case "done":
    case "accepted":
    case "passed":
      return "text-emerald-500";
    case "running":
    case "queued":
    case "writing":
      return "text-blue-500";
    case "blocked":
    case "failed":
    case "rejected":
      return "text-rose-500";
    case "accepted_with_changes":
    case "needs_followup":
    case "needs_human_decision":
      return "text-amber-500";
    default:
      return "text-muted-foreground";
  }
}

export const FINDING_TYPE_LABEL: Record<string, string> = {
  blocker: "Blocker",
  major_risk: "Major Risk",
  risk: "Risk",
  suggestion: "Suggestion",
  question: "Question",
  info: "Info",
};

export const FINDING_TYPE_TONE: Record<string, string> = {
  blocker: "bg-rose-500/15 text-rose-600 dark:text-rose-300 border-rose-500/30",
  major_risk: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
  risk: "bg-orange-500/10 text-orange-700 dark:text-orange-300 border-orange-500/30",
  suggestion: "bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/30",
  question: "bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/30",
  info: "bg-slate-500/10 text-slate-600 dark:text-slate-300 border-slate-500/30",
};

export const SEVERITY_TONE: Record<string, string> = {
  high: "bg-rose-500",
  medium: "bg-amber-500",
  low: "bg-slate-400",
};
