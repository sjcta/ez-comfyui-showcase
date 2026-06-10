"""Local lightweight image protection checks for generated previews."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import threading
from typing import Callable, Iterable, Any

from modules.llm_client import DIRECT_FINAL_SYSTEM_PROMPT, chat_text, image_to_data_url


_PROMPT_PATTERN_DEFAULTS = {
    "hard": (
        r"18\s*\+|18禁|r18|r-18|nsfw|nfsw|私处|乳头|性器官|生殖器|阴部|阴茎|外阴|色情|情色|露点|"
        r"\bnipples?\b|\bgenitals?\b|\bpenis\b|\bvagina\b|\bsex\b|\bsexual\b|\bporn\b|\berotic\b"
    ),
    "risk": (
        r"露出乳头|裸露乳头|露出生殖器|露出性器官|暴露性器官|"
        r"裸体|全裸|全身裸体|赤裸|裸身|一丝不挂|"
        r"无衣物|无任何衣物|没有衣物|不穿(?:衣服|衣物)|没有衣服|"
        r"没穿[^，。,.;；]*(?:衣服|衣物)|未穿[^，。,.;；]*(?:衣服|衣物)|"
        r"(?:去除|移除)(?:所有|全部)?(?:衣服|衣物)|脱(?:掉|去)[^，。,.;；]*(?:衣服|衣物)|"
        r"\bgenitals?\b|\bpenis\b|\bvagina\b|\bnipples?\b|\bnudes?\b|\bnaked\b|\bfully\s+nude\b|\bfull\s+nude\b|"
        r"\bcompletely\s+naked\b|\bno\s+clothes\b|\bwithout\s+clothes\b|"
        r"\bremove\s+(?:all\s+)?(?:clothes|clothing)\b|\btake\s+off\s+(?:all\s+)?(?:clothes|clothing)\b|"
        r"\bclothes\s+off\b|\bundressed\b|\bunclothed\b"
    ),
    "strong_nude": (
        r"全裸|裸体|全身裸体|赤裸|裸身|一丝不挂|"
        r"\bnudes?\b|\bnaked\b|\bfully\s+nude\b|\bfull\s+nude\b|\bcompletely\s+naked\b"
    ),
    "violence": (
        r"血腥|血迹|大量血|暴力|重伤|伤口|肢解|断肢|残肢|内脏|开膛|尸体|谋杀|砍杀|枪击|刺穿|"
        r"\bblood(?:y)?\b|\bgore\b|\bgory\b|\bgraphic\s+violence\b|\bsevere\s+injury\b|"
        r"\bmutilat(?:e|ed|ion)\b|\bdismember(?:ed|ment)?\b|\bexposed\s+organs?\b|\bcorpse\b"
    ),
    "obscene_gesture": r"竖中指|中指手势|不雅手势|\bmiddle\s+finger\b|\bobscene\s+gesture\b",
}
_PROMPT_RE = re.compile(_PROMPT_PATTERN_DEFAULTS["hard"], re.IGNORECASE)
_NSFW_RISK_PROMPT_RE = re.compile(_PROMPT_PATTERN_DEFAULTS["risk"], re.IGNORECASE)
_STRONG_NUDE_PROMPT_RE = re.compile(_PROMPT_PATTERN_DEFAULTS["strong_nude"], re.IGNORECASE)
_VIOLENCE_PROMPT_RE = re.compile(_PROMPT_PATTERN_DEFAULTS["violence"], re.IGNORECASE)
_OBSCENE_GESTURE_RE = re.compile(_PROMPT_PATTERN_DEFAULTS["obscene_gesture"], re.IGNORECASE)
_UNSAFE_LABEL_RE = re.compile(r"nsfw|unsafe|porn|hentai|sexy|sexual|nude|explicit|r18", re.IGNORECASE)
_SAFE_LABEL_RE = re.compile(r"safe|normal|neutral|drawing|anime|sfw", re.IGNORECASE)
_DETECTOR_PROTECT_LABEL_RE = re.compile(
    r"(exposed|visible).*(nipple|genital|vagina|penis|anus)|"
    r"(nipple|genital|vagina|penis|anus).*(exposed|visible)|"
    r"female_genitalia_exposed|male_genitalia_exposed|anus_exposed|"
    r"exposed_genital|exposed_genitalia|exposed_anus",
    re.IGNORECASE,
)
_DETECTOR_IGNORE_LABEL_RE = re.compile(
    r"covered|face|feet|belly|armpit|male[_ -]?breast",
    re.IGNORECASE,
)
_STRONG_PROMPT_SKIN_THRESHOLD = 0.14
_STRONG_NUDE_SKIN_THRESHOLD = 0.14
_NSFW_RISK_SKIN_THRESHOLD = 0.18
_VISUAL_INTIMATE_SKIN_THRESHOLD = 0.40
_DETECTOR_PAIRED_BREAST_THRESHOLD = 0.56
_DETECTOR_BUTTOCKS_THRESHOLD = 0.75
_DETECTOR_WEAK_BREAST_PROMPT_THRESHOLD = 0.52
_LLM_VISION_REVIEW_PROMPT = (
    "Act as an expert visual content-safety reviewer. Inspect the visible image carefully for two "
    "families only: sexual/erotic exposure and violence/gore. Do not judge skin exposure area by "
    "itself. Ordinary pets, cats, dogs, animals, plush toys, cartoons, swimwear, underwear, cleavage, "
    "bare shoulders, bare back, bare torso, bare legs, fitness, fashion, medical, or non-sexual "
    "artistic nudity must stay safe unless there is visible sexual content or graphic violence. "
    "For sexual review, specifically check whether nipples, areolae, labia/vulva, penis/scrotum, anus, "
    "erection, sexual acts, sexual fluids, or sexually explicit contact are actually visible. Treat "
    "wet, sheer, transparent, translucent, see-through, mesh, lace, thin, or body-painted material as "
    "exposure when nipples/areolae/genitals/anus are visibly discernible through it. For violence "
    "review, estimate visible blood/gore severity: none, mild blood, injury, graphic blood, gore, "
    "mutilation, exposed organs, severe injury, or active violent harm. The generation prompt is "
    "only context for ambiguous visual evidence; visible image evidence controls. Return one JSON "
    "object with keys: protected boolean, sexual_visible boolean, violent_visible boolean, "
    "confidence number from 0 to 1, violence_level string, sexual_findings string, violence_findings "
    "string, reason short string. The protected field MUST be true if and only if sexual_visible or "
    "violent_visible is true. If both sexual_visible and violent_visible are false, protected MUST be "
    "false, even when the image contains underwear, thong, bare back, bare shoulders, cleavage, or "
    "ordinary non-sexual skin exposure. A covered crotch/pubic area under underwear, thong, swimsuit, "
    "fabric, shadow, or an object is safe; do not call it genitals unless a concrete anatomical feature "
    "such as labia/vulva, penis/scrotum, anus, nipple, or areola is visibly discernible."
)
_LLM_VISION_REVIEW_PROMPT_STRICT = (
    "Second-pass expert visual safety verifier. Inspect only what is actually visible in the image. "
    "Return protected=true only when at least one of these is clearly visible: nipples, areolae, "
    "labia/vulva, penis/scrotum, anus, sexual act/contact/fluids, or graphic violence/gore/severe injury. Do not infer "
    "hidden anatomy from camera angle, underwear, thong, shadows, body outline, bare torso, bare legs, "
    "or ordinary skin exposure. Sheer or transparent fabric counts only when the protected body part is "
    "visibly discernible through the material. Return one JSON object with keys: protected boolean, "
    "sexual_visible boolean, violent_visible boolean, confidence number from 0 to 1, violence_level "
    "string, sexual_findings string, violence_findings string, reason short string."
)
_LLM_VISION_REVIEW_PROMPT_ADJUDICATOR = (
    "Final adjudicator for visual content-safety. Decide from visible evidence only. Protect the image "
    "when sexual exposure or violence/gore is actually visible; release it when the image only shows "
    "covered underwear/swimwear/thong, bare skin, suggestive pose, low-angle view, or ambiguous shapes "
    "without visible protected anatomy or violent injury. Be strict about real leaks through transparent "
    "material, but do not hallucinate body parts hidden by fabric or objects. Return one JSON object with "
    "keys: protected boolean, sexual_visible boolean, violent_visible boolean, confidence number from 0 "
    "to 1, violence_level string, sexual_findings string, violence_findings string, reason short string."
)

_SETTINGS_LOCK = threading.Lock()
_RUNTIME_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "llm_vision_enabled": os.environ.get("EZ_IMAGE_PROTECTION_LLM_VISION", "").strip().lower() in {"1", "true", "yes", "on"},
    "detector_enabled": True,
    "prompt_signals_enabled": os.environ.get("EZ_IMAGE_PROTECTION_PROMPT_SIGNALS", "").strip().lower() in {"1", "true", "yes", "on"},
    "visual_fallback_enabled": os.environ.get("EZ_IMAGE_PROTECTION_VISUAL_FALLBACK", "1").strip().lower() in {"1", "true", "yes", "on"},
    "llm_vision_review_passes": 3,
    "llm_vision_protect_votes": 2,
    "classifier_threshold": 0.68,
    "detector_threshold": 0.45,
    "paired_breast_threshold": _DETECTOR_PAIRED_BREAST_THRESHOLD,
    "buttocks_threshold": _DETECTOR_BUTTOCKS_THRESHOLD,
    "weak_breast_prompt_threshold": _DETECTOR_WEAK_BREAST_PROMPT_THRESHOLD,
    "prompt_context_enabled": True,
    "strong_prompt_skin_threshold": _STRONG_PROMPT_SKIN_THRESHOLD,
    "strong_nude_skin_threshold": _STRONG_NUDE_SKIN_THRESHOLD,
    "nsfw_risk_skin_threshold": _NSFW_RISK_SKIN_THRESHOLD,
    "visual_intimate_skin_threshold": _VISUAL_INTIMATE_SKIN_THRESHOLD,
    "prompt_patterns": dict(_PROMPT_PATTERN_DEFAULTS),
}
_PROMPT_REGEX_CACHE: dict[str, tuple[str, re.Pattern[str]]] = {}
_SPECIFIC_SEXUAL_EVIDENCE_RE = re.compile(
    r"\bnipples?\b|\bareolae?\b|\blabia\b|\bvulva\b|\bpenis\b|\bscrotum\b|\btesticles?\b|\banus\b|"
    r"\berection\b|\bintercourse\b|\bpenetration\b|\boral\s+sex\b|\bsemen\b|\bejaculat(?:e|ion)\b|"
    r"乳头|乳晕|阴唇|外阴|阴茎|睾丸|肛门|勃起|性交|插入|精液",
    re.IGNORECASE,
)


def _settings_snapshot() -> dict[str, Any]:
    with _SETTINGS_LOCK:
        settings = dict(_RUNTIME_SETTINGS)
        settings["prompt_patterns"] = dict(_RUNTIME_SETTINGS.get("prompt_patterns") or {})
    return settings


def get_image_protection_settings() -> dict[str, Any]:
    """Return current runtime settings for admin display."""
    return _settings_snapshot()


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _coerce_threshold(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _coerce_int(value: Any, default: int, minimum: int = 1, maximum: int = 5) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def configure_image_protection(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Merge validated settings into the resident image-protection runtime."""
    incoming = settings or {}
    with _SETTINGS_LOCK:
        current = dict(_RUNTIME_SETTINGS)
        current["prompt_patterns"] = dict(_RUNTIME_SETTINGS.get("prompt_patterns") or {})
        for key in (
            "enabled",
            "llm_vision_enabled",
            "detector_enabled",
            "prompt_signals_enabled",
            "visual_fallback_enabled",
            "prompt_context_enabled",
        ):
            if key in incoming:
                current[key] = _coerce_bool(incoming.get(key), bool(current.get(key)))
        for key in (
            "classifier_threshold",
            "detector_threshold",
            "paired_breast_threshold",
            "buttocks_threshold",
            "weak_breast_prompt_threshold",
            "strong_prompt_skin_threshold",
            "strong_nude_skin_threshold",
            "nsfw_risk_skin_threshold",
            "visual_intimate_skin_threshold",
        ):
            if key in incoming:
                current[key] = _coerce_threshold(incoming.get(key), float(current.get(key, 0)))
        if "llm_vision_review_passes" in incoming:
            current["llm_vision_review_passes"] = _coerce_int(incoming.get("llm_vision_review_passes"), 3, 1, 5)
        if "llm_vision_protect_votes" in incoming:
            current["llm_vision_protect_votes"] = _coerce_int(incoming.get("llm_vision_protect_votes"), 2, 1, 5)
        current["llm_vision_protect_votes"] = min(
            int(current.get("llm_vision_review_passes") or 1),
            int(current.get("llm_vision_protect_votes") or 1),
        )
        patterns = incoming.get("prompt_patterns")
        if isinstance(patterns, dict):
            for name, value in patterns.items():
                if name in _PROMPT_PATTERN_DEFAULTS:
                    current["prompt_patterns"][name] = str(value or _PROMPT_PATTERN_DEFAULTS[name])
        _RUNTIME_SETTINGS.clear()
        _RUNTIME_SETTINGS.update(current)
        _PROMPT_REGEX_CACHE.clear()
    return get_image_protection_settings()


def _setting_bool(key: str, default: bool) -> bool:
    return _coerce_bool(_settings_snapshot().get(key), default)


def _setting_threshold(key: str, default: float) -> float:
    return _coerce_threshold(_settings_snapshot().get(key), default)


def _setting_int(key: str, default: int, minimum: int = 1, maximum: int = 5) -> int:
    return _coerce_int(_settings_snapshot().get(key), default, minimum, maximum)


def _runtime_prompt_re(name: str, fallback: re.Pattern[str]) -> re.Pattern[str]:
    settings = _settings_snapshot()
    patterns = settings.get("prompt_patterns") or {}
    pattern = str(patterns.get(name) or _PROMPT_PATTERN_DEFAULTS.get(name) or "")
    cached = _PROMPT_REGEX_CACHE.get(name)
    if cached and cached[0] == pattern:
        return cached[1]
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = fallback
    _PROMPT_REGEX_CACHE[name] = (pattern, compiled)
    return compiled


def prompt_needs_protection(prompt: str) -> bool:
    """Return whether legacy prompt text would have triggered preview protection."""
    return bool(_runtime_prompt_re("hard", _PROMPT_RE).search(prompt or ""))


def prompt_has_nsfw_risk(prompt: str) -> bool:
    """Return whether prompt text has NSFW-risk phrasing that needs visual confirmation."""
    return bool(_runtime_prompt_re("risk", _NSFW_RISK_PROMPT_RE).search(prompt or ""))


def prompt_has_strong_nude_intent(prompt: str) -> bool:
    """Return whether prompt explicitly asks for nude/full-nude content."""
    return bool(_runtime_prompt_re("strong_nude", _STRONG_NUDE_PROMPT_RE).search(prompt or ""))


def prompt_has_obscene_gesture(prompt: str) -> bool:
    """Return whether prompt text requests an obscene gesture."""
    return bool(_runtime_prompt_re("obscene_gesture", _OBSCENE_GESTURE_RE).search(prompt or ""))


def prompt_has_violence_gore(prompt: str) -> bool:
    """Return whether prompt text requests visible violence or gore."""
    return bool(_runtime_prompt_re("violence", _VIOLENCE_PROMPT_RE).search(prompt or ""))


def prompt_protection_enabled() -> bool:
    """Return whether prompt text can independently trigger protection."""
    return _setting_bool("prompt_signals_enabled", False)


@dataclass
class ImageProtectionResult:
    status: str
    score: float
    reason: str
    source: str


class ImageProtectionWorker:
    """Lazy resident classifier wrapper with a local heuristic fallback."""

    def __init__(
        self,
        load_detector: Callable[[], Any] | None = None,
        load_classifier: Callable[[], Any] | None = None,
        load_vision_reviewer: Callable[[], Any] | None = None,
        threshold: float | None = None,
        detector_threshold: float | None = None,
    ) -> None:
        self._load_detector = load_detector or self._load_default_detector
        self._load_classifier = load_classifier or self._load_default_classifier
        self._load_vision_reviewer = load_vision_reviewer or self._load_default_vision_reviewer
        self._detector: Any = None
        self._classifier: Any = None
        self._vision_reviewer: Any = None
        self._detector_loaded = False
        self._loaded = False
        self._vision_loaded = False
        self._lock = threading.Lock()
        self._threshold = float(threshold if threshold is not None else os.environ.get("EZ_IMAGE_PROTECTION_THRESHOLD", "0.68"))
        self._detector_threshold = float(
            detector_threshold if detector_threshold is not None else os.environ.get("EZ_IMAGE_PROTECTION_DETECTOR_THRESHOLD", "0.45")
        )

    def check(self, image_path: str, prompt: str = "") -> ImageProtectionResult:
        if not image_path or not os.path.isfile(image_path):
            return ImageProtectionResult("error", 1.0, "missing image", "local-error")
        if not _setting_bool("enabled", True):
            return ImageProtectionResult("safe", 1.0, "image protection disabled", "settings")
        with self._lock:
            prompt_result = self._prompt_rule_result(prompt)
            if _setting_bool("llm_vision_enabled", False):
                reviewer = self._vision_reviewer_once()
                if reviewer is not None:
                    try:
                        result = self._review_with_llm_vision(reviewer, image_path, prompt)
                        if result is not None:
                            if result.status == "protected":
                                return result
                            if prompt_result is not None:
                                return prompt_result
                            return result
                    except Exception as exc:
                        return ImageProtectionResult("error", 1.0, f"llm vision failed: {exc}", "llm-vision")
            if prompt_result is not None:
                return prompt_result
            detector = self._detector_once() if _setting_bool("detector_enabled", True) else None
            detector_available = detector is not None
            if detector_available:
                try:
                    result = self._detect_with_detector(detector, image_path, prompt)
                    if result is not None and result.status == "protected":
                        return result
                except Exception as exc:
                    return ImageProtectionResult("error", 1.0, f"detector failed: {exc}", "detector")
            classifier = self._classifier_once()
            if classifier is not None:
                try:
                    result = self._classify_with_model(classifier, image_path)
                    if result is not None and result.status == "protected":
                        return result
                except Exception as exc:
                    return ImageProtectionResult("error", 1.0, f"classifier failed: {exc}", "classifier")
            visual_fallback = _setting_bool("visual_fallback_enabled", True)
            return self._heuristic_check(image_path, prompt, prompt_fallback=not detector_available, visual_fallback=visual_fallback)

    def _prompt_rule_result(self, prompt: str) -> ImageProtectionResult | None:
        if not prompt_protection_enabled():
            return None
        if prompt_has_obscene_gesture(prompt):
            return ImageProtectionResult("protected", 0.76, "obscene gesture prompt", "prompt")
        if prompt_has_violence_gore(prompt):
            return ImageProtectionResult("protected", 0.82, "violence/gore prompt", "prompt")
        if prompt_has_strong_nude_intent(prompt):
            return ImageProtectionResult("protected", 0.80, "strong nude prompt", "prompt")
        if prompt_needs_protection(prompt):
            return ImageProtectionResult("protected", 0.78, "explicit sexual prompt", "prompt")
        if prompt_has_nsfw_risk(prompt):
            return ImageProtectionResult("protected", 0.74, "nsfw-risk prompt", "prompt")
        return None

    def _detector_once(self) -> Any:
        if self._detector_loaded:
            return self._detector
        self._detector_loaded = True
        try:
            self._detector = self._load_detector()
        except Exception:
            self._detector = None
        return self._detector

    def _classifier_once(self) -> Any:
        if self._loaded:
            return self._classifier
        self._loaded = True
        try:
            self._classifier = self._load_classifier()
        except Exception:
            self._classifier = None
        return self._classifier

    def _vision_reviewer_once(self) -> Any:
        if self._vision_loaded:
            return self._vision_reviewer
        self._vision_loaded = True
        try:
            self._vision_reviewer = self._load_vision_reviewer()
        except Exception:
            self._vision_reviewer = None
        return self._vision_reviewer

    def _load_default_classifier(self) -> Any:
        model_path = os.environ.get("EZ_IMAGE_PROTECTION_MODEL", "").strip()
        if not model_path:
            return None
        from transformers import pipeline

        return pipeline("image-classification", model=model_path, local_files_only=True)

    def _load_default_detector(self) -> Any:
        mode = os.environ.get("EZ_IMAGE_PROTECTION_DETECTOR", "ifnude").strip().lower()
        if mode in {"", "0", "false", "off", "none", "disabled"}:
            return None
        try:
            from ifnude import detector as ifnude_detector
            return _ResidentIfNudeDetector(ifnude_detector)
        except Exception:
            return None

    def _load_default_vision_reviewer(self) -> Any:
        return _default_llm_vision_reviewer

    def _review_with_llm_vision(self, reviewer: Any, image_path: str, prompt: str = "") -> ImageProtectionResult | None:
        passes = _setting_int("llm_vision_review_passes", 3, 1, 5)
        required_votes = min(passes, _setting_int("llm_vision_protect_votes", 2, 1, 5))
        results: list[ImageProtectionResult] = []
        prompts = (
            _LLM_VISION_REVIEW_PROMPT,
            _LLM_VISION_REVIEW_PROMPT_STRICT,
            _LLM_VISION_REVIEW_PROMPT_ADJUDICATOR,
        )
        for index in range(passes):
            raw = self._call_vision_review_pass(reviewer, image_path, prompt, prompts[min(index, len(prompts) - 1)], index)
            result = raw if isinstance(raw, ImageProtectionResult) else _coerce_llm_vision_result(raw)
            if result is not None:
                results.append(result)
        if not results:
            return None
        protected_results = [result for result in results if result.status == "protected"]
        if len(protected_results) >= required_votes:
            best = max(protected_results, key=lambda item: item.score)
            return ImageProtectionResult(
                "protected",
                best.score,
                f"llm vision consensus {len(protected_results)}/{len(results)}: {best.reason}"[:240],
                "llm-vision",
            )
        best_safe = max(results, key=lambda item: item.score)
        if protected_results:
            reason = f"llm vision protected vote disputed {len(protected_results)}/{len(results)}: {best_safe.reason}"
        else:
            reason = f"llm vision consensus 0/{len(results)}: {best_safe.reason}"
        return ImageProtectionResult("safe", best_safe.score, reason[:240], "llm-vision")

    def _call_vision_review_pass(
        self,
        reviewer: Any,
        image_path: str,
        prompt: str,
        review_prompt: str,
        index: int,
    ) -> Any:
        if reviewer is _default_llm_vision_reviewer:
            return _default_llm_vision_reviewer(image_path, prompt if index == 0 else "", review_prompt=review_prompt)
        return reviewer(image_path, prompt)

    def _detect_with_detector(self, detector: Any, image_path: str, prompt: str = "") -> ImageProtectionResult | None:
        raw = detector(image_path, mode="fast") if _call_accepts_fast_mode(detector) else detector(image_path)
        entries = list(_flatten_detector_output(raw, image_path))
        if not entries:
            return ImageProtectionResult("safe", 1.0, "detector no exposed parts", "detector")
        detector_threshold = _setting_threshold("detector_threshold", self._detector_threshold)
        paired_threshold = _setting_threshold("paired_breast_threshold", _DETECTOR_PAIRED_BREAST_THRESHOLD)
        paired_breast = _paired_exposed_breast_score(entries, detector_threshold)
        if paired_breast >= paired_threshold:
            return ImageProtectionResult(
                "protected",
                paired_breast,
                f"detector paired EXPOSED_BREAST_F score={paired_breast:.3f}",
                "detector",
            )
        buttocks_score = _best_detector_label_score(entries, "EXPOSED_BUTTOCKS")
        buttocks_threshold = _setting_threshold("buttocks_threshold", _DETECTOR_BUTTOCKS_THRESHOLD)
        if buttocks_score >= buttocks_threshold:
            return ImageProtectionResult(
                "protected",
                buttocks_score,
                f"detector EXPOSED_BUTTOCKS score={buttocks_score:.3f}",
                "detector",
            )
        weak_breast_score = _best_detector_label_score(entries, "EXPOSED_BREAST_F")
        weak_breast_threshold = _setting_threshold("weak_breast_prompt_threshold", _DETECTOR_WEAK_BREAST_PROMPT_THRESHOLD)
        if (
            _setting_bool("prompt_context_enabled", True)
            and weak_breast_score >= weak_breast_threshold
            and (prompt_needs_protection(prompt) or prompt_has_nsfw_risk(prompt))
        ):
            return ImageProtectionResult(
                "protected",
                weak_breast_score,
                f"detector weak EXPOSED_BREAST_F score={weak_breast_score:.3f} with prompt risk",
                "detector",
            )
        best_label = ""
        best_score = 0.0
        for entry in entries:
            label = str(entry.get("label", "") or entry.get("class", "") or entry.get("name", ""))
            score = _clamp_score(entry.get("score", entry.get("confidence", entry.get("probability", 0))))
            if not _detector_label_requires_protection(label):
                continue
            if score >= detector_threshold and score >= best_score:
                best_score = score
                best_label = label
        if best_label:
            return ImageProtectionResult("protected", best_score, f"detector {best_label} score={best_score:.3f}", "detector")
        return ImageProtectionResult("safe", 1.0, "detector no protected exposed parts", "detector")

    def _classify_with_model(self, classifier: Any, image_path: str) -> ImageProtectionResult | None:
        try:
            from PIL import Image, ImageOps
        except Exception:
            return None
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((384, 384))
            raw = classifier(img)
        entries = list(_flatten_classifier_output(raw))
        if not entries:
            return None
        unsafe = 0.0
        safe = 0.0
        top_label = ""
        for entry in entries:
            label = str(entry.get("label", "") or entry.get("class", ""))
            score = _clamp_score(entry.get("score", entry.get("probability", 0)))
            if score > unsafe and _UNSAFE_LABEL_RE.search(label):
                unsafe = score
                top_label = label
            if _SAFE_LABEL_RE.search(label):
                safe = max(safe, score)
        threshold = _setting_threshold("classifier_threshold", self._threshold)
        status = "protected" if unsafe >= threshold and unsafe >= safe else "safe"
        score = unsafe if status == "protected" else max(0.0, 1.0 - unsafe)
        reason = f"{top_label or 'classifier'} score={unsafe:.3f}"
        return ImageProtectionResult(status, score, reason, "classifier")

    def _heuristic_check(
        self,
        image_path: str,
        prompt: str,
        prompt_fallback: bool = True,
        visual_fallback: bool = True,
    ) -> ImageProtectionResult:
        prompt_hit = prompt_needs_protection(prompt)
        nsfw_risk_hit = prompt_has_nsfw_risk(prompt)
        strong_nude_hit = prompt_has_strong_nude_intent(prompt)
        gesture_hit = prompt_has_obscene_gesture(prompt)
        skin_ratio = 0.0
        try:
            from PIL import Image, ImageOps
            with Image.open(image_path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((96, 96))
                pixels = list(img.getdata())
            if pixels:
                skin_like = 0
                for r, g, b in pixels:
                    mx = max(r, g, b)
                    mn = min(r, g, b)
                    if r > 95 and g > 40 and b > 20 and (mx - mn) > 15 and r > g and r > b:
                        skin_like += 1
                skin_ratio = skin_like / len(pixels)
        except Exception as exc:
            return ImageProtectionResult("error", 1.0, f"heuristic failed: {exc}", "heuristic")
        if prompt_protection_enabled():
            if gesture_hit:
                return ImageProtectionResult("protected", 0.76, "obscene gesture prompt", "prompt")
            if strong_nude_hit:
                return ImageProtectionResult("protected", 0.78, "strong nude prompt", "prompt")
            if prompt_hit and skin_ratio >= _setting_threshold("strong_prompt_skin_threshold", _STRONG_PROMPT_SKIN_THRESHOLD):
                return ImageProtectionResult("protected", max(0.76, skin_ratio), f"prompt signal with skin_ratio={skin_ratio:.3f}", "prompt")
            if prompt_fallback and nsfw_risk_hit and skin_ratio >= _setting_threshold("nsfw_risk_skin_threshold", _NSFW_RISK_SKIN_THRESHOLD):
                return ImageProtectionResult("protected", max(0.76, skin_ratio), f"nsfw-risk prompt with skin_ratio={skin_ratio:.3f}", "prompt")
        visual_signal, visual_reason = _visual_intimate_signal(image_path, skin_ratio) if visual_fallback else (False, "")
        if visual_signal:
            return ImageProtectionResult("protected", max(0.74, skin_ratio), visual_reason, "heuristic")
        return ImageProtectionResult("safe", max(0.0, 1.0 - skin_ratio), f"local heuristic skin_ratio={skin_ratio:.3f}", "heuristic")


def _flatten_classifier_output(raw: Any) -> Iterable[dict]:
    if isinstance(raw, dict):
        yield raw
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
            elif isinstance(item, list):
                yield from _flatten_classifier_output(item)


def _default_llm_vision_reviewer(
    image_path: str,
    prompt: str = "",
    review_prompt: str = _LLM_VISION_REVIEW_PROMPT,
) -> dict[str, Any]:
    data_url = image_to_data_url(image_path)
    user_text = review_prompt
    if prompt:
        user_text += "\n\nGeneration prompt for context only:\n" + str(prompt)[:1200]
    raw = chat_text(
        [
            {
                "role": "system",
                "content": DIRECT_FINAL_SYSTEM_PROMPT + " Return only one valid JSON object. Do not output markdown.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        temperature=0.02,
        max_tokens=320,
        response_format={"type": "json_object"},
    )
    return _extract_llm_review_json(raw)


def _extract_llm_review_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_llm_vision_result(raw: Any) -> ImageProtectionResult | None:
    data = _extract_llm_review_json(raw)
    if not data:
        return None
    protected = _coerce_bool(data.get("protected"), False)
    sexual_visible = _coerce_bool(data.get("sexual_visible"), False)
    violent_visible = _coerce_bool(data.get("violent_visible"), False)
    confidence = _clamp_score(data.get("confidence", 0.0))
    reason = str(data.get("reason") or "").strip()
    sexual_text = " ".join(
        str(data.get(key) or "")
        for key in ("sexual_findings", "reason", "visible_parts", "evidence")
    )
    if sexual_visible and not _SPECIFIC_SEXUAL_EVIDENCE_RE.search(sexual_text):
        sexual_visible = False
        protected = violent_visible
        reason = "llm sexual flag ignored because no specific visible protected anatomy evidence: " + (reason or "generic sexual finding")
    if not reason:
        labels = []
        if sexual_visible:
            labels.append("sexual content visible")
        if violent_visible:
            labels.append("violent/gory content visible")
        reason = ", ".join(labels) or "llm vision review"
    visible_violation = sexual_visible or violent_visible
    if visible_violation:
        return ImageProtectionResult("protected", max(0.74, confidence), reason[:240], "llm-vision")
    if protected:
        reason = "llm protected flag ignored because sexual_visible=false and violent_visible=false: " + reason
    return ImageProtectionResult("safe", max(0.0, 1.0 - confidence), reason[:240] or "llm vision safe", "llm-vision")


def _flatten_detector_output(raw: Any, image_path: str = "") -> Iterable[dict]:
    if isinstance(raw, dict):
        if image_path and isinstance(raw.get(image_path), list):
            yield from _flatten_detector_output(raw.get(image_path), image_path)
            return
        if any(key in raw for key in ("label", "class", "name")):
            yield raw
            return
        for value in raw.values():
            if isinstance(value, (list, dict)):
                yield from _flatten_detector_output(value, image_path)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield from _flatten_detector_output(item, image_path)
            elif isinstance(item, list):
                yield from _flatten_detector_output(item, image_path)


def _detector_label_requires_protection(label: str) -> bool:
    normalized = (label or "").replace("-", "_").replace(" ", "_")
    if not normalized or _DETECTOR_IGNORE_LABEL_RE.search(normalized):
        return False
    return bool(_DETECTOR_PROTECT_LABEL_RE.search(normalized))


def _paired_exposed_breast_score(entries: list[dict], detector_threshold: float) -> float:
    scores = []
    for entry in entries:
        label = str(entry.get("label", "") or entry.get("class", "") or entry.get("name", ""))
        normalized = label.replace("-", "_").replace(" ", "_").upper()
        if normalized != "EXPOSED_BREAST_F":
            continue
        score = _clamp_score(entry.get("score", entry.get("confidence", entry.get("probability", 0))))
        if score >= detector_threshold:
            scores.append(score)
    if len(scores) < 2:
        return 0.0
    scores.sort(reverse=True)
    return min(scores[0], scores[1])


def _best_detector_label_score(entries: list[dict], expected_label: str) -> float:
    expected = expected_label.replace("-", "_").replace(" ", "_").upper()
    best = 0.0
    for entry in entries:
        label = str(entry.get("label", "") or entry.get("class", "") or entry.get("name", ""))
        normalized = label.replace("-", "_").replace(" ", "_").upper()
        if normalized != expected:
            continue
        best = max(best, _clamp_score(entry.get("score", entry.get("confidence", entry.get("probability", 0)))))
    return best


def _call_accepts_fast_mode(callable_obj: Any) -> bool:
    try:
        import inspect
        signature = inspect.signature(callable_obj)
    except Exception:
        return False
    return "mode" in signature.parameters


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _visual_intimate_signal(image_path: str, skin_ratio: float) -> tuple[bool, str]:
    """Detect narrow visual-only intimate markers without treating skin alone as unsafe."""
    if skin_ratio < _setting_threshold("visual_intimate_skin_threshold", _VISUAL_INTIMATE_SKIN_THRESHOLD):
        return False, ""
    try:
        from PIL import Image, ImageOps
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((220, 220))
            width, height = img.size
            pixels = list(img.getdata())
    except Exception:
        return False, ""
    if not pixels or width < 24 or height < 24:
        return False, ""

    skin_mask: list[bool] = []
    marker_mask: list[bool] = []
    for r, g, b in pixels:
        mx = max(r, g, b)
        mn = min(r, g, b)
        skin_mask.append(r > 90 and g > 35 and b > 18 and (mx - mn) > 12 and r > g * 0.95 and r > b * 1.05)
        marker_mask.append(
            70 < r < 190
            and 30 < g < 150
            and 20 < b < 135
            and r > g * 1.04
            and r > b * 1.08
            and (r - g) > 6
            and (r - b) > 12
            and (mx - mn) > 16
        )

    face_box = _detect_face_box_scaled(image_path, width, height)
    candidates = _visual_marker_components(width, height, skin_mask, marker_mask, face_box)
    if face_box:
        _fx, _fy, fw, _fh = face_box
        strong_candidates = [component for component in candidates if component[0] >= 48]
        if fw / max(1, width) <= 0.50 and _has_paired_visual_markers(strong_candidates, width, height):
            return True, f"visual intimate markers={len(candidates)} skin_ratio={skin_ratio:.3f}"
        return False, ""
    paired = _has_paired_visual_markers(candidates, width, height)
    if paired:
        return True, f"visual paired intimate markers skin_ratio={skin_ratio:.3f}"
    return False, ""


def _detect_face_box(image_path: str) -> tuple[float, float, float, float] | None:
    try:
        import cv2
        image = cv2.imread(image_path)
        if image is None:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda face: int(face[2]) * int(face[3]))
        return float(x), float(y), float(w), float(h)
    except Exception:
        return None


def _detect_face_box_scaled(image_path: str, target_width: int, target_height: int) -> tuple[float, float, float, float] | None:
    try:
        import cv2
        image = cv2.imread(image_path)
        if image is None:
            return None
        original_height, original_width = image.shape[:2]
        if original_width <= 0 or original_height <= 0:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda face: int(face[2]) * int(face[3]))
        sx = target_width / max(1.0, float(original_width))
        sy = target_height / max(1.0, float(original_height))
        return float(x) * sx, float(y) * sy, float(w) * sx, float(h) * sy
    except Exception:
        return None


def _visual_marker_components(
    width: int,
    height: int,
    skin_mask: list[bool],
    marker_mask: list[bool],
    face_box: tuple[float, float, float, float] | None,
) -> list[tuple[int, float, float]]:
    mask = [False] * (width * height)
    for idx, marked in enumerate(marker_mask):
        if not marked:
            continue
        x = idx % width
        y = idx // width
        xn = x / max(1, width)
        yn = y / max(1, height)
        if face_box:
            fx, fy, fw, fh = face_box
            if y < fy + fh * 1.45:
                continue
            if not (fx - fw * 0.75 <= x <= fx + fw * 1.75):
                continue
            if yn > 0.74:
                continue
        else:
            if not (0.18 <= xn <= 0.82 and 0.28 <= yn <= 0.64):
                continue
        if _skin_fraction(width, height, skin_mask, x - 8, x + 9, y - 8, y + 9) >= 0.50:
            mask[idx] = True

    seen = [False] * len(mask)
    components: list[tuple[int, float, float]] = []
    for idx, marked in enumerate(mask):
        if not marked or seen[idx]:
            continue
        stack = [idx]
        seen[idx] = True
        points: list[int] = []
        while stack:
            current = stack.pop()
            points.append(current)
            x = current % width
            y = current // width
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    next_idx = ny * width + nx
                    if mask[next_idx] and not seen[next_idx]:
                        seen[next_idx] = True
                        stack.append(next_idx)
        if 4 <= len(points) <= 180:
            cx = sum(point % width for point in points) / len(points)
            cy = sum(point // width for point in points) / len(points)
            components.append((len(points), cx, cy))
    return components


def _has_paired_visual_markers(components: list[tuple[int, float, float]], width: int, height: int) -> bool:
    for idx, first in enumerate(components):
        _area1, x1, y1 = first
        for _area2, x2, y2 in components[idx + 1:]:
            if abs(x1 - x2) / max(1, width) >= 0.20 and abs(y1 - y2) / max(1, height) <= 0.16:
                return True
    return False


def _skin_fraction(
    width: int,
    height: int,
    skin_mask: list[bool],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> float:
    total = 0
    skin = 0
    for y in range(max(0, int(y0)), min(height, int(y1))):
        for x in range(max(0, int(x0)), min(width, int(x1))):
            total += 1
            if skin_mask[y * width + x]:
                skin += 1
    return skin / total if total else 0.0


class _ResidentIfNudeDetector:
    """Keep ifnude's ONNX session resident instead of rebuilding it per image."""

    def __init__(self, ifnude_detector_module: Any) -> None:
        self._module = ifnude_detector_module
        self._session = ifnude_detector_module.onnxruntime.InferenceSession(
            ifnude_detector_module.model_path,
            providers=["CPUExecutionProvider"],
        )

    def __call__(self, image_path: str, mode: str = "fast") -> list[dict]:
        min_side = 480 if mode == "fast" else 800
        max_side = 800 if mode == "fast" else 1333
        min_prob = 0.5 if mode == "fast" else 0.6
        image, scale = self._module.preprocess_image(image_path, min_side=min_side, max_side=max_side)
        outputs = self._session.run(
            [output.name for output in self._session.get_outputs()],
            {self._session.get_inputs()[0].name: self._module.np.expand_dims(image, axis=0)},
        )
        labels = [item for item in outputs if item.dtype == "int32"][0]
        scores = [item for item in outputs if isinstance(item[0][0], self._module.np.float32)][0]
        boxes = [item for item in outputs if isinstance(item[0][0], self._module.np.ndarray)][0]
        boxes /= scale
        results: list[dict] = []
        for box, score, label in zip(boxes[0], scores[0], labels[0]):
            score_value = float(score)
            if score_value < min_prob:
                continue
            class_name = self._module.classes[label]
            if class_name == "EXPOSED_BELLY":
                continue
            results.append({"box": box.astype(int).tolist(), "score": score_value, "label": class_name})
        return results
