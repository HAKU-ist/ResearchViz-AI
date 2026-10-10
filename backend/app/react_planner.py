from typing import Any

def build_planner_trace_step(action: str, status: str, notes: list[str] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"action": action, "status": status}
    if notes:
        result["notes"] = notes
    if payload:
        result["payload"] = payload
    return result
