"""Optional local speech-to-text adapter for mobile creator voice input."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class SpeechTranscriber:
    def __init__(self, command: str | None = None) -> None:
        self.command = command or os.environ.get("EZ_WHISPER_COMMAND") or "whisper"

    def transcribe_bytes(
        self,
        content: bytes,
        filename: str = "voice.webm",
        timeout_ms: int = 5000,
    ) -> dict[str, Any]:
        if not content:
            return self._failure("empty_audio")

        command_path = shutil.which(self.command)
        if not command_path:
            return self._failure("speech_backend_unavailable")

        suffix = Path(filename or "voice.webm").suffix or ".webm"
        timeout_sec = max(1, int(timeout_ms or 5000)) / 1000.0

        with tempfile.TemporaryDirectory(prefix="ez-speech-") as temp_dir:
            audio_file = tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=suffix)
            try:
                with audio_file:
                    audio_file.write(content)

                audio_path = Path(audio_file.name)
                txt_path = audio_path.with_suffix(".txt")
                proc = subprocess.run(
                    [command_path, str(audio_path), "--output_format", "txt", "--output_dir", temp_dir],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    check=False,
                )
                if proc.returncode != 0:
                    return self._failure("speech_transcribe_failed", self._short_message(proc))

                transcript = txt_path.read_text(encoding="utf-8").strip() if txt_path.exists() else ""
                return {
                    "ok": bool(transcript),
                    "provider": self.command,
                    "transcript": transcript,
                    "duration_ms": 0,
                    "error_code": "" if transcript else "empty_transcript",
                }
            except subprocess.TimeoutExpired:
                return self._failure("speech_timeout")

    @staticmethod
    def _failure(error_code: str, message: str = "") -> dict[str, Any]:
        result = {
            "ok": False,
            "provider": "none",
            "transcript": "",
            "duration_ms": 0,
            "error_code": error_code,
        }
        if message:
            result["message"] = message
        return result

    @staticmethod
    def _short_message(proc: subprocess.CompletedProcess[str]) -> str:
        text = (proc.stderr or proc.stdout or "").strip()
        if not text:
            return f"speech command exited with code {proc.returncode}"
        return text[:500]
