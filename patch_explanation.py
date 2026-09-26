import re
from pathlib import Path

path = Path("server/app/services/explanation_service.py")
content = path.read_text(encoding="utf-8")

if "pixel_lst: float | None = None" not in content:
    # update signature of build_full_explanation
    content = content.replace(
        "async def build_full_explanation(db, zone_id: int) -> Dict[str, Any]:",
        "async def build_full_explanation(db, zone_id: int, pixel_lst: float | None = None) -> Dict[str, Any]:"
    )
    # update call to generate_llm_explanation
    content = content.replace(
        "llm_explanation = await generate_llm_explanation(evidence, knowledge_context, deterministic_text)",
        "llm_explanation = await generate_llm_explanation(evidence, knowledge_context, deterministic_text, pixel_lst)"
    )
    # update _validate_llm_explanation
    content = content.replace(
        "def _validate_llm_explanation(llm_expl: dict[str, Any], evidence: dict[str, Any]) -> list[str]:",
        "def _validate_llm_explanation(llm_expl: dict[str, Any], evidence: dict[str, Any], pixel_lst: float | None = None) -> list[str]:"
    )
    content = content.replace(
        "llm_warnings = _validate_llm_explanation(llm_explanation, evidence)",
        "llm_warnings = _validate_llm_explanation(llm_explanation, evidence, pixel_lst)"
    )
    
    # update the lst check inside validation
    old_check = """        actual_val = measurements.get(metric)
        if actual_val is not None:
            matches = re.findall(pattern, full_text)
            for match in matches:
                try:
                    claimed_val = float(match)
                    # allow a small epsilon for floating point rounding
                    if abs(claimed_val - float(actual_val)) > 0.1:
                        warnings.append(f"hallucination: LLM claimed {metric} is {claimed_val} but actual is {actual_val}")
                except ValueError:
                    pass"""
    
    new_check = """        actual_val = measurements.get(metric)
        actual_vals = []
        if actual_val is not None:
            actual_vals.append(float(actual_val))
        if metric == "lst" and pixel_lst is not None:
            actual_vals.append(float(pixel_lst))
            
        if actual_vals:
            matches = re.findall(pattern, full_text)
            for match in matches:
                try:
                    claimed_val = float(match)
                    if not any(abs(claimed_val - val) <= 0.1 for val in actual_vals):
                        warnings.append(f"hallucination: LLM claimed {metric} is {claimed_val} but valid values are {actual_vals}")
                except ValueError:
                    pass"""
    content = content.replace(old_check, new_check)

path.write_text(content, encoding="utf-8")
print("Patched explanation_service.py")
