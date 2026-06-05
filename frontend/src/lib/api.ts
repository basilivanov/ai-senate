import type {
  AgentArtifactMeta,
  AgentStatusRow,
  ChangesSummary,
  ConsensusResult,
  CreateRunRequest,
  FindingsByCategory,
  GitDiffInput,
  GitDiffResponse,
  PerspectivesConfig,
  ProjectDigestResponse,
  ProjectInput,
  RunDetail,
  RunSummary,
  UpdatedDocsResponse,
} from "./types";

const BASE = "/api";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  listRuns: () => http<RunSummary[]>("/runs"),
  getRun: (id: string) => http<RunDetail>(`/runs/${id}`),
  createRun: (body: CreateRunRequest) =>
    http<RunSummary>("/runs", { method: "POST", body: JSON.stringify(body) }),
  deleteRun: (id: string) => http<void>(`/runs/${id}`, { method: "DELETE" }),
  getFindings: (id: string) => http<FindingsByCategory>(`/runs/${id}/findings`),
  getConsensus: (id: string) => http<ConsensusResult>(`/runs/${id}/consensus`),
  getUpdatedSpec: (id: string) => http<{ content: string }>(`/runs/${id}/updated-spec`),
  getUpdatedDocs: (id: string) => http<UpdatedDocsResponse>(`/runs/${id}/updated-docs`),
  getChanges: (id: string) => http<ChangesSummary>(`/runs/${id}/changes`),
  getRoundLog: (id: string) => http<{ round_log: Array<Record<string, unknown>> }>(`/runs/${id}/round-log`),
  getAgentStatuses: (id: string) => http<AgentStatusRow[]>(`/runs/${id}/agents`),
  getAgentArtifact: (id: string, agent: string, round: number) =>
    http<AgentArtifactMeta>(`/runs/${id}/rounds/${round}/agents/${agent}`),
  acceptSpec: (id: string) => http<{ status: string }>(`/runs/${id}/accept`, { method: "POST" }),
  getConfig: () => http<PerspectivesConfig>("/config"),
  getSpec: () => http<{ content: string }>("/spec"),
  saveSpec: (content: string) =>
    http<{ status: string }>("/spec", { method: "PUT", body: JSON.stringify({ content }) }),
  health: () => http<{ status: string; opencode: { reachable: boolean; base_url: string } }>("/health"),
  projectDigest: (body: ProjectInput) =>
    http<ProjectDigestResponse>("/project/digest", { method: "POST", body: JSON.stringify(body) }),
  projectGitDiff: (body: GitDiffInput) =>
    http<GitDiffResponse>("/project/git-diff", { method: "POST", body: JSON.stringify(body) }),
};