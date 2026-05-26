"""FastAPI route registration for the mobile creator agent."""

from __future__ import annotations

import mimetypes
import os
import re
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from modules.mobile_agent import (
    DEFAULT_MOBILE_CREATOR_SETTINGS,
    IntentRouter,
    build_agent_response,
    build_generate_fields,
)
from modules.mobile_agent_llm import response_from_llm_decision


class MobileAgentUnderstandRequest(BaseModel):
    text: str = ""
    has_image: bool = False
    has_video: bool = False
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


def register_mobile_agent_routes(app, deps: dict[str, Any]) -> None:
    get_current_user = deps["get_current_user"]
    get_current_user_optional = deps.get("get_current_user_optional", get_current_user)
    load_system_settings = deps["load_system_settings"]
    load_wf_meta = deps["load_wf_meta"]
    normalize_wf_meta_entry = deps["normalize_wf_meta_entry"]
    resolve_workflow = deps["resolve_workflow"]
    can_view_workflow = deps["can_view_workflow"]
    analyze_workflow = deps["analyze_workflow"]
    add_log = deps["add_log"]
    user_id = deps["user_id"]
    speech_transcriber_factory = deps["speech_transcriber_factory"]
    mobile_thread_store = deps.get("mobile_thread_store")
    mobile_agent_llm = deps.get("mobile_agent_llm")
    mobile_agent_llm_factory = deps.get("mobile_agent_llm_factory")

    @app.post("/api/mobile-agent/understand")
    def api_mobile_agent_understand(
        req: MobileAgentUnderstandRequest,
        current_user: dict | None = Depends(get_current_user_optional),
    ):
        attachments = _normalize_attachments(req.attachments)
        request_context = dict(req.context or {})
        if attachments:
            request_context["attachments"] = attachments
        mobile_settings = _load_mobile_creator_settings(load_system_settings)
        route_preview = IntentRouter().classify(
            req.text,
            has_image=req.has_image or bool(attachments),
            has_video=req.has_video,
            context=request_context,
        )
        workflow_setting = _workflow_setting_for_intent(route_preview.get("intent", ""))
        workflow_name = str(mobile_settings.get(workflow_setting) or "").strip()
        workflow_entry = _resolve_workflow_entry(workflow_name, load_wf_meta, normalize_wf_meta_entry)
        workflow_path = resolve_workflow(workflow_name, workflow_entry) if workflow_name else None
        workflow_available = bool(
            workflow_name
            and workflow_path
            and (current_user is None or can_view_workflow(workflow_name, workflow_entry, current_user))
        )
        llm_provider = _resolve_mobile_agent_llm(mobile_agent_llm, mobile_agent_llm_factory, mobile_settings, add_log)
        llm_result = _try_mobile_agent_llm(llm_provider, req.text, request_context, mobile_settings, add_log)
        data = response_from_llm_decision(
            llm_result,
            req.text,
            mobile_settings,
            workflow_available=workflow_available,
            context=request_context,
        )
        if data is None:
            data = build_agent_response(
                req.text,
                mobile_settings,
                workflow_available=workflow_available,
                has_image=req.has_image or bool(attachments),
                has_video=req.has_video,
                context=request_context,
            )
            if llm_result:
                data["llm_provider"] = "rule_fallback"
                data["llm_error_code"] = str(llm_result.get("error_code") or "")
                data["llm_error_message"] = str(llm_result.get("message") or "")
        if attachments:
            data["attachments"] = attachments
        can_prepare_generation = data.get("response_type") == "confirm"
        selected_workflow = str(data.get("resolved_workflow") or workflow_name or "").strip()
        selected_entry = _resolve_workflow_entry(selected_workflow, load_wf_meta, normalize_wf_meta_entry)
        selected_path = resolve_workflow(selected_workflow, selected_entry) if selected_workflow else None
        selected_available = bool(
            selected_workflow
            and selected_path
            and (current_user is None or can_view_workflow(selected_workflow, selected_entry, current_user))
        )
        if selected_workflow and can_prepare_generation:
            data["workflow_title"] = _workflow_display_name(selected_workflow, selected_entry)
        if selected_available and can_prepare_generation:
            try:
                analysis = analyze_workflow(selected_path)
                data["field_values"] = build_generate_fields(
                    _workflow_fields_from_analysis(analysis),
                    data.get("compiled_prompt", ""),
                    source_result=data.get("source_result") if isinstance(data, dict) else {},
                )
                data["workflow_choices"] = _build_workflow_choices(
                    data,
                    mobile_settings,
                    current_user,
                    load_wf_meta,
                    normalize_wf_meta_entry,
                    resolve_workflow,
                    can_view_workflow,
                    analyze_workflow,
                    add_log,
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

    @app.post("/api/mobile-agent/upload-attachment")
    async def api_mobile_agent_upload_attachment(
        file: UploadFile = File(...),
        current_user: dict | None = Depends(get_current_user_optional),
    ):
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty attachment")
        original_name = os.path.basename(file.filename or "image")
        mime_type = str(file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream")
        if not (mime_type.startswith("image/") or _looks_like_image_filename(original_name)):
            raise HTTPException(status_code=400, detail="Only image attachments are supported")
        suffix = Path(original_name).suffix.lower()
        if not suffix or not re.match(r"^\.[a-z0-9]{1,8}$", suffix):
            suffix = mimetypes.guess_extension(mime_type) or ".png"
        attachment_id = f"att_{uuid.uuid4().hex}{suffix}"
        upload_dir = Path("data") / "mobile_agent_uploads" / datetime.now().strftime("%Y%m%d")
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / attachment_id
        path.write_bytes(content)
        data = {
            "id": attachment_id,
            "name": original_name,
            "mime_type": mime_type,
            "media_type": "image",
            "size": len(content),
            "url": f"/api/mobile-agent/attachments/{attachment_id}",
        }
        add_log(
            "info",
            "mobile_agent",
            "attachment uploaded",
            details=f"user={user_id(current_user)} attachment={attachment_id} size={len(content)}",
        )
        return {"ok": True, "data": data}

    @app.get("/api/mobile-agent/attachments/{attachment_id}")
    def api_mobile_agent_attachment(attachment_id: str):
        if not re.match(r"^att_[a-f0-9]{32}\.[A-Za-z0-9]{1,8}$", attachment_id or ""):
            raise HTTPException(status_code=404, detail="Attachment not found")
        base = Path("data") / "mobile_agent_uploads"
        matches = list(base.glob(f"*/{attachment_id}"))
        if not matches:
            raise HTTPException(status_code=404, detail="Attachment not found")
        path = matches[0]
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    @app.get("/api/mobile-agent/threads")
    def api_mobile_agent_threads(current_user: dict = Depends(get_current_user)):
        store = _require_thread_store(mobile_thread_store)
        uid = user_id(current_user)
        return {"ok": True, "data": store.list_threads(uid)}

    @app.get("/api/mobile-agent/threads/{thread_id}")
    def api_mobile_agent_thread(thread_id: str, current_user: dict = Depends(get_current_user)):
        store = _require_thread_store(mobile_thread_store)
        thread = store.get_thread(user_id(current_user), thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {"ok": True, "data": thread}

    @app.put("/api/mobile-agent/threads/{thread_id}")
    def api_mobile_agent_upsert_thread(
        thread_id: str,
        payload: dict[str, Any],
        current_user: dict = Depends(get_current_user),
    ):
        store = _require_thread_store(mobile_thread_store)
        data = dict(payload or {})
        data["id"] = thread_id
        try:
            saved = store.upsert_thread(user_id(current_user), data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "data": saved}

    @app.delete("/api/mobile-agent/threads/{thread_id}")
    def api_mobile_agent_delete_thread(thread_id: str, current_user: dict = Depends(get_current_user)):
        store = _require_thread_store(mobile_thread_store)
        store.delete_thread(user_id(current_user), thread_id)
        return {"ok": True}

    @app.post("/api/mobile-agent/transcribe")
    async def api_mobile_agent_transcribe(
        file: UploadFile = File(...),
        timeout_ms: int = Form(5000),
        current_user: dict | None = Depends(get_current_user_optional),
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


def _require_thread_store(store: Any) -> Any:
    if store is None:
        raise HTTPException(status_code=503, detail="Mobile agent thread storage is not configured")
    return store


def _normalize_attachments(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for item in items[:4]:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("id") or "").strip()
        name = os.path.basename(str(item.get("name") or "图片").strip()) or "图片"
        url = str(item.get("url") or "").strip()
        mime_type = str(item.get("mime_type") or item.get("type") or "").strip()
        media_type = str(item.get("media_type") or "").strip() or ("image" if mime_type.startswith("image/") else "")
        if not attachment_id and not url:
            continue
        normalized.append({
            "id": attachment_id,
            "name": name,
            "mime_type": mime_type,
            "media_type": media_type or "image",
            "size": int(item.get("size") or 0) if str(item.get("size") or "").isdigit() else 0,
            "url": url,
        })
    return normalized


def _looks_like_image_filename(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


def _try_mobile_agent_llm(
    provider: Any,
    text: str,
    context: dict[str, Any],
    settings: dict[str, Any],
    add_log: Callable[..., Any],
) -> dict[str, Any] | None:
    if provider is None:
        return None
    try:
        result = provider.decide(text, context=context, settings=settings)
        if (
            isinstance(result, dict)
            and not result.get("ok")
            and result.get("error_code") == "llm_invalid_decision"
            and isinstance(context, dict)
            and context.get("messages")
        ):
            retry_context = {k: v for k, v in context.items() if k != "messages"}
            retry_context["messages"] = []
            retry = provider.decide(text, context=retry_context, settings=settings)
            if isinstance(retry, dict) and retry.get("ok"):
                retry["retried_without_history"] = True
                return retry
        if isinstance(result, dict):
            return result
        return {"ok": False, "provider": "unknown", "error_code": "llm_invalid_result", "message": "invalid result"}
    except Exception as exc:
        add_log("warn", "mobile_agent", f"LLM provider failed: {exc}", details=traceback.format_exc(limit=5))
        return {"ok": False, "provider": "unknown", "error_code": "llm_exception", "message": str(exc)}


def _resolve_mobile_agent_llm(
    provider: Any,
    factory: Any,
    settings: dict[str, Any],
    add_log: Callable[..., Any],
) -> Any:
    if not callable(factory):
        return provider
    try:
        return factory(settings)
    except Exception as exc:
        add_log("warn", "mobile_agent", f"LLM provider factory failed: {exc}", details=traceback.format_exc(limit=5))
        return provider


def _load_mobile_creator_settings(load_system_settings: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    settings = load_system_settings() or {}
    configured = settings.get("mobile_creator") if isinstance(settings, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    merged = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **configured}
    if not str(merged.get("default_text_to_image_workflow") or "").strip():
        merged["default_text_to_image_workflow"] = DEFAULT_MOBILE_CREATOR_SETTINGS["default_text_to_image_workflow"]
    return merged


def _workflow_setting_for_intent(intent: str) -> str:
    if intent == "image_to_image":
        return "default_image_to_image_workflow"
    return "default_text_to_image_workflow"


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


def _workflow_display_name(workflow_name: str, workflow_entry: dict[str, Any] | None) -> str:
    entry = workflow_entry if isinstance(workflow_entry, dict) else {}
    for key in ("name", "title", "label", "display_name"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return str(workflow_name or "").strip()


def _workflow_fields_from_analysis(analysis: Any) -> list[dict[str, Any]]:
    if not isinstance(analysis, dict):
        return []
    direct_fields = analysis.get("fields")
    if isinstance(direct_fields, list):
        return [field for field in direct_fields if isinstance(field, dict)]

    flattened: list[dict[str, Any]] = []
    nodes = analysis.get("nodes")
    if not isinstance(nodes, list):
        return flattened
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "")
        class_type = str(node.get("class_type") or "")
        title = str(node.get("title") or node.get("node_title") or class_type)
        for field in node.get("fields") or []:
            if not isinstance(field, dict):
                continue
            merged = dict(field)
            merged.setdefault("node_id", node_id)
            merged.setdefault("node_title", title)
            merged.setdefault("class_type", class_type)
            if not merged.get("label"):
                merged["label"] = title if str(merged.get("field") or "") == "text" else str(merged.get("field") or "")
            flattened.append(merged)
    return flattened


def _build_workflow_choices(
    data: dict[str, Any],
    settings: dict[str, Any],
    current_user: dict | None,
    load_wf_meta: Callable[[], dict[str, Any]],
    normalize_wf_meta_entry: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    resolve_workflow: Callable[..., Any],
    can_view_workflow: Callable[..., bool],
    analyze_workflow: Callable[[Any], Any],
    add_log: Callable[..., Any],
) -> list[dict[str, Any]]:
    selected = str(data.get("resolved_workflow") or "").strip()
    intent = str(data.get("intent") or "text_to_image").strip()
    meta = load_wf_meta() or {}
    names = _candidate_workflow_names(selected, intent, settings, meta)
    choices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        entry = _resolve_workflow_entry(name, load_wf_meta, normalize_wf_meta_entry)
        path = resolve_workflow(name, entry)
        if not path:
            continue
        if current_user is not None and not can_view_workflow(name, entry, current_user):
            continue
        try:
            fields = build_generate_fields(
                _workflow_fields_from_analysis(analyze_workflow(path)),
                data.get("compiled_prompt", ""),
                source_result=data.get("source_result") if isinstance(data, dict) else {},
            )
        except Exception as exc:
            add_log(
                "warn",
                "mobile_agent",
                f"workflow choice analysis failed: {name}: {exc}",
                details=traceback.format_exc(limit=5),
            )
            continue
        choices.append({
            "workflow": name,
            "title": _workflow_display_name(name, entry),
            "field_values": fields,
            "available": True,
        })
        if len(choices) >= 12:
            break
    return choices


def _candidate_workflow_names(
    selected: str,
    intent: str,
    settings: dict[str, Any],
    meta: dict[str, Any],
) -> list[str]:
    names: list[str] = []
    default_key = "default_image_to_image_workflow" if intent == "image_to_image" else "default_text_to_image_workflow"
    for name in (selected, str(settings.get(default_key) or "").strip()):
        if name and name not in names:
            names.append(name)
    if isinstance(meta, dict):
        for name, entry in meta.items():
            filename = str(name or "").strip()
            if not filename or filename in names:
                continue
            if _workflow_matches_intent(filename, entry, intent):
                names.append(filename)
    return names


def _workflow_matches_intent(filename: str, entry: Any, intent: str) -> bool:
    text = filename.lower()
    if isinstance(entry, dict):
        parts = [str(entry.get(key) or "") for key in ("name", "title", "label", "display_name", "type", "workflow_type")]
        tags = entry.get("tags")
        if isinstance(tags, list):
            parts.extend(str(tag or "") for tag in tags)
        text += " " + " ".join(parts).lower()
    if intent == "image_to_image":
        return any(token in text for token in ("i2i", "image_to_image", "img2img", "图生图", "改图", "图片编辑"))
    if any(token in text for token in ("video", "视频", "t2v", "i2v", "image_to_video", "文生视频", "图生视频")):
        return False
    if any(token in text for token in ("i2i", "image_to_image", "img2img", "图生图", "改图")):
        return False
    return any(token in text for token in ("t2i", "text_to_image", "txt2img", "文生图", "生图", "image", "图片"))


def _mark_workflow_mapping_failed(data: dict[str, Any]) -> None:
    data["field_values"] = {}
    data["needs_confirmation"] = True
    data["error_code"] = "workflow_analysis_failed"
    data["question"] = "工作流字段解析失败，请稍后重试或在高级工作流界面手动填写提示词。"
    data["message"] = "Workflow analysis failed while mapping the compiled prompt to generation fields."
