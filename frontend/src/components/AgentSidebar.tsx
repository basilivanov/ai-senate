import { useMemo } from "react";
import type { AgentRunState, AgentRunStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { formatDuration } from "@/lib/utils";
import {
  Bug, Code, Database, Shield, Sparkles, Brain, Loader2, CheckCircle2, XCircle, Clock, AlertTriangle, Terminal,
} from "lucide-react";

const AGENT_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  architect: Shield,
  dba: Database,
  coder: Code,
  security: Shield,
  critical: Bug,
  synthesizer: Brain,
  writer: Sparkles,
  minimax27: Bug,
  kimi26: Code,
  minimax: Shield,
  deepseekv4pro: Database,
};

const STATUS_CONFIG: Record<string, { icon: React.ComponentType<{ className?: string }>; text: string; color: string; animate: boolean }> = {
  queued: { icon: Clock, text: "Ожидает", color: "text-muted-foreground", animate: true },
  running: { icon: Loader2, text: "Думает", color: "text-blue-500", animate: true },
  done: { icon: CheckCircle2, text: "Готово", color: "text-emerald-500", animate: false },
  failed: { icon: XCircle, text: "Ошибка", color: "text-rose-500", animate: false },
  failed_parse: { icon: AlertTriangle, text: "Parse error", color: "text-amber-500", animate: false },
  timeout: { icon: Clock, text: "Таймаут", color: "text-rose-500", animate: false },
  waiting: { icon: Clock, text: "Ожидает", color: "text-amber-500", animate: true },
};

const PHASES = [
  { key: "round_1_review", label: "R1", full: "Round 1 — Review" },
  { key: "round_1_consensus", label: "R1⊕", full: "Round 1 — Consensus" },
  { key: "round_2_cross_review", label: "R2", full: "Round 2 — Cross Review" },
  { key: "round_2_consensus", label: "R2⊕", full: "Round 2 — Consensus" },
  { key: "writer", label: "W", full: "Writer" },
  { key: "round_3_final_check", label: "R3", full: "Round 3 — Final Check" },
  { key: "done", label: "✓", full: "Done" },
];

function Dots() {
  return (
    <span className="inline-flex dots-animation">
      <span>.</span><span>.</span><span>.</span>
    </span>
  );
}

interface AgentSidebarCardProps {
  agentKey: string;
  state: AgentRunState;
  isWriter?: boolean;
}

export function AgentSidebarCard({ agentKey, state, isWriter }: AgentSidebarCardProps) {
  const Icon = AGENT_ICON[agentKey] || Terminal;
  const statusCfg = STATUS_CONFIG[state.status] || STATUS_CONFIG.queued;
  const StatusIcon = statusCfg.icon;
  const parsed = state.parsed_output;

  return (
    <div className={`rounded-lg border p-3 transition-all ${statusCfg.color} ${state.status === "done" ? "bg-emerald-500/5 border-emerald-500/20" : state.status === "running" ? "bg-blue-500/5 border-blue-500/20" : "bg-card"}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`shrink-0 ${statusCfg.color}`}>
            {statusCfg.animate && state.status === "running" ? (
              <StatusIcon className={`h-4 w-4 ${statusCfg.animate ? "animate-spin" : ""}`} />
            ) : statusCfg.animate && state.status === "queued" ? (
              <StatusIcon className="h-4 w-4 animate-pulse" />
            ) : (
              <StatusIcon className="h-4 w-4" />
            )}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{isWriter ? "Writer" : agentKey}</div>
            <div className="text-[10px] text-muted-foreground">
              {state.status === "running" ? <>{statusCfg.text}<Dots /></> : statusCfg.text}
            </div>
          </div>
        </div>
        {state.duration_ms ? (
          <span className="text-[10px] text-muted-foreground whitespace-nowrap">{formatDuration(state.duration_ms)}</span>
        ) : null}
      </div>
      {parsed && state.status === "done" && (
        <div className="mt-1.5 text-[11px] space-y-0.5">
          <div className="flex items-center gap-1.5">
            <Badge variant="outline" className={`text-[9px] px-1 py-0 ${statusCfg.color}`}>{parsed.decision}</Badge>
            <span className="text-muted-foreground">{(parsed.confidence * 100).toFixed(0)}%</span>
            <Badge variant="outline" className="text-[9px] px-1 py-0">{parsed.items?.length || 0} items</Badge>
          </div>
          {parsed.summary && (
            <p className="text-muted-foreground line-clamp-2">{parsed.summary}</p>
          )}
        </div>
      )}
      {state.error && state.status !== "done" && (
        <div className="mt-1 text-[10px] text-rose-400 line-clamp-2">{state.error}</div>
      )}
    </div>
  );
}

interface AgentSidebarProps {
  agents: Record<string, AgentRunState>;
  phase: string;
  currentRound: number;
  maxRounds: number;
  profile?: string;
}

export function AgentSidebar({ agents, phase, currentRound, maxRounds, profile }: AgentSidebarProps) {
  const perspectiveEntries = useMemo(() => {
    return Object.entries(agents)
      .filter(([key]) => key !== "writer")
      .map(([key, state]) => ({ key, state }));
  }, [agents]);

  const writerEntry = useMemo(() => {
    const w = agents["writer"];
    return w ? w : null;
  }, [agents]);

  return (
    <aside className="w-[240px] min-w-[240px] lg:w-[320px] lg:min-w-[320px] border-r bg-muted/20 flex flex-col h-full overflow-y-auto">
      <div className="p-3 border-b">
        <h3 className="text-sm font-semibold">Агенты</h3>
        {profile && (
          <div className="text-[10px] text-muted-foreground mt-0.5">Профиль: {profile}</div>
        )}
      </div>

      <div className="p-2 space-y-2 flex-1">
        {perspectiveEntries.map(({ key, state }) => (
          <AgentSidebarCard key={key} agentKey={key} state={state} />
        ))}
        {writerEntry && (
          <>
            <div className="border-t my-2" />
            <AgentSidebarCard agentKey="writer" state={writerEntry} isWriter />
          </>
        )}
      </div>

      <PhaseProgress phase={phase} currentRound={currentRound} maxRounds={maxRounds} />
    </aside>
  );
}

interface PhaseProgressProps {
  phase: string;
  currentRound: number;
  maxRounds: number;
}

export function PhaseProgress({ phase, currentRound, maxRounds }: PhaseProgressProps) {
  let currentIdx = PHASES.findIndex(p => p.key === phase);
  if (currentIdx === -1) {
    if (phase === "queued") currentIdx = -1;
    else currentIdx = 0;
  }

  // Early exit: if writer_enabled is false and phase is done after round 1
  const visiblePhases = PHASES.filter(p => {
    if (maxRounds < 2 && (p.key.startsWith("round_2") || p.key === "round_3_final_check")) return false;
    if (maxRounds < 3 && p.key === "round_3_final_check") return false;
    return true;
  });

  return (
    <div className="p-3 border-t bg-muted/30">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">
        {PHASES[currentIdx]?.full || phase}
      </div>
      <div className="flex items-center gap-1">
        {visiblePhases.map((p, i) => {
          const isCompleted = i < currentIdx;
          const isCurrent = i === currentIdx;
          return (
            <div
              key={p.key}
              className={`flex-1 h-1.5 rounded-full transition-all ${
                isCompleted ? "bg-emerald-500"
                : isCurrent ? "bg-blue-500 animate-pulse"
                : "bg-muted"
              }`}
              title={p.full}
            />
          );
        })}
      </div>
    </div>
  );
}

export { PHASES, STATUS_CONFIG, AGENT_ICON };