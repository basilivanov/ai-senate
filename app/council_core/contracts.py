from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


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


class PRContext(BaseModel):
    url: str
    owner: str
    repo: str
    number: int
    title: str = ""
    body: str = ""
    head_branch: str = ""
    base_branch: str = ""
    author: str = ""
    state: str = ""


class Workspace(BaseModel):
    root: str
    spec_file: str
    owner_input_file: str
    documents: List[DocumentRef] = []
    project: Optional[ProjectContext] = None
    git_diff: Optional[GitDiffContext] = None
    pr: Optional[PRContext] = None

class Instructions(BaseModel):
    language: str = "ru"
    output_format: str = "json"
    must_return_valid_json: bool = True
    do_not_modify_files: bool = True
    owner_input_priority: str = "high"
    focus: List[str]

class AgentRequestContract(BaseModel):
    schema_version: str = "agent_request_v1"
    run_id: str
    agent: str
    role: str
    task: str
    effort: str = "max"
    new_document: bool = False
    workspace: Workspace
    instructions: Instructions
    output_schema: str = "agent_review_response_v1"

class FindingItem(BaseModel):
    id: str
    type: str  # info, suggestion, risk, major_risk, blocker, question
    category: str
    severity: str
    title: str
    description: str
    evidence: Optional[str] = None
    recommendation: Optional[str] = None
    confidence: float = 1.0

class AgentResponseContract(BaseModel):
    schema_version: str = "agent_review_response_v1"
    agent: str
    role: str
    decision: str  # accept, accept_with_changes, needs_more_info, reject, block
    confidence: float
    summary: str
    items: List[FindingItem] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    required_actions: List[str] = Field(default_factory=list)

class ConsensusResultContract(BaseModel):
    schema_version: str = "consensus_result_v1"
    run_id: str
    status: str  # accepted, accepted_with_changes, needs_followup, needs_human_decision, blocked
    summary: str
    agent_status: Dict[str, int]  # total, done, failed, failed_parse, timeout
    counts: Dict[str, int]  # info, suggestion, risk, etc.
    decision_votes: Dict[str, int]
    required_actions: List[str]
    unresolved_questions: List[str]

class WriterWorkspace(BaseModel):
    spec_file: str
    owner_input_file: str

class WriterInputs(BaseModel):
    findings_file: str
    consensus_file: str
    agent_outputs_dir: str

class WriterRequestContract(BaseModel):
    schema_version: str = "writer_request_v1"
    run_id: str
    new_document: bool = False
    workspace: WriterWorkspace
    inputs: WriterInputs
    task: str
    output_file: str

class WriterResponseContract(BaseModel):
    schema_version: str = "writer_response_v1"
    status: str
    summary: str
    updated_document_content: str
    output_file: str
    owner_input_processed: bool = True
    owner_input_applied: bool = True
    unresolved_questions_kept: bool = True
    blockers_preserved: bool = True
    major_risks_preserved: bool = True
    notes: List[str] = Field(default_factory=list)
