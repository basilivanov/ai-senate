import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, AlertTriangle, Info, AlertCircle, Shield, Bug, Database, Code, Brain, Sparkles, RefreshCw, Download, GitBranch } from "lucide-react";
import ReactMarkdown from "react-markdown";

import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { formatDate, formatDuration, phaseLabel, statusColor, FINDING_TYPE_LABEL, FINDING_TYPE_TONE, SEVERITY_TONE } from "@/lib/utils";
import { AgentSidebar } from "@/components/AgentSidebar";
import type { Finding } from "@/lib/types";

export function RunPage() {
  const { id = "" } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<string>("findings");

  const run = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.getRun(id),
    refetchInterval: (q) => {
      const data = q.state.data as { status?: string } | undefined;
      return data && ["done", "failed", "blocked", "rejected"].includes(String(data.status)) ? false : 2000;
    },
  });
  const findings = useQuery({ queryKey: ["findings", id], queryFn: () => api.getFindings(id), enabled: !!run.data });
  const consensus = useQuery({ queryKey: ["consensus", id], queryFn: () => api.getConsensus(id), enabled: !!run.data });
  const spec = useQuery({ queryKey: ["updated-spec", id], queryFn: () => api.getUpdatedSpec(id), enabled: !!run.data });
  const updatedDocs = useQuery({ queryKey: ["updated-docs", id], queryFn: () => api.getUpdatedDocs(id), enabled: !!run.data });
  const changes = useQuery({ queryKey: ["changes", id], queryFn: () => api.getChanges(id), enabled: !!run.data });

  const accept = useMutation({
    mutationFn: () => api.acceptSpec(id),
    onSuccess: () => alert("Спецификация принята и сохранена в data/spec.md"),
  });

  const [prUrl, setPrUrl] = useState("");
  const [postCommentResult, setPostCommentResult] = useState<string | null>(null);
  const postComment = useMutation({
    mutationFn: (url: string) => api.postComment(id, url),
    onSuccess: (data) => setPostCommentResult(data.status),
    onError: (e) => setPostCommentResult(`Error: ${e}`),
  });

  const agentEntries = useMemo(() => {
    const data = run.data;
    if (!data) return [];
    return Object.entries(data.agents).map(([key, a]) => ({ key, ...a }));
  }, [run.data]);

  const hasMultiDoc = useMemo(() => {
    return updatedDocs.data && Object.keys(updatedDocs.data.documents || {}).length > 1;
  }, [updatedDocs.data]);

  if (run.isLoading) return <CenterShell><Spinner /> Загрузка запуска…</CenterShell>;
  if (run.isError) return <CenterShell><Alert variant="destructive"><AlertTitle>Не удалось загрузить</AlertTitle><AlertDescription>{String(run.error)}</AlertDescription></Alert></CenterShell>;
  if (!run.data) return null;

  const d = run.data;
  const c = consensus.data;
  const f = findings.data;
  const totalFindings =
    (f?.blockers.length || 0) + (f?.major_risks.length || 0) + (f?.risks.length || 0) + (f?.suggestions.length || 0) + (f?.questions.length || 0) + (f?.infos.length || 0);

  return (
    <div className="flex h-[calc(100vh-3rem)]">
      {/* Left sidebar: agents */}
      <AgentSidebar
        agents={d.agents}
        phase={d.phase}
        currentRound={d.current_round}
        maxRounds={d.max_rounds}
        profile={d.profile}
      />

      {/* Right: main content */}
      <main className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Link to="/" className="hover:underline flex items-center gap-1">
                <ArrowLeft className="h-3 w-3" /> Назад
              </Link>
              <span>·</span>
              <span className="font-mono">{d.run_id}</span>
              {d.profile && <><span>·</span><Badge variant="outline" className="text-[10px]">{d.profile}</Badge></>}
            </div>
            <h1 className="text-2xl font-semibold mt-1">{d.new_document ? "Новый документ" : "Ревью ТЗ"}</h1>
            <div className="text-sm text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>Phase: <span className="text-foreground font-medium">{phaseLabel(d.phase)}</span></span>
              <span>·</span>
              <span>Status: <span className={`font-medium ${statusColor(d.status)}`}>{d.status}</span></span>
              <span>·</span>
              <span>Round: {d.current_round}/{d.max_rounds}</span>
              {d.started_at && <><span>·</span><span>Started: {formatDate(d.started_at)}</span></>}
              {d.finished_at && <><span>·</span><span>Finished: {formatDate(d.finished_at)}</span></>}
            </div>
            {d.project && (
              <div className="text-xs text-muted-foreground mt-1">
                Project: {d.project.path} · {d.project.files_included} files · {d.project.truncated ? "truncated" : "complete"}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => qc.invalidateQueries({ queryKey: ["run", id] })}>
              <RefreshCw className="h-3.5 w-3.5" /> Обновить
            </Button>
            {d.status === "done" && spec.data?.content && (
              <Button size="sm" onClick={() => accept.mutate()} disabled={accept.isPending}>
                {accept.isPending ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />}
                Принять
              </Button>
            )}
            {d.status === "done" && (
              <div className="flex items-center gap-1">
                <Input
                  placeholder="PR URL"
                  value={prUrl}
                  onChange={(e) => { setPrUrl(e.target.value); setPostCommentResult(null); }}
                  className="w-48 h-8 text-xs"
                />
                <Button size="sm" variant="outline" onClick={() => postComment.mutate(prUrl)} disabled={!prUrl.trim() || postComment.isPending}>
                  {postComment.isPending ? <Spinner /> : <GitBranch className="h-3.5 w-3.5" />}
                  Post to PR
                </Button>
                {postCommentResult && <span className="text-xs text-muted-foreground">{postCommentResult}</span>}
              </div>
            )}
          </div>
        </div>

        {c && <ConsensusCard consensus={c} totalFindings={totalFindings} />}

        <Tabs defaultValue={hasMultiDoc ? "docs" : "findings"}>
          <TabsList>
            <TabsTrigger active={activeTab === "findings"} onClick={() => setActiveTab("findings")}>Findings ({totalFindings})</TabsTrigger>
            <TabsTrigger active={activeTab === "consensus"} onClick={() => setActiveTab("consensus")}>Consensus</TabsTrigger>
            {hasMultiDoc ? <TabsTrigger active={activeTab === "docs"} onClick={() => setActiveTab("docs")}>Documents</TabsTrigger> : <TabsTrigger active={activeTab === "spec"} onClick={() => setActiveTab("spec")}>Spec</TabsTrigger>}
            <TabsTrigger active={activeTab === "changes"} onClick={() => setActiveTab("changes")}>Changes</TabsTrigger>
            <TabsTrigger active={activeTab === "log"} onClick={() => setActiveTab("log")}>Log</TabsTrigger>
          </TabsList>

          <TabsContent>
            {activeTab === "findings" && (findings.isLoading ? (
              <Skeleton className="h-64" />
            ) : f ? (
              <FindingsPanel findings={f} />
            ) : null)}
          </TabsContent>

          <TabsContent>
            {activeTab === "consensus" && (consensus.isLoading ? (
              <Skeleton className="h-40" />
            ) : c ? (
              <ConsensusDetail consensus={c} />
            ) : null)}
          </TabsContent>

          <TabsContent>
            {activeTab === (hasMultiDoc ? "docs" : "spec") && (hasMultiDoc ? (
              updatedDocs.isLoading ? (
                <Skeleton className="h-96" />
              ) : updatedDocs.data ? (
                <MultiDocPanel docs={updatedDocs.data.documents} />
              ) : null
            ) : (
              spec.isLoading ? (
                <Skeleton className="h-96" />
              ) : spec.data?.content ? (
                <UpdatedSpecPanel content={spec.data.content} />
              ) : (
                <EmptyState text="Writer не сгенерировал обновлённую спецификацию" />
              )
            ))}
          </TabsContent>

          <TabsContent>
            {activeTab === "changes" && (changes.isLoading ? (
              <Skeleton className="h-40" />
            ) : changes.data ? (
              <ChangesPanel changes={changes.data} />
            ) : null)}
          </TabsContent>

          <TabsContent>
            {activeTab === "log" && <RoundLogPanel entries={d.round_log || []} />}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function CenterShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="text-sm text-muted-foreground flex items-center gap-2">{children}</div>
    </div>
  );
}

function ConsensusCard({ consensus, totalFindings }: { consensus: import("@/lib/types").ConsensusResult; totalFindings: number }) {
  const variant: "default" | "destructive" | "warning" | "success" =
    ["blocked", "rejected", "failed"].includes(consensus.status) ? "destructive"
    : ["needs_followup", "needs_human_decision", "accepted_with_changes"].includes(consensus.status) ? "warning"
    : consensus.status === "done" || consensus.status === "accepted" ? "success"
    : "default";
  return (
    <Alert variant={variant}>
      <AlertTitle className="text-base flex items-center gap-2">
        <span className={`font-semibold ${statusColor(consensus.status)}`}>{consensus.status}</span>
        <span className="text-muted-foreground font-normal">— {consensus.summary}</span>
      </AlertTitle>
      <AlertDescription>
        <div className="flex flex-wrap gap-2 mt-2 text-xs">
          {Object.entries(consensus.counts || {}).map(([k, v]) => (
            <Badge key={k} className={FINDING_TYPE_TONE[k] || ""}>{FINDING_TYPE_LABEL[k] || k}: {v as number}</Badge>
          ))}
          <Badge variant="outline">All findings: {totalFindings}</Badge>
        </div>
      </AlertDescription>
    </Alert>
  );
}

function FindingsPanel({ findings }: { findings: import("@/lib/types").FindingsByCategory }) {
  const groups: { key: keyof import("@/lib/types").FindingsByCategory; title: string; icon: React.ReactNode }[] = [
    { key: "blockers", title: "Blockers", icon: <AlertCircle className="h-4 w-4 text-rose-500" /> },
    { key: "major_risks", title: "Major Risks", icon: <AlertTriangle className="h-4 w-4 text-amber-500" /> },
    { key: "risks", title: "Risks", icon: <AlertTriangle className="h-4 w-4 text-orange-500" /> },
    { key: "suggestions", title: "Suggestions", icon: <Sparkles className="h-4 w-4 text-sky-500" /> },
    { key: "questions", title: "Questions", icon: <Info className="h-4 w-4 text-violet-500" /> },
    { key: "infos", title: "Info", icon: <Info className="h-4 w-4 text-slate-500" /> },
  ];
  return (
    <div className="space-y-6">
      {groups.map((g) => {
        const items = findings[g.key] || [];
        if (items.length === 0) return null;
        return (
          <section key={g.key}>
            <div className="flex items-center gap-2 mb-3">
              {g.icon}
              <h3 className="font-semibold">{g.title}</h3>
              <Badge variant="outline">{items.length}</Badge>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {items.map((f) => <FindingCard key={f.id} finding={f} />)}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium leading-snug">{finding.title}</CardTitle>
          <Badge className={FINDING_TYPE_TONE[finding.type] || ""}>{FINDING_TYPE_LABEL[finding.type] || finding.type}</Badge>
        </div>
        <CardDescription className="text-[11px]">
          <span className="font-mono">{finding.id}</span> · {finding.agent} · {finding.category}
        </CardDescription>
      </CardHeader>
      <CardContent className="text-xs space-y-2">
        <p>{finding.description}</p>
        {finding.evidence && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">Evidence</div>
            <blockquote className="border-l-2 pl-2 italic text-muted-foreground">{finding.evidence}</blockquote>
          </div>
        )}
        {finding.recommendation && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">Recommendation</div>
            <p>{finding.recommendation}</p>
          </div>
        )}
        <div className="flex items-center gap-2 pt-1 text-[10px] text-muted-foreground">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${SEVERITY_TONE[finding.severity] || "bg-slate-400"}`} />
          <span>severity: {finding.severity}</span>
          <span>·</span>
          <span>confidence: {(finding.confidence * 100).toFixed(0)}%</span>
        </div>
      </CardContent>
    </Card>
  );
}

function ConsensusDetail({ consensus }: { consensus: import("@/lib/types").ConsensusResult }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="text-sm">Agent status</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {Object.entries(consensus.agent_status).map(([k, v]) => (
            <div key={k} className="flex justify-between"><span className="text-muted-foreground">{k}</span><span className="font-mono">{v as number}</span></div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Decision votes</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {Object.entries(consensus.decision_votes).map(([k, v]) => (
            <div key={k} className="flex justify-between"><span className="text-muted-foreground">{k}</span><span className="font-mono">{v as number}</span></div>
          ))}
        </CardContent>
      </Card>
      <Card className="md:col-span-2">
        <CardHeader><CardTitle className="text-sm">Required actions ({consensus.required_actions.length})</CardTitle></CardHeader>
        <CardContent>
          {consensus.required_actions.length === 0 ? (
            <p className="text-sm text-muted-foreground">Нет</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {consensus.required_actions.map((a, i) => (
                <li key={i} className="flex gap-2"><span className="text-muted-foreground">•</span><span>{a}</span></li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function UpdatedSpecPanel({ content }: { content: string }) {
  const download = () => {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "updated-spec.md"; a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-sm">Updated specification</CardTitle>
        <Button size="sm" variant="outline" onClick={download}>
          <Download className="h-3.5 w-3.5" /> Скачать
        </Button>
      </CardHeader>
      <CardContent>
        <div className="prose prose-sm dark:prose-invert max-w-none rounded-lg border bg-card p-4 max-h-[70vh] overflow-y-auto">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      </CardContent>
    </Card>
  );
}

function MultiDocPanel({ docs }: { docs: Record<string, string> }) {
  const filenames = Object.keys(docs);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Updated documents ({filenames.length})</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {filenames.map((fname) => {
          const download = () => {
            const blob = new Blob([docs[fname]], { type: "text/markdown" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = fname; a.click();
            URL.revokeObjectURL(url);
          };
          return (
            <div key={fname} className="space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium">{fname}</h4>
                <Button size="sm" variant="outline" onClick={download}>
                  <Download className="h-3 w-3" /> {fname}
                </Button>
              </div>
              <div className="prose prose-sm dark:prose-invert max-w-none rounded-lg border bg-card p-3 max-h-[40vh] overflow-y-auto">
                <ReactMarkdown>{docs[fname]}</ReactMarkdown>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ChangesPanel({ changes }: { changes: import("@/lib/types").ChangesSummary }) {
  const groups = [
    { key: "added", title: "Added", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30" },
    { key: "changed", title: "Changed", tone: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30" },
    { key: "removed", title: "Removed", tone: "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/30" },
    { key: "kept_unresolved", title: "Kept unresolved", tone: "bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/30" },
  ] as const;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {groups.map((g) => {
        const items = changes[g.key as keyof import("@/lib/types").ChangesSummary] || [];
        return (
          <Card key={g.key}>
            <CardHeader>
              <CardTitle className="text-sm flex items-center justify-between">
                <span>{g.title}</span>
                <Badge className={g.tone}>{items.length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {items.length === 0 ? (
                <p className="text-sm text-muted-foreground">—</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {items.map((it, i) => <li key={i} className="flex gap-2"><span className="text-muted-foreground">•</span><span>{it}</span></li>)}
                </ul>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function RoundLogPanel({ entries }: { entries: import("@/lib/types").RoundEntry[] }) {
  if (entries.length === 0) return <EmptyState text="Round log пуст" />;
  return (
    <div className="space-y-3">
      {entries.map((e, i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">
                Round {String(e.round)} · <span className="text-muted-foreground font-normal">{phaseLabel(e.phase)}</span>
              </CardTitle>
              <span className={`text-xs font-medium ${statusColor(e.status)}`}>{e.status}</span>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{e.summary}</p>
            {e.counts && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {Object.entries(e.counts).map(([k, v]) => (
                  <Badge key={k} variant="outline" className="text-[10px]">{k}: {v as number}</Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}