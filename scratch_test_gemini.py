import os
import json
import asyncio
import sys

sys.path.append("/opt/ai-lab/ai-senate")

os.environ["AGY_PROXY_API_KEY"] = "sk-cliproxy-local"

from app.agent_adapters.api import ApiAgentAdapter
from app.council_core.contracts import AgentRequestContract, Workspace, Instructions

async def test_gemini():
    config = {
        "enabled": True,
        "type": "api",
        "provider": "openai_compatible",
        "role": "critical_reviewer",
        "base_url": "http://127.0.0.1:18317/v1",
        "api_key_env": "AGY_PROXY_API_KEY",
        "model": "gemini-3.1-pro-preview",
        "temperature": 0.2,
        "timeout_sec": 120
    }
    
    adapter = ApiAgentAdapter("agy", config)
    
    contract = AgentRequestContract(
        run_id="test-run-gemini",
        agent="agy",
        role="critical_reviewer",
        task="Проверь ТЗ: нужно сделать чат-бота для техподдержки. Стек: FastAPI. Дай структурированный фидбек.",
        new_document=True,
        workspace=Workspace(
            root="/opt/ai-lab/ai-senate",
            spec_file="",
            owner_input_file=""
        ),
        instructions=Instructions(
            focus=["MVP scope"]
        )
    )
    
    print("🚀 Отправка тестового запроса к Gemini 3.1 Pro на локальный прокси...")
    
    result = await adapter.run(contract.json())
    
    print("\n================ РЕЗУЛЬТАТ ТЕСТА ================")
    print(f"Статус выполнения: {result.get('status')}")
    print(f"Время выполнения:  {result.get('duration_ms')} мс")
    print(f"Код HTTP ответа:   {result.get('exit_code')}")
    print(f"Ошибка (если есть): {result.get('error')}")
    print("\n--- СЫРОЙ ОТВЕТ (первые 800 символов) ---")
    print(result.get("raw_output", "")[:800])
    
    if result.get("parsed_output"):
        print("\n--- УСПЕШНО САРСЕННЫЙ JSON (Decision & Summary) ---")
        print(f"Decision:   {result['parsed_output'].get('decision')}")
        print(f"Summary:    {result['parsed_output'].get('summary')}")
        print(f"Количество замечаний: {len(result['parsed_output'].get('items', []))}")
    else:
        print("\n⚠️ Внимание: Не удалось распарсить JSON из ответа модели!")

if __name__ == "__main__":
    asyncio.run(test_gemini())
