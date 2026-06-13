import os
import json
import yaml
from typing import Dict, Any, List, Optional

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
            "You are the technical writer for the AI Senate Council.\n"
            "Your job: produce an updated specification that incorporates owner input and Council findings, "
            "without hiding blockers, major risks, or unresolved questions.\n"
            "\n"
            "ABSOLUTE OUTPUT RULES:\n"
            "1. Respond with a single valid JSON object, NOTHING else — no prose, no markdown fences, no commentary.\n"
            "2. The JSON must match writer_response_v1 with the field `updated_document_content` containing the full new spec as a Markdown string.\n"
            "3. Do NOT write to any files. Do NOT reference any tool outputs. The full document must be in the `updated_document_content` string.\n"
            "4. Escape all newlines as `\\n` and quotes as `\\\"` inside the JSON string.\n"
            "5. If the spec would be very long, keep it concise but complete; the entire JSON must fit in one response.\n"
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
    documents: Optional[List] = None,
    mode: str = "review",
) -> WriterResponseContract:
    """
    Executes the writer/synthesizer agent to generate the updated specification.
    In discussion mode, produces a synthesis/summary of the discussion.
    """
    cfg = _load_writer_config()
    is_multi_doc = documents and len(documents) > 1

    # Override system prompt and task for discussion mode
    if mode == "discussion":
        cfg["system_override"] = (
            "You are the synthesizer for the AI Senate Council discussion.\n"
            "Your job: produce a comprehensive synthesis document that captures the key points, "
            "areas of agreement and disagreement, open questions, and final conclusions from the discussion.\n"
            "\n"
            "ABSOLUTE OUTPUT RULES:\n"
            "1. Respond with a single valid JSON object, NOTHING else — no prose, no markdown fences, no commentary.\n"
            "2. The JSON must match writer_response_v1 with the field `updated_document_content` containing the full synthesis as a Markdown string.\n"
            "3. Do NOT write to any files. Do NOT reference any tool outputs. The full document must be in the `updated_document_content` string.\n"
            "4. Escape all newlines as `\\n` and quotes as `\\\"` inside the JSON string.\n"
            "5. Structure the synthesis with clear sections: Summary, Key Points, Areas of Agreement, Areas of Disagreement, Open Questions, Conclusions & Recommendations.\n"
        )
        writer_task = (
            "Create a synthesis document summarizing the discussion. "
            "Include: key points raised, areas of agreement, areas of disagreement, "
            "open questions, and final conclusions with recommendations. "
            "Return the new document content in JSON under the 'updated_document_content' field."
        )
    else:
        writer_task = (
            "Create updated specification without hiding blockers, major risks or unresolved questions. "
            "Return the new document content in JSON under the 'updated_document_content' field."
        )

    if is_multi_doc:
        doc_list = ", ".join(d.get("filename", "doc") for d in documents)
        multi_doc_system_addition = (
            f"\n\nMULTI-DOCUMENT MODE: You are updating {len(documents)} documents: [{doc_list}].\n"
            "Instead of 'updated_document_content', return a JSON field 'updated_documents' "
            "which is a dict mapping each filename to its full updated Markdown content.\n"
            "Example: {\"updated_documents\": {\"architecture.md\": \"...\", \"api-contracts.md\": \"...\"}}\n"
        )
        cfg["system_override"] = cfg.get("system_override", "") + multi_doc_system_addition

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
        task=writer_task,
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
            summary=f"Ошибка генерации документа: {error_msg}",
            updated_document_content=fallback_content or f"# Ошибка генерации\n\nНе удалось запустить Writer: {error_msg}",
            output_file=output_file,
            owner_input_processed=False,
            owner_input_applied=False,
            notes=[f"Stderr: {execution_result.get('stderr', '')}"],
        )

    parsed_output = execution_result["parsed_output"]

    # Multi-document mode: updated_documents dict
    if is_multi_doc and isinstance(parsed_output.get("updated_documents"), dict):
        updated_docs = parsed_output["updated_documents"]
        updated_dir = os.path.join(os.path.dirname(output_file), "updated")
        os.makedirs(updated_dir, exist_ok=True)
        for fname, content in updated_docs.items():
            fpath = os.path.join(updated_dir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
        # Also write first (or combined) to updated-spec.md for backward compat
        primary_content = list(updated_docs.values())[0] if updated_docs else ""
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(primary_content)

        return WriterResponseContract(
            schema_version="writer_response_v1",
            status=parsed_output.get("status", "draft_created"),
            summary=parsed_output.get("summary", "Документ успешно сгенерирован (мультидокумент)."),
            updated_document_content=primary_content,
            output_file=output_file,
            owner_input_processed=parsed_output.get("owner_input_processed", True),
            owner_input_applied=parsed_output.get("owner_input_applied", True),
            unresolved_questions_kept=parsed_output.get("unresolved_questions_kept", True),
            blockers_preserved=parsed_output.get("blockers_preserved", True),
            major_risks_preserved=parsed_output.get("major_risks_preserved", True),
            notes=parsed_output.get("notes", []) or [],
        )

    # Single-document mode
    updated_content = parsed_output.get("updated_document_content", "") or ""

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(updated_content)

    return WriterResponseContract(
        schema_version="writer_response_v1",
        status=parsed_output.get("status", "draft_created"),
        summary=parsed_output.get("summary", "Документ успешно сгенерирован."),
        updated_document_content=updated_content,
        output_file=output_file,
        owner_input_processed=parsed_output.get("owner_input_processed", True),
        owner_input_applied=parsed_output.get("owner_input_applied", True),
        unresolved_questions_kept=parsed_output.get("unresolved_questions_kept", True),
        blockers_preserved=parsed_output.get("blockers_preserved", True),
        major_risks_preserved=parsed_output.get("major_risks_preserved", True),
        notes=parsed_output.get("notes", []) or [],
    )
