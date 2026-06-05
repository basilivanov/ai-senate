# ТЗ: AI Senate v2 — Профили, мультидокумент, code-aware review, live-панель

## Обоснование

AI Senate v1 работал с одним документом (spec_text), без доступа к коду проекта,
с фиксированным набором из 4 перспектив. На практике нужны три профиля использования:

1. **code_review** — ревью последних изменений в проекте с контекстом кода и спек
2. **full_council** — мультидокументальное проектирование (2-4 спеки + контекст проекта)
3. **quick_review** — быстрое ревью задачи агента, 2 модели, 1 раунд

Плюс визуальная обратная связь: в v1 агенты были спрятаны в табе. Нужна живая
боковая панель с анимацией состояний.

---

## 1. Профили запуска

### Конфигурация (`agents.yaml`)

```yaml
profiles:
  full_council:
    description: "Полный Совет — 4 перспективы, cross-review, writer"
    jury: default
    max_rounds: 2
    writer: true
    auto_stop_if_clean: true
    project_context: false

  quick_review:
    description: "Быстрое ревью — 2 модели, 1 раунд, без writer"
    jury: lite
    max_rounds: 1
    writer: false
    auto_stop_if_clean: true
    project_context: false

  code_review:
    description: "Ревью кода — 4 перспективы + контекст проекта + git diff"
    jury: default
    max_rounds: 2
    writer: true
    auto_stop_if_clean: true
    project_context: true

juries:
  default: [glm51, qwen37max, minimax, deepseekv4pro]
  lite: [glm51, qwen37max]
```

### Поведение по профилю

| Профиль | Жюри | Раунды | Writer | Проект | Use case |
|---------|------|--------|--------|--------|----------|
| full_council | 4 | 2 | да | опционально | Мультидокумент, новая фича |
| quick_review | 2 | 1 | нет | нет | Ревью задачи агента |
| code_review | 4 | 2 | да | да | Ревью кода, git diff |

Профиль выбирается при создании run через API `profile` поле.
Пользователь может переопределить `max_rounds` и `auto_stop_if_clean`.
Если `writer: false` в профиле — Writer-фаза пропускается полностью.

---

## 2. Мультидокументальный режим

### Данные

Вместо одного `spec_text` API принимает `documents: [{filename, role, content}]`.
Обратная совместимость: если `documents` пуст, используется `spec_text` как раньше.

### Хранение

Каждый документ сохраняется в `{run_dir}/input/{filename}`.
При сборке промпта каждый документ вставляется как:

```
=== Документ: architecture.md (Архитектура системы) ===
...содержимое...

=== Документ: api-contracts.md (API контракты) ===
...содержимое...
```

### Writer мультидокументальный

Если `len(documents) > 1`, Writer получает инструкцию вернуть JSON:

```json
{
  "schema_version": "writer_response_v1",
  "status": "draft_created",
  "summary": "...",
  "updated_documents": {
    "architecture.md": "...обновлённое содержимое...",
    "api-contracts.md": "...обновлённое содержимое..."
  },
  "notes": ["..."]
}
```

Если `len(documents) == 1` или используется `spec_text` — старый формат `updated_document_content`.

Парсинг в `writer.py` пытается `updated_documents` первым, fallback на `updated_document_content`.

Результат сохраняется:
- Single-doc: `{run_dir}/updated-spec.md` (как раньше)
- Multi-doc: `{run_dir}/updated/{filename}` для каждого файла

API:
- `GET /api/runs/{id}/updated-spec` — работает как раньше для single-doc
- `GET /api/runs/{id}/updated-docs` — возвращает `{filename: content}` для multi-doc

---

## 3. Code-aware review (project digest)

### Модуль `app/council_core/project_digest.py`

Функция `build_project_digest()`:

```python
def build_project_digest(
    project_path: str,
    file_patterns: List[str] = None,       # default: **/*.{py,ts,tsx,js,jsx,yaml,yml,json,toml,md,go,rs}
    exclude_patterns: List[str] = None,    # default: .git, node_modules, __pycache__, .venv, venv, dist, build
    max_file_size_kb: int = 50,
    max_total_tokens: int = 15000,
    respect_gitignore: bool = True,
) -> ProjectContext
```

Возвращает:

```python
class ProjectContext(BaseModel):
    path: str
    tree: str                    # tree-подобный вывод структуры
    files: List[DocumentRef]     # включённые файлы с содержимым
    total_tokens_estimate: int
    truncated: bool              # был ли обрезан дайджест
```

Логика:

1. Построить дерево проекта (аналог `tree --dirsfirst -I '.git|node_modules|...'`)
2. Применить `exclude_patterns` + `.gitignore`
3. Отфильтровать по `file_patterns`
4. Отсортировать: корень → config → source → test
5. Обрезать по `max_file_size_kb` на файл
6. Обрезать по `max_total_tokens` (оценка: 1 токен ≈ 4 символа)
7. Приоритет файла: если он упомянут в выбранных документах — выше
8. Вернуть `ProjectContext`

### Безопасность путей

`project_path` валидируется: должен быть под `AI_SENATE_PROJECT_ROOTS`
(env var, default: `/opt/solarsage-astro,/tmp/grace-orchestrator-export`).
Проверка: `os.path.realpath(project_path).startswith(allowed_root)`.

---

## 4. Git diff

### Модуль `app/council_core/git_context.py`

```python
def get_git_diff(
    project_path: str,
    diff_type: str = "head~1",  # unstaged | staged | head~1 | head~N | branch:base..head | last:N
    max_lines: int = 2000,
) -> GitDiffResult
```

Поддерживаемые diff_type:
- `unstaged` → `git diff`
- `staged` → `git diff --cached`
- `head~1` → `git diff HEAD~1..HEAD`
- `head~N` → `git diff HEAD~N..HEAD`
- `last:N` → последние N коммитов: `git diff HEAD~N..HEAD`
- `branch:base..head` → `git diff base..head`

Возвращает:

```python
class GitDiffResult(BaseModel):
    project_path: str
    diff_type: str
    diff_content: str
    files_changed: int
    insertions: int
    deletions: int
    truncated: bool
    file_list: List[str]
```

Валидация: `project_path` под `AI_SENATE_PROJECT_ROOTS`, директория содержит `.git/`.

### Включение в промпт

Если `workspace.git_diff` задан, в `_build_user_prompt()` добавляется:

```
=== GIT DIFF (12 files changed, +340/-89 lines) ===
diff --git a/src/main.py b/src/main.py
...
=== END GIT DIFF ===

Review these changes against the project specification and codebase.
Check: spec-vs-implementation gaps, missed edge cases, stale docs.
```

---

## 5. Contracts (Pydantic модели)

### Новые модели в `contracts.py`

```python
class DocumentRef(BaseModel):
    filename: str
    role: str = ""
    content: str

class ProjectContext(BaseModel):
    path: str
    tree: str = ""
    files: List[DocumentRef] = []
    total_tokens_estimate: int = 0
    truncated: bool = False

class GitDiffContext(BaseModel):
    diff_content: str = ""
    diff_type: str = ""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    truncated: bool = False
    file_list: List[str] = []

class Workspace(BaseModel):
    root: str
    spec_file: str
    owner_input_file: str
    documents: List[DocumentRef] = []          # NEW
    project: Optional[ProjectContext] = None    # NEW
    git_diff: Optional[GitDiffContext] = None   # NEW
```

---

## 6. API-изменения

### CreateRunBody v2

```python
class DocumentInput(BaseModel):
    filename: str
    role: str = ""
    content: str

class GitDiffInput(BaseModel):
    project_path: str
    diff_type: str = "head~1"
    max_lines: int = 2000

class ProjectInput(BaseModel):
    path: str
    file_patterns: List[str] = []
    exclude_patterns: List[str] = []
    max_file_size_kb: int = 50
    max_total_tokens: int = 15000

class CreateRunBody(BaseModel):
    spec_text: str = ""                          # backward compat
    documents: List[DocumentInput] = []           # NEW: multi-doc
    owner_input: str = ""
    new_document: bool = False
    profile: str = "full_council"                 # NEW
    project: Optional[ProjectInput] = None        # NEW
    git_diff: Optional[GitDiffInput] = None       # NEW
    max_rounds: int = 2
    auto_stop_if_clean: bool = True
```

### Новые эндпоинты

```
POST /api/project/digest
Body: { "path": "/opt/solarsage-astro", "file_patterns": [...], "max_total_tokens": 15000 }
Response: ProjectContext (tree + files + token estimate)

POST /api/project/git-diff
Body: { "project_path": "/opt/solarsage-astro", "diff_type": "head~1", "max_lines": 2000 }
Response: GitDiffResult

GET /api/runs/{id}/updated-docs
Response: { "architecture.md": "...", "api-contracts.md": "..." }
```

### Storage

В `runs` таблицу добавляются колонки:
- `profile TEXT DEFAULT 'full_council'`
- `project_path TEXT`

---

## 7. service.py — профильная логика

При создании run:

```python
profile_cfg = yaml_cfg.get("profiles", {}).get(body.profile, {})
jury_name = profile_cfg.get("jury", "default")
jury = _get_jury(yaml_cfg, jury_name)
max_rounds = body.max_rounds or profile_cfg.get("max_rounds", 2)
writer_enabled = profile_cfg.get("writer", True)

# Multi-doc: сохранить каждый документ
if body.documents:
    for doc in body.documents:
        path = os.path.join(run_dir, "input", doc.filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(doc.content)
elif body.spec_text:
    # backward compat
    with open(spec_file, "w") as f:
        f.write(body.spec_text)

# Project digest
project_context = None
if body.project:
    project_context = build_project_digest(...)
    run_data["project"] = {"path": body.project.path, "files_included": len(project_context.files), "truncated": project_context.truncated}

# Git diff
git_diff_ctx = None
if body.git_diff:
    git_diff_ctx = get_git_diff(...)
    run_data["git_diff"] = {"diff_type": git_diff_ctx.diff_type, "files_changed": git_diff_ctx.files_changed}

# Skip writer if profile says so
if not writer_enabled:
    # Skip Writer phase entirely
```

---

## 8. opencode.py — _build_user_prompt

Расширение промпта для мультидокумента, project context и git diff:

```python
def _build_user_prompt(self, contract, raw_contract_json):
    parts = []
    
    # Base prompt (role, task, focus)
    parts.append(f"You are acting as: {contract.get('role')}\n...")
    
    workspace = contract.get("workspace", {})
    
    # Multi-doc mode
    documents = workspace.get("documents", [])
    if documents:
        for doc in documents:
            parts.append(f"\n=== Документ: {doc['filename']} ({doc.get('role', '')}) ===\n{doc['content']}")
    else:
        # Single-doc backward compat
        spec_content = self._read_file(workspace.get("spec_file"))
        parts.append(f"\n--- CURRENT SPECIFICATION ---\n{spec_content or '[No spec]'}")
    
    # Owner input
    owner_content = self._read_file(workspace.get("owner_input_file"))
    parts.append(f"\n--- OWNER INPUT ---\n{owner_content or '[No comments]'}")
    
    # Project context
    project = workspace.get("project")
    if project:
        parts.append(f"\n=== PROJECT: {project['path']} ===")
        parts.append(f"=== PROJECT TREE ===\n{project['tree']}")
        for f in project.get("files", []):
            parts.append(f"\n=== FILE: {f['filename']} ===\n{f['content']}")
        if project.get("truncated"):
            parts.append("\n[Project digest was truncated due to token limit]")
    
    # Git diff
    git_diff = workspace.get("git_diff")
    if git_diff and git_diff.get("diff_content"):
        parts.append(f"\n=== GIT DIFF ({git_diff['files_changed']} files, +{git_diff['insertions']}/-{git_diff['deletions']}) ===")
        parts.append(git_diff["diff_content"])
        if git_diff.get("truncated"):
            parts.append("\n[Diff was truncated due to line limit]")
        parts.append("=== END GIT DIFF ===")
        parts.append("Review these changes against the specification and codebase.")
    
    # JSON schema instructions
    parts.append("\n--- INSTRUCTIONS ---\nReturn ONLY valid JSON...")
    
    return "\n".join(parts)
```

---

## 9. Frontend: Live-панель агентов

### Layout: RunPage two-column

```
┌──────────────┬─────────────────────────────────────────────┐
│ АГЕНТЫ       │  КОНТЕНТ                                    │
│ (240→320px)  │                                              │
│              │  [Findings] [Consensus] [Spec] [Changes] [Δ]  │
│ ┌──────────┐│                                              │
│ │ ● glm51  ││                                              │
│ │ Думает...││                                              │
│ └──────────┘│                                              │
│ ┌──────────┐│                                              │
│ │ ○ qwen37 ││                                              │
│ │ Ожидает  ││                                              │
│ └──────────┘│                                              │
│              │                                              │
│ ── WRITER ── │                                              │
│ ┌──────────┐│                                              │
│ │ ◷ Writer ││                                              │
│ │ Waiting  ││                                              │
│ └──────────┘│                                              │
│              │                                              │
│ R1 Review → │                                              │
│ ▓▓▓▓░░░░░░ │                                              │
└──────────────┴─────────────────────────────────────────────┘
```

### Состояния агента

| Статус      | Иконка | Текст               | Анимация             |
|-------------|--------|---------------------|----------------------|
| queued      | ○ серый | «Ожидает»           | pulse slow           |
| running     | ● синий | «Думает...» → «Думает.» → «Думает..» | pulse + dots keyframe |
| done        | ✓ зелёный | decision + conf% + N items | fade-in slide-in    |
| failed      | ✗ красный | error text          | статичный           |
| timeout     | ⏱ красный | «Таймаут»           | статичный           |
| waiting     | ◷ жёлтый | «Ожидает Writer»    | pulse slow           |

### Polling

- Active run: каждые 2с
- Done/failed: прекратить polling
- Фаза «Думает...» — анимация текста с точками (CSS keyframe)

### PhaseProgress

```
R1 Review → Consensus → R2 Cross → Consensus → Writer → Done
    ✓           ✓           ▓▓▓░░░░       ░          ░        ░
```

Текущая фаза — синяя с полосой прогресса, пройденные — зелёные, будущие — серые.

---

## 10. Frontend: RunCreateForm

### Профили

Dropdown: `full_council` / `quick_review` / `code_review`

При выборе профиля:
- `full_council`: показывает мультидокумент + owner_input, скрывает проект/diff
- `quick_review`: показывает только spec_text + owner_input, минимум полей
- `code_review`: показывает всё: документы + проект + diff + owner_input

### Мультидокумент

Список документов с кнопкой «Добавить». Каждый документ:
- filename (автозаполнение при выборе из проекта)
- role (опционально)
- content (textarea)

Кнопка «Загрузить из проекта» — открывает файловый браузер (API `/project/digest`).

### Project context

- Поле «Путь к проекту»
- Чекбокс «Включить исходный код»
- Кнопка «Предпросмотр дайджеста» → `POST /api/project/digest`
- Показать: дерево, N файлов включено, ~N токенов

### Git diff

- Чекбокс «Включить git diff»
- Dropdown типа diff: `head~1` / `unstaged` / `staged` / `last:3`
- Кнопка «Предпросмотр diff» → `POST /api/project/git-diff`
- Показать: N файлов изменено, +M/-K строк

---

## 11. Файлы для изменения

| # | Файл | Тип | Описание |
|---|------|-----|----------|
| 1 | `app/config/agents.yaml` | modify | +profiles, +juries.lite |
| 2 | `app/council_core/contracts.py` | modify | +DocumentRef, ProjectContext, GitDiffContext, Workspace fields |
| 3 | `app/council_core/project_digest.py` | **NEW** | scan project, build tree, select files, token estimation |
| 4 | `app/council_core/git_context.py` | **NEW** | git diff extraction with path validation |
| 5 | `app/council_core/writer.py` | modify | multi-doc writer output, updated_documents format |
| 6 | `app/runs/service.py` | modify | profile-based flow, multi-doc save, project/diff injection, skip writer |
| 7 | `app/runs/storage.py` | modify | +profile, project_path columns |
| 8 | `app/agent_adapters/opencode.py` | modify | _build_user_prompt: multi-doc + project + diff |
| 9 | `app/web/api.py` | modify | +DocumentInput, ProjectInput, GitDiffInput, profile, /project/digest, /project/git-diff, /updated-docs |
| 10 | `frontend/src/lib/types.ts` | modify | +new types |
| 11 | `frontend/src/lib/api.ts` | modify | +new API calls |
| 12 | `frontend/src/components/AgentSidebar.tsx` | **NEW** | live agent panel |
| 13 | `frontend/src/components/PhaseProgress.tsx` | **NEW** | phase progress bar |
| 14 | `frontend/src/pages/RunPage.tsx` | modify | two-column layout, sidebar |
| 15 | `frontend/src/pages/HomePage.tsx` | modify | profile selector in create form |
| 16 | `frontend/src/components/RunCreateForm.tsx` | **NEW** | full create form with profiles, multi-doc, project, diff |

---

## 12. Безопасность

- `project_path` валидируется: `os.path.realpath()` должен начинаться с одного из `AI_SENATE_PROJECT_ROOTS`
- Git diff запускается с `timeout=30` и `cwd=project_path`, только `git diff` команды
- Никакой arbitrary command execution
- `max_lines` для diff и `max_total_tokens` для digest — лимиты на размер

---

## 13. Критерии приёмки

1. **Профили**: `quick_review` запускается с 2 моделями, 1 раунд, без Writer — <90с
2. **Multi-doc**: можно передать 2+ документа, все попадают в промпт каждого агента
3. **Multi-doc Writer**: Writer возвращает `updated_documents` dict, каждый файл сохранён отдельно
4. **Project digest**: при указании `project` — дерево + файлы включены в промпт, ≤15000 токенов
5. **Git diff**: при указании `git_diff` — diff включён в промпт, ≤2000 строк
6. **Code review профиль**: 4 перспективы + project context + git diff
7. **Skip writer**: при `writer: false` в профиле — Writer-фаза пропускается
8. **Backward compat**: API без `documents`/`project`/`git_diff`/`profile` работает как раньше
9. **Live sidebar**: агенты видны слева с анимацией, polling 2с для active run
10. **Phase progress**: визуальный прогресс по фазам run