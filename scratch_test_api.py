import os
import json
import asyncio
import sys

# Добавляем пути, чтобы Python видел модули нашего проекта
sys.path.append("/opt/ai-lab/ai-senate")

# Принудительно задаем ключ для теста
os.environ["CLAUDE_API_KEY"] = "fe_oa_7c23d052eb6d8e682eaef3c5a9f393269e75874a77c876ad"

from app.agent_adapters.api import ApiAgentAdapter
from app.council_core.contracts import AgentRequestContract, Workspace, Instructions

async def test_claude():
    config = {
        "enabled": True,
        "type": "api",
        "provider": "openai_compatible",
        "role": "architectural_reviewer",
        "base_url": "https://api.freemodel.dev/v1",
        "api_key_env": "CLAUDE_API_KEY",
        "model": "gpt-5.4",
        "temperature": 0.2,
        "timeout_sec": 120
    }
    
    adapter = ApiAgentAdapter("claude", config)
    
    # Строим тестовый контракт запроса
    contract = AgentRequestContract(
        run_id="test-run-api",
        agent="claude",
        role="architectural_reviewer",
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
    
    print("🚀 Отправка тестового запроса к Claude Opus на https://cc.freemodel.dev...")
    
    result = await adapter.run(contract.json())
    
    print("\n================ РЕЗУЛЬТАТ ТЕСТА ================")
    print(f"Статус выполнения: {result.get('status')}")
    print(f"Время выполнения:  {result.get('duration_ms')} мс")
    print(f"Код HTTP ответа:   {result.get('exit_code')}")
    print(f"Таймаут:           {result.get('timeout')}")
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
    asyncio.run(test_claude())
