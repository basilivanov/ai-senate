import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Plus, RefreshCw, Play, Trash2, Sparkles, Bot, Shield, Search,
} from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { formatDate, phaseLabel, statusColor, FINDING_TYPE_LABEL, FINDING_TYPE_TONE, formatDuration } from "@/lib/utils";

export function HomePage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [spec, setSpec] = useState("");
  const [ownerInput, setOwnerInput] = useState("");
  const [newDoc, setNewDoc] = useState(false);
  const [maxRounds, setMaxRounds] = useState(2);
  const [autoStop, setAutoStop] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.listRuns(), refetchInterval: 5000 });
  const currentSpec = useQuery({ queryKey: ["spec"], queryFn: () => api.getSpec() });
  const config = useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 10000 });

  useEffect(() => {
    if (currentSpec.data && !spec) setSpec(currentSpec.data.content || "");
  }, [currentSpec.data, spec]);

  const create = useMutation({
    mutationFn: () => api.createRun({
      spec_text: spec,
      owner_input: ownerInput,
      new_document: newDoc,
      max_rounds: maxRounds,
      auto_stop_if_clean: autoStop,
    }),
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

  const activeRuns = (runs.data || []).filter((r) =>
    ["queued", "running"].includes(r.status) || !["done", "failed", "blocked", "rejected"].includes(r.status),
  );
  const pastRuns = (runs.data || []).filter((r) => !activeRuns.includes(r));

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
                        Жюри: <span className="font-medium text-foreground">{config.data.juries.default.length}</span> перспектив
                        {" · "}
                        Writer: <span className="font-medium text-foreground">{config.data.writer?.model || "—"}</span>
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
                  <label className="block">
                    <div className="text-sm font-medium mb-1.5">Текущая спецификация (spec.md)</div>
                    <Textarea
                      value={spec}
                      onChange={(e) => setSpec(e.target.value)}
                      placeholder="Вставьте текущее ТЗ или оставьте пустым для нового документа"
                      className="min-h-[180px] font-mono text-xs"
                    />
                  </label>
                  <label className="block">
                    <div className="text-sm font-medium mb-1.5">Owner Input — что изменить / добавить</div>
                    <Textarea
                      value={ownerInput}
                      onChange={(e) => setOwnerInput(e.target.value)}
                      placeholder="Опишите правки, уточнения, новые требования"
                      className="min-h-[100px]"
                    />
                  </label>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={newDoc}
                        onChange={(e) => setNewDoc(e.target.checked)}
                        className="h-4 w-4 rounded border-input"
                      />
                      <span>Новый документ (с нуля)</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <span>Раундов:</span>
                      <Input
                        type="number"
                        min={1}
                        max={3}
                        value={maxRounds}
                        onChange={(e) => setMaxRounds(Number(e.target.value) || 1)}
                        className="w-20 h-8"
                      />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={autoStop}
                        onChange={(e) => setAutoStop(e.target.checked)}
                        className="h-4 w-4 rounded border-input"
                      />
                      <span>Остановить, если чисто</span>
                    </label>
                  </div>

                  {error && (
                    <Alert variant="destructive">
                      <AlertTitle>Ошибка запуска</AlertTitle>
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  <div className="flex items-center gap-2">
                    <Button
                      onClick={() => create.mutate()}
                      disabled={create.isPending || (newDoc && !ownerInput.trim())}
                    >
                      {create.isPending ? <Spinner /> : <Play className="h-4 w-4" />}
                      Запустить консилиум
                    </Button>
                    <Button variant="ghost" onClick={() => setShowForm(false)}>Отмена</Button>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  Нажмите «Новый запуск», чтобы начать. Жюри из {config.data?.juries.default.length || "—"} перспектив одновременно ревьюят ТЗ, затем Writer собирает новую версию.
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
