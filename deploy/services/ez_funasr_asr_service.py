#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ASR_MODEL = None
ASR_MODEL_NAME = os.environ.get("EZ_FUNASR_MODEL", "sensevoice").strip().lower()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _load_funasr():
    global ASR_MODEL
    if ASR_MODEL is not None:
        return ASR_MODEL
    from funasr import AutoModel

    kwargs = {"device": os.environ.get("EZ_FUNASR_DEVICE", "cuda:0")}
    if ASR_MODEL_NAME == "sensevoice":
        kwargs.update({"model": os.environ.get("EZ_FUNASR_SENSEVOICE_MODEL", "iic/SenseVoiceSmall"), "vad_model": "fsmn-vad"})
    elif ASR_MODEL_NAME == "paraformer":
        kwargs.update({"model": "paraformer-zh", "vad_model": "fsmn-vad", "punc_model": "ct-punc"})
    elif ASR_MODEL_NAME == "paraformer-streaming":
        kwargs.update({"model": "paraformer-zh-streaming"})
    elif ASR_MODEL_NAME == "fun-asr-nano":
        kwargs.update({"model": "FunAudioLLM/Fun-ASR-Nano-2512", "hub": "hf", "trust_remote_code": True})
    else:
        raise ValueError(f"unknown FunASR model: {ASR_MODEL_NAME}")
    ASR_MODEL = AutoModel(**kwargs)
    return ASR_MODEL


def _duration_s(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate() or 16000)
    except Exception:
        return 0.0


def _clean_text(text: str) -> str:
    import re

    text = str(text or "")
    text = re.sub(r"<\|[^|]+?\|>", "", text)
    return text.strip()


def _transcribe_wav(path: Path) -> dict:
    model = _load_funasr()
    started = time.perf_counter()
    if ASR_MODEL_NAME == "fun-asr-nano":
        result = model.generate(input=[str(path)], cache={}, batch_size=1, language="中文", itn=True)
    else:
        result = model.generate(input=str(path), batch_size_s=60)
    elapsed = time.perf_counter() - started
    text = ""
    if isinstance(result, list) and result:
        text = str(result[0].get("text") or result[0].get("sentence") or "")
    return {
        "ok": True,
        "text": _clean_text(text),
        "language": "zh",
        "duration": round(_duration_s(path), 4),
        "elapsed": round(elapsed, 4),
        "provider": "funasr",
        "model": ASR_MODEL_NAME,
    }


class ASRHandler(BaseHTTPRequestHandler):
    server_version = "EZFunASR/0.1"

    def do_GET(self):
        if self.path == "/health":
            _json_response(self, 200, {"ok": True, "provider": "funasr", "model": ASR_MODEL_NAME, "loaded": ASR_MODEL is not None})
            return
        _json_response(self, 404, {"ok": False, "detail": "not found"})

    def do_POST(self):
        if self.path != "/asr/transcribe":
            _json_response(self, 404, {"ok": False, "detail": "not found"})
            return
        temp_path = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise ValueError("empty audio")
            data = self.rfile.read(length)
            tmp_dir = Path(os.environ.get("EZ_FUNASR_TMP_DIR", "/tmp"))
            tmp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="ez_asr_", suffix=".wav", dir=str(tmp_dir), delete=False) as tmp:
                tmp.write(data)
                temp_path = Path(tmp.name)
            _json_response(self, 200, _transcribe_wav(temp_path))
        except Exception as exc:
            _json_response(self, 500, {"ok": False, "detail": str(exc), "traceback": traceback.format_exc(limit=8)})
        finally:
            if temp_path:
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    host = os.environ.get("EZ_FUNASR_HOST", "0.0.0.0")
    port = int(os.environ.get("EZ_FUNASR_PORT", "18211"))
    if os.environ.get("EZ_FUNASR_PRELOAD", "1") != "0":
        _load_funasr()
    print(f"EZ FunASR service listening on {host}:{port}, model={ASR_MODEL_NAME}", flush=True)
    ThreadingHTTPServer((host, port), ASRHandler).serve_forever()


if __name__ == "__main__":
    main()
