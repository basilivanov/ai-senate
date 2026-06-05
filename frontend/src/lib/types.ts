// API contracts — mirror of FastAPI Pydantic v2 schemas

export type RunStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "blocked"
  | "accepted"
  | "accepted_with_changes"
  | "needs_followup"
  | "needs_human_decision"
  | "rejected";

export type RunPhase =
  | "queued"
  | "round_1_review"
  | "round_1_consensus"
  | "round_2_cross_review"
  | "round_2_consensus"
  | "writer"
  | "round_3_final_check"
  | "done";

export interface RunSummary {
  id: string;
  status: string;
  created_at: string;
  updated_at: string;
  new_document: boolean;
  max_rounds: number;
  current_round: number;
  auto_stop_if_clean: boolean;
  phase: string;
}

export type AgentRunStatus = "queued" | "running" | "done" | "failed" | "failed_parse" | "timeout" | "waiting";

export interface AgentRunState {
  status: AgentRunStatus;
  duration_ms?: number;
  error?: string | null;
  parsed_output?: FindingAgentResponse | null;
}

export interface RoundEntry {
  round: number | string;
  phase: string;
  status: string;
  summary: string;
  counts?: Record<string, number>;
  agent_status?: Record<string, number>;
}

export interface RunDetail {
  run_id: string;
  status: string;
  phase: string;
  current_round: number;
  max_rounds: number;
  auto_stop_if_clean: boolean;
  new_document: boolean;
  started_at?: string;
  finished_at?: string;
  agents: Record<string, AgentRunState>;
  round_log: RoundEntry[];
}

export interface Finding {
  id: string;
  agent: string;
  role: string;
  type: "blocker" | "major_risk" | "risk" | "suggestion" | "question" | "info";
  category: string;
  severity: "low" | "medium" | "high";
  title: string;
  description: string;
  evidence?: string;
  recommendation?: string;
  confidence: number;
}

export interface FindingsByCategory {
  blockers: Finding[];
  major_risks: Finding[];
  risks: Finding[];
  suggestions: Finding[];
  questions: Finding[];
  infos: Finding[];
}

export interface FindingAgentResponse {
  schema_version: string;
  agent: string;
  role: string;
  decision: string;
  confidence: number;
  summary: string;
  items: Finding[];
  open_questions: string[];
  required_actions: string[];
}

export interface ConsensusResult {
  schema_version: string;
  run_id: string;
  status: string;
  summary: string;
  agent_status: Record<string, number>;
  counts: Record<string, number>;
  decision_votes: Record<string, number>;
  required_actions: string[];
  unresolved_questions: string[];
}

export interface ChangesSummary {
  added: string[];
  changed: string[];
  removed: string[];
  kept_unresolved: string[];
}

export interface AgentStatusRow {
  agent: string;
  status: AgentRunStatus;
  duration_ms?: number;
  exit_code?: number;
  timeout?: boolean;
  parsed?: boolean;
  error?: string | null;
  role?: string;
}

export interface AgentArtifactMeta {
  agent: string;
  status: AgentRunStatus;
  duration_ms?: number;
  error?: string | null;
  raw_output?: string;
  parsed_output?: FindingAgentResponse | null;
  system_prompt?: string;
  user_prompt?: string;
}

export interface AgentPerspective {
  key: string;
  role: string;
  provider: string;
  model: string;
  enabled: boolean;
  timeout_sec: number;
}

export interface JuryConfig {
  default: string[];
  synthesis: string[];
}

export interface PerspectivesConfig {
  perspectives: AgentPerspective[];
  writer: AgentPerspective | null;
  juries: JuryConfig;
}

export interface CreateRunRequest {
  spec_text: string;
  owner_input: string;
  new_document: boolean;
  max_rounds: number;
  auto_stop_if_clean: boolean;
}
