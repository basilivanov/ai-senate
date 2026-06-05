import os
import json
import yaml
from typing import Dict, Any
from app.council_core.contracts import WriterRequestContract, WriterResponseContract, WriterWorkspace, WriterInputs
from app.agent_adapters.cli import CliAgentAdapter
from app.agent_adapters.api import ApiAgentAdapter

async def run_writer(
    run_id: str,
    new_document: bool,
    spec_file: str,
    owner_input_file: str,
    findings_file: str,
    consensus_file: str,
    agent_outputs_dir: str,
    output_file: str
) -> WriterResponseContract:
    """
    Executes the writer/synthesizer agent to generate the updated specification.
    Logs raw outputs and saves the resulting document.
    """
    # 1. Load writer config from agents.yaml
    config_path = "/opt/ai-lab/ai-senate/app/config/agents.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    writer_config = config.get("agents", {}).get("writer")
    if not writer_config:
        raise ValueError("Writer agent configuration not found in agents.yaml")
        
    # 2. Build Strongly Typed Request Contract
    request = WriterRequestContract(
        schema_version="writer_request_v1",
        run_id=run_id,
        new_document=new_document,
        workspace=WriterWorkspace(
            spec_file=spec_file,
            owner_input_file=owner_input_file
        ),
        inputs=WriterInputs(
            findings_file=findings_file,
            consensus_file=consensus_file,
            agent_outputs_dir=agent_outputs_dir
        ),
        task="Create updated specification without hiding blockers, major risks or unresolved questions. Return the new document content in JSON under the 'updated_document_content' field.",
        output_file=output_file
    )
    
    request_json = request.json(indent=2)
    
    # Create logging directory for the writer
    writer_run_dir = os.path.join(agent_outputs_dir, "writer")
    os.makedirs(writer_run_dir, exist_ok=True)
    
    # Save the request prompt/contract
    with open(os.path.join(writer_run_dir, "request.json"), "w", encoding="utf-8") as f:
        f.write(request_json)
        
    # 3. Instantiate appropriate adapter based on config
    agent_type = writer_config.get("type", "cli")
    if agent_type == "cli":
        adapter = CliAgentAdapter("writer", writer_config)
    else:
        adapter = ApiAgentAdapter("writer", writer_config)
        
    # 4. Run the Writer
    execution_result = await adapter.run(request_json)
    
    # Save artifacts
    with open(os.path.join(writer_run_dir, "stdout.txt"), "w", encoding="utf-8") as f:
        f.write(execution_result.get("stdout", ""))
        
    with open(os.path.join(writer_run_dir, "stderr.txt"), "w", encoding="utf-8") as f:
        f.write(execution_result.get("stderr", ""))
        
    status_json = {
        "agent": "writer",
        "status": execution_result.get("status"),
        "duration_ms": execution_result.get("duration_ms"),
        "exit_code": execution_result.get("exit_code"),
        "timeout": execution_result.get("timeout"),
        "parsed": execution_result.get("status") == "done",
        "error": execution_result.get("error")
    }
    
    with open(os.path.join(writer_run_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status_json, f, indent=2)
        
    # 5. Handle Writer execution failures gracefully (Section 21 Rule 8)
    if execution_result.get("status") != "done" or not execution_result.get("parsed_output"):
        error_msg = execution_result.get("error", "Unknown error occurred during synthesis.")
        
        # We read the original spec if it exists to fall back gracefully
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
            notes=[f"Stderr: {execution_result.get('stderr', '')}"]
        )
        
    parsed_output = execution_result["parsed_output"]
    updated_content = parsed_output.get("updated_document_content", "")
    
    # 6. Save the generated spec to filesystem (Backend writes the file!)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(updated_content)
        
    # Return strongly-typed response
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
        notes=parsed_output.get("notes", [])
    )
