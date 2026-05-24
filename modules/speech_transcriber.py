"""Optional local speech-to-text adapter for mobile creator voice input."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SAFE_AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".wav",
    ".webm",
}


class SpeechTranscriber:
    TEMP_PREFIX = "ez-speech-"

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

        suffix = self._safe_suffix(filename)
        timeout_sec = max(1, int(timeout_ms or 5000)) / 1000.0
        result: dict[str, Any] | None = None

        try:
            temp_dir = tempfile.mkdtemp(prefix=self.TEMP_PREFIX)
        except OSError as e:
            return self._failure("speech_temp_failed", str(e))

        try:
            try:
                with tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=suffix) as audio_file:
                    audio_file.write(content)
            except OSError as e:
                result = self._failure("speech_temp_failed", str(e))

            if result is not None:
                return result
            audio_path = Path(audio_file.name)
            txt_path = audio_path.with_suffix(".txt")
            try:
                proc = subprocess.run(
                    [command_path, str(audio_path), "--output_format", "txt", "--output_dir", temp_dir],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                result = self._failure("speech_timeout")
                return result
            except OSError as e:
                result = self._failure("speech_transcribe_failed", str(e))
                return result

            if proc.returncode != 0:
                result = self._failure("speech_transcribe_failed", self._short_message(proc))
                return result

            try:
                transcript = txt_path.read_text(encoding="utf-8").strip() if txt_path.exists() else ""
            except (OSError, UnicodeDecodeError) as e:
                result = self._failure("speech_transcribe_failed", str(e))
                return result

            result = {
                "ok": bool(transcript),
                "provider": self.command,
                "transcript": transcript,
                "duration_ms": 0,
                "error_code": "" if transcript else "empty_transcript",
            }
            return result
        finally:
            self._cleanup_temp_dir(temp_dir)

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

    @staticmethod
    def _safe_suffix(filename: str) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in SAFE_AUDIO_SUFFIXES:
            return suffix
        return ".webm"

    @staticmethod
    def _cleanup_temp_dir(temp_dir: str) -> str:
        try:
            shutil.rmtree(temp_dir)
        except OSError as e:
            return str(e)
        return ""
