import os
import json
import yaml
from typing import Dict, Any

from app.council_core.contracts import WriterRequestContract, WriterResponseContract, WriterWorkspace, WriterInputs
from app.agent_adapters import OpencodeAgentAdapter


PROJECT_ROOT = os.environ.get(
    "AI_SENATE_ROOT",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
AGENTS_YAML = os.path.join(PROJECT_ROOT, "app", "config", "agents.yaml")


def _load_writer_config() -> Dict[str, Any]:
    with open(AGENTS_YAML, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    writer = cfg.get("writer") or {}
    defaults = cfg.get("defaults", {}) or {}
    return {
        "agent": writer.get("agent", "writer"),
        "provider": writer.get("provider") or defaults.get("provider", "cliproxy"),
        "model": writer.get("model") or defaults.get("model", "claude-opus-4-6-thinking"),
        "opencode_agent": writer.get("opencode_agent") or defaults.get("opencode_agent", "plan"),
        "timeout_sec": writer.get("timeout_sec") or defaults.get("timeout_sec", 600),
        "system_override": (
            "You are the technical writer for the AI Senate.\n"
            "Your job: produce an updated specification that incorporates owner input and Council findings, "
            "without hiding blockers, major risks, or unresolved questions.\n"
            "Return a valid JSON object matching writer_response_v1 with `updated_document_content` "
            "containing the full new spec text (Markdown)."
        ),
    }


async def run_writer(
    run_id: str,
    new_document: bool,
    spec_file: str,
    owner_input_file: str,
    findings_file: str,
    consensus_file: str,
    agent_outputs_dir: str,
    output_file: str,
) -> WriterResponseContract:
    """
    Executes the writer/synthesizer agent to generate the updated specification.
    """
    cfg = _load_writer_config()
    request = WriterRequestContract(
        schema_version="writer_request_v1",
        run_id=run_id,
        new_document=new_document,
        workspace=WriterWorkspace(spec_file=spec_file, owner_input_file=owner_input_file),
        inputs=WriterInputs(
            findings_file=findings_file,
            consensus_file=consensus_file,
            agent_outputs_dir=agent_outputs_dir,
        ),
        task=(
            "Create updated specification without hiding blockers, major risks or unresolved questions. "
            "Return the new document content in JSON under the 'updated_document_content' field."
        ),
        output_file=output_file,
    )
    request_json = request.model_dump_json(indent=2)

    writer_run_dir = os.path.join(agent_outputs_dir, "writer")
    os.makedirs(writer_run_dir, exist_ok=True)
    with open(os.path.join(writer_run_dir, "request.json"), "w", encoding="utf-8") as f:
        f.write(request_json)

    adapter = OpencodeAgentAdapter("writer", cfg)
    execution_result = await adapter.run(request_json)

    with open(os.path.join(writer_run_dir, "stdout.txt"), "w", encoding="utf-8") as f:
        f.write(execution_result.get("stdout", "") or "")
    with open(os.path.join(writer_run_dir, "stderr.txt"), "w", encoding="utf-8") as f:
        f.write(execution_result.get("stderr", "") or "")
    with open(os.path.join(writer_run_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump({
            "agent": "writer",
            "status": execution_result.get("status"),
            "duration_ms": execution_result.get("duration_ms"),
            "exit_code": execution_result.get("exit_code"),
            "timeout": execution_result.get("timeout"),
            "parsed": execution_result.get("status") == "done",
            "error": execution_result.get("error"),
        }, f, indent=2, ensure_ascii=False)

    if execution_result.get("status") != "done" or not execution_result.get("parsed_output"):
        error_msg = execution_result.get("error", "Unknown error occurred during synthesis.")
        fallback_content = ""
        if os.path.exists(spec_file):
            with open(spec_file, "r", encoding="utf-8") as f:
                fallback_content = f.read()
        return WriterResponseContract(
            schema_version="writer_response_v1",
            status="failed",
            summary=f"Ошибка генерации ТЗ: {error_msg}",
            updated_document_content=fallback_content or f"# Ошибка генерации\n\nНе удалось запустить Writer: {error_msg}",
            output_file=output_file,
            owner_input_processed=False,
            owner_input_applied=False,
            notes=[f"Stderr: {execution_result.get('stderr', '')}"],
        )

    parsed_output = execution_result["parsed_output"]
    updated_content = parsed_output.get("updated_document_content", "") or ""

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(updated_content)

    return WriterResponseContract(
        schema_version="writer_response_v1",
        status=parsed_output.get("status", "draft_created"),
        summary=parsed_output.get("summary", "ТЗ успешно обновлено."),
        updated_document_content=updated_content,
        output_file=output_file,
        owner_input_processed=parsed_output.get("owner_input_processed", True),
        owner_input_applied=parsed_output.get("owner_input_applied", True),
        unresolved_questions_kept=parsed_output.get("unresolved_questions_kept", True),
        blockers_preserved=parsed_output.get("blockers_preserved", True),
        major_risks_preserved=parsed_output.get("major_risks_preserved", True),
        notes=parsed_output.get("notes", []) or [],
    )
