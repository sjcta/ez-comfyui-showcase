"""Validation helpers for ComfyUI API prompt workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowIssue:
    node_id: str
    field: str
    kind: str
    value: Any

    def label(self) -> str:
        if self.kind == "missing_node":
            return f"{self.node_id}::{self.field} -> {self.value}"
        return f"{self.node_id}::{self.field}"


def validate_api_prompt(workflow: dict[str, Any]) -> list[WorkflowIssue]:
    """Return graph/link issues that would make ComfyUI reject a prompt."""
    issues: list[WorkflowIssue] = []
    node_ids = {str(k) for k, v in workflow.items() if isinstance(v, dict)}

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for field, value in inputs.items():
            if not isinstance(value, list) or len(value) < 2:
                continue
            source = value[0]
            if source is None:
                issues.append(WorkflowIssue(str(node_id), str(field), "placeholder", value))
            elif str(source) not in node_ids:
                issues.append(WorkflowIssue(str(node_id), str(field), "missing_node", source))

    return issues


def describe_api_prompt_issues(issues: list[WorkflowIssue], limit: int = 8) -> str:
    """Build a concise Chinese error message for invalid ComfyUI prompts."""
    if not issues:
        return ""

    missing = [item for item in issues if item.kind == "missing_node"]
    placeholders = [item for item in issues if item.kind == "placeholder"]
    examples = ", ".join(item.label() for item in issues[:limit])
    return (
        "工作流不是可提交的 ComfyUI API Prompt："
        f"{len(missing)} 个连接指向不存在的节点，"
        f"{len(placeholders)} 个输入仍是占位值。"
        f"示例: {examples}；"
        "请重新从 ComfyUI 导出 API Prompt 格式的工作流后再同步。"
    )
