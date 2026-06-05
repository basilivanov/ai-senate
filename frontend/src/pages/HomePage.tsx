import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Plus, RefreshCw, Play, Trash2, Sparkles, Bot, Shield, Search, FolderOpen, FileText, GitBranch,
} from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { formatDate, phaseLabel, statusColor, FINDING_TYPE_LABEL, FINDING_TYPE_TONE, formatDuration } from "@/lib/utils";
import type { CreateRunRequest, DocumentInput, ProfileConfig } from "@/lib/types";

const PROFILE_INFO: Record<string, { label: string; desc: string }> = {
  full_council: { label: "Полный Совет", desc: "4 модели, 2 раунда, writer" },
  quick_review: { label: "Быстрое ревью", desc: "2 модели, 1 раунд, без writer" },
  code_review: { label: "Code Review", desc: "4 модели + проект + git diff" },
};

export function HomePage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [profile, setProfile] = useState("full_council");
  const [spec, setSpec] = useState("");
  const [ownerInput, setOwnerInput] = useState("");
  const [newDoc, setNewDoc] = useState(false);
  const [maxRounds, setMaxRounds] = useState(2);
  const [autoStop, setAutoStop] = useState(true);

  // Multi-doc
  const [documents, setDocuments] = useState<{ filename: string; role: string; content: string }[]>([]);
  const [docFilename, setDocFilename] = useState("");
  const [docRole, setDocRole] = useState("");
  const [docContent, setDocContent] = useState("");

  // Project & git diff
  const [projectPath, setProjectPath] = useState("");
  const [includeProject, setIncludeProject] = useState(false);
  const [includeGitDiff, setIncludeGitDiff] = useState(false);
  const [gitDiffType, setGitDiffType] = useState("head~1");
  const [diffPreview, setDiffPreview] = useState<{ files: number; insertions: number; deletions: number } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.listRuns(), refetchInterval: 5000 });
  const currentSpec = useQuery({ queryKey: ["spec"], queryFn: () => api.getSpec() });
  const config = useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 10000 });

  useEffect(() => {
    if (currentSpec.data && !spec) setSpec(currentSpec.data.content || "");
  }, [currentSpec.data, spec]);

  const isCodeReview = profile === "code_review";
  const isQuickReview = profile === "quick_review";

  const create = useMutation({
    mutationFn: () => {
      const body: CreateRunRequest = {
        spec_text: spec,
        documents,
        owner_input: ownerInput,
        new_document: newDoc,
        profile,
        project: includeProject && projectPath ? { path: projectPath, file_patterns: [], exclude_patterns: [], max_file_size_kb: 50, max_total_tokens: 15000 } : null,
        git_diff: includeGitDiff && projectPath ? { project_path: projectPath, diff_type: gitDiffType, max_lines: 2000 } : null,
        max_rounds: isQuickReview ? 1 : maxRounds,
        auto_stop_if_clean: autoStop,
      };
      return api.createRun(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      setError(null);
      setShowForm(false);
    },
    onError: (e) => setError(String(e)),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteRun(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const previewDiff = async () => {
    if (!projectPath) return;
    setDiffLoading(true);
    try {
      const res = await api.projectGitDiff({ project_path: projectPath, diff_type: gitDiffType, max_lines: 2000 });
      setDiffPreview({ files: res.files_changed, insertions: res.insertions, deletions: res.deletions });
    } catch (e) {
      setDiffPreview(null);
    } finally {
      setDiffLoading(false);
    }
  };

  const addDocument = () => {
    if (!docFilename.trim() || !docContent.trim()) return;
    setDocuments([...documents, { filename: docFilename.trim(), role: docRole.trim(), content: docContent }]);
    setDocFilename("");
    setDocRole("");
    setDocContent("");
  };

  const removeDocument = (idx: number) => {
    setDocuments(documents.filter((_, i) => i !== idx));
  };

  const activeRuns = (runs.data || []).filter((r) =>
    ["queued", "running"].includes(r.status) || !["done", "failed", "blocked", "rejected"].includes(r.status),
  );
  const pastRuns = (runs.data || []).filter((r) => !activeRuns.includes(r));

  const profiles = config.data?.profiles || {};
  const juryInfo = isQuickReview ? "lite" : "default";

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/30">
      <Header
        opencodeReachable={health.data?.opencode.reachable ?? null}
        opencodeUrl={health.data?.opencode.base_url}
      />

      <main className="container py-8 space-y-8">
        <section className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-2xl">
                    <Sparkles className="h-5 w-5 text-primary" />
                    Запустить Совет
                  </CardTitle>
                  <CardDescription className="mt-1.5">
                    {config.data ? (
                      <>
                        Жюри: <span className="font-medium text-foreground">{config.data.juries[juryInfo]?.length || "?"}</span> моделей
                        {" · "}
                        Writer: <span className="font-medium text-foreground">{isQuickReview ? "нет" : config.data.writer?.model || "—"}</span>
                      </>
                    ) : "Загрузка…"}
                  </CardDescription>
                </div>
                <Button
                  variant={showForm ? "secondary" : "default"}
                  onClick={() => setShowForm((v) => !v)}
                  size="sm"
                >
                  <Plus className="h-4 w-4" />
                  {showForm ? "Скрыть" : "Новый запуск"}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {showForm ? (
                <div className="space-y-4">
                  {/* Profile selector */}
                  <div>
                    <div className="text-sm font-medium mb-1.5">Профиль</div>
                    <div className="flex gap-2 flex-wrap">
                      {Object.entries(PROFILE_INFO).map(([key, info]) => (
                        <Button
                          key={key}
                          variant={profile === key ? "default" : "outline"}
                          size="sm"
                          onClick={() => setProfile(key)}
                        >
                          <div className="text-left">
                            <div className="font-medium">{info.label}</div>
                            <div className="text-[10px] text-muted-foreground">{info.desc}</div>
                          </div>
                        </Button>
                      ))}
                    </div>
                  </div>

                  {/* Multi-doc or single-doc */}
                  {isQuickReview ? (
                    <>
                      <label className="block">
                        <div className="text-sm font-medium mb-1.5">Текст ревью (spec)</div>
                        <Textarea
                          value={spec}
                          onChange={(e) => setSpec(e.target.value)}
                          placeholder="Вставьте текст для ревью"
                          className="min-h-[120px] font-mono text-xs"
                        />
                      </label>
                    </>
                  ) : (
                    <>
                      <label className="block">
                        <div className="text-sm font-medium mb-1.5">Текущая спецификация (spec.md)</div>
                        <Textarea
                          value={spec}
                          onChange={(e) => setSpec(e.target.value)}
                          placeholder="Вставьте ТЗ или оставьте пустым для нового документа"
                          className="min-h-[140px] font-mono text-xs"
                        />
                      </label>

                      {/* Multi-doc */}
                      <div>
                        <div className="text-sm font-medium mb-1.5 flex items-center gap-1.5">
                          <FileText className="h-3.5 w-3.5" /> Дополнительные документы ({documents.length})
                        </div>
                        {documents.map((doc, i) => (
                          <div key={i} className="flex items-center gap-2 mb-1.5">
                            <Badge variant="outline" className="text-xs">{doc.filename}</Badge>
                            <span className="text-xs text-muted-foreground truncate max-w-[200px]">{doc.role || "—"}</span>
                            <Button size="icon" variant="ghost" className="h-5 w-5" onClick={() => removeDocument(i)}>
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                        ))}
                        <div className="grid grid-cols-[1fr_1fr_auto] gap-2 mt-2">
                          <Input placeholder="filename.md" value={docFilename} onChange={(e) => setDocFilename(e.target.value)} className="h-8 text-xs" />
                          <Input placeholder="Роль (опц.)" value={docRole} onChange={(e) => setDocRole(e.target.value)} className="h-8 text-xs" />
                          <Button size="sm" variant="outline" onClick={addDocument} className="h-8">
                            <Plus className="h-3 w-3" />
                          </Button>
                        </div>
                        {docFilename && (
                          <Textarea
                            placeholder="Содержимое документа..."
                            value={docContent}
                            onChange={(e) => setDocContent(e.target.value)}
                            className="min-h-[100px] mt-2 text-xs"
                          />
                        )}
                      </div>
                    </>
                  )}

                  <label className="block">
                    <div className="text-sm font-medium mb-1.5">Owner Input — что изменить / добавить</div>
                    <Textarea
                      value={ownerInput}
                      onChange={(e) => setOwnerInput(e.target.value)}
                      placeholder="Опишите правки, уточнения, новые требования"
                      className="min-h-[80px]"
                    />
                  </label>

                  {/* Project & Git diff (code_review profile) */}
                  {(isCodeReview || includeProject) && (
                    <div className="space-y-3 border rounded-lg p-3 bg-muted/30">
                      <div className="text-sm font-medium flex items-center gap-1.5">
                        <FolderOpen className="h-3.5 w-3.5" /> Контекст проекта
                      </div>
                      <div>
                        <label className="block text-xs text-muted-foreground mb-1">Путь к проекту</label>
                        <Input
                          placeholder="/opt/solarsage-astro"
                          value={projectPath}
                          onChange={(e) => setProjectPath(e.target.value)}
                          className="h-8 text-xs"
                        />
                      </div>

                      {(isCodeReview || includeGitDiff) && (
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <GitBranch className="h-3.5 w-3.5" />
                            <span className="text-xs text-muted-foreground">Git diff</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <select
                              value={gitDiffType}
                              onChange={(e) => setGitDiffType(e.target.value)}
                              className="h-8 text-xs border rounded px-2"
                            >
                              <option value="head~1">Последний коммит (head~1)</option>
                              <option value="unstaged">Незакоммиченные (unstaged)</option>
                              <option value="staged">Staged</option>
                              <option value="last:3">Последние 3 коммита</option>
                              <option value="last:5">Последние 5 коммитов</option>
                            </select>
                            <Button size="sm" variant="outline" onClick={previewDiff} disabled={diffLoading || !projectPath} className="h-8">
                              {diffLoading ? <Spinner /> : "Предпросмотр"}
                            </Button>
                          </div>
                          {diffPreview && (
                            <div className="text-xs text-muted-foreground mt-1">
                              {diffPreview.files} файлов, +{diffPreview.insertions}/-{diffPreview.deletions} строк
                            </div>
                          )}
                        </div>
                      )}

                      {!isCodeReview && (
                        <label className="flex items-center gap-2 text-xs">
                          <input type="checkbox" checked={includeProject} onChange={(e) => setIncludeProject(e.target.checked)} className="h-4 w-4 rounded border-input" />
                          Включить исходный код (digest)
                        </label>
                      )}
                      {!isCodeReview && includeProject && (
                        <label className="flex items-center gap-2 text-xs">
                          <input type="checkbox" checked={includeGitDiff} onChange={(e) => setIncludeGitDiff(e.target.checked)} className="h-4 w-4 rounded border-input" />
                          Включить git diff
                        </label>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={newDoc} onChange={(e) => setNewDoc(e.target.checked)} className="h-4 w-4 rounded border-input" />
                      <span>Новый документ</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <span>Раундов:</span>
                      <Input
                        type="number" min={1} max={3}
                        value={isQuickReview ? 1 : maxRounds}
                        onChange={(e) => setMaxRounds(Number(e.target.value) || 1)}
                        className="w-20 h-8" disabled={isQuickReview}
                      />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={autoStop} onChange={(e) => setAutoStop(e.target.checked)} className="h-4 w-4 rounded border-input" />
                      <span>Остановить, если чисто</span>
                    </label>
                  </div>

                  {error && (
                    <Alert color="destructive">
                      <AlertTitle>Ошибка запуска</AlertTitle>
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  <div className="flex items-center gap-2">
                    <Button onClick={() => create.mutate()} disabled={create.isPending || (newDoc && !ownerInput.trim())}>
                      {create.isPending ? <Spinner /> : <Play className="h-4 w-4" />}
                      Запустить {PROFILE_INFO[profile]?.label || profile}
                    </Button>
                    <Button variant="ghost" onClick={() => setShowForm(false)}>Отмена</Button>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  Нажмите «Новый запуск», чтобы начать. Жюри из {config.data?.juries[juryInfo]?.length || "—"} перспектив ревьюят ТЗ.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Bot className="h-4 w-4" /> Жюри и модели
              </CardTitle>
            </CardHeader>
            <CardContent>
              {config.isLoading ? (
                <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
              ) : config.data ? (
                <div className="space-y-2.5">
                  {config.data.perspectives.map((p) => (
                    <div key={p.key} className="flex items-center justify-between gap-2 text-sm">
                      <div className="min-w-0">
                        <div className="font-medium truncate">{p.key}</div>
                        <div className="text-xs text-muted-foreground truncate">{p.role}</div>
                      </div>
                      <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
                        {p.provider}/{p.model}
                      </Badge>
                    </div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </section>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Search className="h-4 w-4" /> Активные запуски
            </h2>
            <Button size="sm" variant="ghost" onClick={() => runs.refetch()}>
              <RefreshCw className="h-3.5 w-3.5" />
              Обновить
            </Button>
          </div>
          <RunsTable
            runs={activeRuns}
            loading={runs.isLoading}
            onDelete={(id) => del.mutate(id)}
            emptyText="Нет активных запусков"
          />
        </section>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">История</h2>
          <RunsTable
            runs={pastRuns}
            loading={runs.isLoading}
            onDelete={(id) => del.mutate(id)}
            emptyText="История пуста"
          />
        </section>
      </main>
    </div>
  );
}

function RunsTable({
  runs,
  loading,
  onDelete,
  emptyText,
}: {
  runs: import("@/lib/types").RunSummary[];
  loading: boolean;
  onDelete: (id: string) => void;
  emptyText: string;
}) {
  if (loading) {
    return <div className="space-y-2">{Array.from({ length: 2 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>;
  }
  if (runs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed text-sm text-muted-foreground p-6 text-center">
        {emptyText}
      </div>
    );
  }
  return (
    <div className="rounded-lg border overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="text-left p-3">Run ID</th>
            <th className="text-left p-3">Profile</th>
            <th className="text-left p-3">Phase</th>
            <th className="text-left p-3">Status</th>
            <th className="text-left p-3">Round</th>
            <th className="text-left p-3">Created</th>
            <th className="w-8"></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-t hover:bg-muted/30 transition-colors">
              <td className="p-3">
                <Link to={`/runs/${r.id}`} className="font-mono text-xs hover:underline text-primary">
                  {r.id}
                </Link>
              </td>
              <td className="p-3">
                <Badge variant="outline" className="text-[10px]">{r.profile || "full_council"}</Badge>
              </td>
              <td className="p-3 text-muted-foreground text-xs">{phaseLabel(r.phase)}</td>
              <td className="p-3">
                <span className={`text-xs font-medium ${statusColor(r.status)}`}>{r.status}</span>
              </td>
              <td className="p-3 text-xs">{r.current_round}/{r.max_rounds}</td>
              <td className="p-3 text-xs text-muted-foreground">{formatDate(r.created_at)}</td>
              <td className="p-2">
                <Button size="icon" variant="ghost" onClick={() => onDelete(r.id)} title="Удалить">
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Header({ opencodeReachable, opencodeUrl }: { opencodeReachable: boolean | null; opencodeUrl?: string }) {
  return (
    <header className="border-b bg-background/60 backdrop-blur sticky top-0 z-10">
      <div className="container flex h-14 items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Shield className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-none">AI Senate</div>
            <div className="text-[10px] text-muted-foreground leading-none mt-0.5">Council coordinator · opencode</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="hidden sm:inline text-muted-foreground">{opencodeUrl || "…"}</span>
          {opencodeReachable === null ? (
            <Badge variant="outline">checking</Badge>
          ) : opencodeReachable ? (
            <Badge variant="outline" className="text-emerald-600 border-emerald-500/40">opencode OK</Badge>
          ) : (
            <Badge variant="outline" className="text-rose-600 border-rose-500/40">opencode down</Badge>
          )}
        </div>
      </div>
      <Separator />
    </header>
  );
}

// Needed for Alert import
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";