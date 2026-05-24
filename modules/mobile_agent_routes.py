"""FastAPI route registration for the mobile creator agent."""

from __future__ import annotations

import traceback
from typing import Any, Callable

from fastapi import Depends, File, Form, UploadFile
from pydantic import BaseModel

from modules.mobile_agent import (
    DEFAULT_MOBILE_CREATOR_SETTINGS,
    build_agent_response,
    build_generate_fields,
)


class MobileAgentUnderstandRequest(BaseModel):
    text: str = ""
    has_image: bool = False
    has_video: bool = False


def register_mobile_agent_routes(app, deps: dict[str, Callable[..., Any]]) -> None:
    get_current_user = deps["get_current_user"]
    load_system_settings = deps["load_system_settings"]
    load_wf_meta = deps["load_wf_meta"]
    normalize_wf_meta_entry = deps["normalize_wf_meta_entry"]
    resolve_workflow = deps["resolve_workflow"]
    can_view_workflow = deps["can_view_workflow"]
    analyze_workflow = deps["analyze_workflow"]
    add_log = deps["add_log"]
    user_id = deps["user_id"]
    speech_transcriber_factory = deps["speech_transcriber_factory"]

    @app.post("/api/mobile-agent/understand")
    def api_mobile_agent_understand(
        req: MobileAgentUnderstandRequest,
        current_user: dict = Depends(get_current_user),
    ):
        mobile_settings = _load_mobile_creator_settings(load_system_settings)
        workflow_name = str(mobile_settings.get("default_text_to_image_workflow") or "").strip()
        workflow_entry = _resolve_workflow_entry(workflow_name, load_wf_meta, normalize_wf_meta_entry)
        workflow_path = resolve_workflow(workflow_name, workflow_entry) if workflow_name else None
        workflow_available = bool(
            workflow_name
            and workflow_path
            and can_view_workflow(workflow_name, workflow_entry, current_user)
        )
        data = build_agent_response(
            req.text,
            mobile_settings,
            workflow_available=workflow_available,
            has_image=req.has_image,
            has_video=req.has_video,
        )
        if workflow_available:
            try:
                analysis = analyze_workflow(workflow_path)
                data["field_values"] = build_generate_fields(
                    analysis.get("fields") if isinstance(analysis, dict) else [],
                    data.get("compiled_prompt", ""),
                )
            except Exception as e:
                add_log(
                    "warn",
                    "mobile_agent",
                    f"workflow analysis failed: {e}",
                    details=traceback.format_exc(limit=5),
                )
                _mark_workflow_mapping_failed(data)
        else:
            data["field_values"] = {}
        add_log(
            "info",
            "mobile_agent",
            "understand request processed",
            details=f"user={user_id(current_user)} workflow={workflow_name} available={workflow_available}",
        )
        return {"ok": True, "data": data}

    @app.post("/api/mobile-agent/transcribe")
    async def api_mobile_agent_transcribe(
        file: UploadFile = File(...),
        timeout_ms: int = Form(5000),
        current_user: dict = Depends(get_current_user),
    ):
        try:
            content = await file.read()
            transcriber = speech_transcriber_factory()
            result = transcriber.transcribe_bytes(
                content,
                filename=file.filename or "voice.webm",
                timeout_ms=timeout_ms,
            )
        except Exception as e:
            result = {
                "ok": False,
                "provider": "none",
                "transcript": "",
                "duration_ms": 0,
                "error_code": "speech_transcribe_failed",
                "message": str(e),
            }

        level = "info" if result.get("ok") else "warn"
        add_log(
            level,
            "mobile_agent",
            "speech transcription completed" if result.get("ok") else "speech transcription failed",
            details=f"user={user_id(current_user)} error_code={result.get('error_code', '')}",
        )
        return result


def _load_mobile_creator_settings(load_system_settings: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    settings = load_system_settings() or {}
    configured = settings.get("mobile_creator") if isinstance(settings, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    merged = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **configured}
    if not str(merged.get("default_text_to_image_workflow") or "").strip():
        merged["default_text_to_image_workflow"] = DEFAULT_MOBILE_CREATOR_SETTINGS["default_text_to_image_workflow"]
    return merged


def _resolve_workflow_entry(
    workflow_name: str,
    load_wf_meta: Callable[[], dict[str, Any]],
    normalize_wf_meta_entry: Callable[[str, dict[str, Any] | None], dict[str, Any]],
) -> dict[str, Any]:
    if not workflow_name:
        return normalize_wf_meta_entry("", {})
    meta = load_wf_meta() or {}
    entry = meta.get(workflow_name, {}) if isinstance(meta, dict) else {}
    return normalize_wf_meta_entry(workflow_name, entry)


def _mark_workflow_mapping_failed(data: dict[str, Any]) -> None:
    data["field_values"] = {}
    data["needs_confirmation"] = True
    data["error_code"] = "workflow_analysis_failed"
    data["question"] = "工作流字段解析失败，请稍后重试或在高级工作流界面手动填写提示词。"
    data["message"] = "Workflow analysis failed while mapping the compiled prompt to generation fields."
