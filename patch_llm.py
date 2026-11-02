import re
from pathlib import Path

path = Path("server/app/services/llm_client.py")
content = path.read_text(encoding="utf-8")

if "pixel_lst: float | None = None" not in content:
    content = content.replace(
        "def _build_prompt(\n    evidence: dict[str, Any],\n    knowledge_context: List[Dict[str, Any]],\n    deterministic_text: str,\n) -> str:",
        "def _build_prompt(\n    evidence: dict[str, Any],\n    knowledge_context: List[Dict[str, Any]],\n    deterministic_text: str,\n    pixel_lst: float | None = None,\n) -> str:"
    )
    
    pixel_prompt_injection = """
    pixel_instruction = ""
    if pixel_lst is not None:
        pixel_instruction = f"\\nPIXEL CONTEXT:\\nThe user clicked on a specific pixel. Pixel-level LST: {pixel_lst} °C. Analytical-zone Mean LST: {evidence.get('measurements', {}).get('lst')} °C.\\nRule 6: Distinguish between the Pixel-level measurement ({pixel_lst} °C) and the Analytical-zone context when discussing LST. Use language such as: 'The selected location shows elevated land-surface temperature relative to the surrounding analytical context.'"
"""
    content = content.replace("city = evidence.get(\"zone\", {}).get(\"city\", \"Mumbai\") # Default fallback", "city = evidence.get(\"zone\", {}).get(\"city\", \"Mumbai\") # Default fallback\n" + pixel_prompt_injection)
    
    content = content.replace("{knowledge_json}", "{knowledge_json}\n{pixel_instruction}")

    content = content.replace(
        "async def call_gemini(\n    evidence: dict[str, Any],\n    knowledge_context: List[Dict[str, Any]],\n    deterministic_text: str,\n) -> Dict[str, Any]:",
        "async def call_gemini(\n    evidence: dict[str, Any],\n    knowledge_context: List[Dict[str, Any]],\n    deterministic_text: str,\n    pixel_lst: float | None = None,\n) -> Dict[str, Any]:"
    )
    
    content = content.replace(
        "prompt = _build_prompt(evidence, knowledge_context, deterministic_text)",
        "prompt = _build_prompt(evidence, knowledge_context, deterministic_text, pixel_lst)"
    )

    content = content.replace(
        "async def generate_llm_explanation(\n    evidence: dict[str, Any],\n    knowledge_context: List[Dict[str, Any]],\n    deterministic_text: str,\n) -> Dict[str, Any]:",
        "async def generate_llm_explanation(\n    evidence: dict[str, Any],\n    knowledge_context: List[Dict[str, Any]],\n    deterministic_text: str,\n    pixel_lst: float | None = None,\n) -> Dict[str, Any]:"
    )
    
    content = content.replace(
        "return await call_gemini(evidence, knowledge_context, deterministic_text)",
        "return await call_gemini(evidence, knowledge_context, deterministic_text, pixel_lst)"
    )

path.write_text(content, encoding="utf-8")
print("Patched llm_client.py")
