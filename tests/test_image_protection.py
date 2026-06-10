import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image


class ImageProtectionWorkerTests(unittest.TestCase):
    def test_detector_exposed_genitalia_is_loaded_once_and_returns_protected(self):
        from modules.image_protection import ImageProtectionWorker

        calls = {"load": 0, "detect": 0}

        def load_detector():
            calls["load"] += 1

            def detect(_path):
                calls["detect"] += 1
                return [{"label": "EXPOSED_GENITALIA_F", "score": 0.82, "box": [10, 20, 30, 40]}]

            return detect

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            first = worker.check(path, prompt="")
            second = worker.check(path, prompt="")

        self.assertEqual(calls["load"], 1)
        self.assertEqual(calls["detect"], 2)
        self.assertEqual(first.status, "protected")
        self.assertEqual(second.status, "protected")
        self.assertEqual(first.source, "detector")
        self.assertIn("EXPOSED_GENITALIA_F", first.reason)

    def test_visual_face_box_scaling_uses_target_thumbnail_dimensions(self):
        from modules import image_protection

        source = Path(image_protection.__file__).read_text("utf-8")

        self.assertIn("def _detect_face_box_scaled", source)
        self.assertIn("target_width / max(1.0, float(original_width))", source)
        self.assertIn("target_height / max(1.0, float(original_height))", source)
        self.assertNotIn("fx + fw + max(fx, 0.0)", source)

    def test_visual_fallback_runs_when_detector_misses(self):
        from modules import image_protection
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        old_visual = image_protection._visual_intimate_signal
        configure_image_protection({"visual_fallback_enabled": True, "prompt_signals_enabled": False})
        try:
            image_protection._visual_intimate_signal = lambda _path, _skin_ratio: (True, "synthetic visual miss")
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "detector-miss.jpg")
                Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
                worker = ImageProtectionWorker(load_detector=lambda: (lambda _path: []), load_classifier=lambda: None)

                result = worker.check(path, prompt="")
        finally:
            image_protection._visual_intimate_signal = old_visual
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "heuristic")
        self.assertIn("synthetic visual miss", result.reason)

    def test_visual_fallback_default_is_enabled_for_detector_misses(self):
        from modules import image_protection

        source = Path(image_protection.__file__).read_text("utf-8")

        self.assertIn('os.environ.get("EZ_IMAGE_PROTECTION_VISUAL_FALLBACK", "1")', source)
        self.assertIn('visual_fallback = _setting_bool("visual_fallback_enabled", True)', source)
        self.assertNotIn('not detector_available\n                and _setting_bool("visual_fallback_enabled", False)', source)

    def test_startup_backfill_does_not_run_llm_vision_review(self):
        app_py = (Path(__file__).resolve().parents[1] / "app.py").read_text("utf-8")
        for name in (
            "_backfill_legacy_prompt_protection",
            "_recheck_safe_heuristic_nsfw_risk_rows",
            "_recheck_safe_heuristic_video_rows",
        ):
            start = app_py.index("def " + name)
            end = app_py.find("\ndef ", start + 1)
            body = app_py[start:end if end != -1 else len(app_py)]
            self.assertIn("load_vision_reviewer=lambda: None", body)

    def test_llm_vision_review_protects_visible_erotic_or_violent_content(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })
        calls = {"review": 0}

        def load_vision_reviewer():
            def review(_path, _prompt):
                calls["review"] += 1
                return {
                    "protected": True,
                    "sexual_visible": False,
                    "violent_visible": True,
                    "confidence": 0.91,
                    "reason": "graphic blood and severe injury visible",
                }

            return review

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "violent.jpg")
                Image.new("RGB", (48, 48), (20, 20, 20)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(calls["review"], 3)
        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("consensus 3/3", result.reason)
        self.assertIn("severe injury", result.reason)

    def test_llm_vision_safe_result_does_not_protect_skin_area_alone(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.88,
                "reason": "non-sexual skin exposure only",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "skin-area.jpg")
                Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "llm-vision")

    def test_llm_vision_contradictory_protected_flag_is_ignored_when_no_visible_violation(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": True,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.98,
                "violence_level": "none",
                "sexual_findings": "No nipples, areolae, genitals, anus, or sexual acts are visible.",
                "violence_findings": "No blood, gore, or injury visible.",
                "reason": "Safe image with ordinary non-sexual skin exposure.",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "contradictory-safe.jpg")
                Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("protected flag ignored", result.reason)

    def test_llm_vision_single_protected_vote_is_disputed_safe(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "llm_vision_review_passes": 3,
            "llm_vision_protect_votes": 2,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })
        reviews = iter([
            {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.95,
                "reason": "ambiguous low-angle view claims visible nipple",
            },
            {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.95,
                "reason": "underwear only, no protected anatomy visible",
            },
            {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.93,
                "reason": "covered underwear and ordinary skin exposure only",
            },
        ])

        def load_vision_reviewer():
            return lambda _path, _prompt: next(reviews)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "disputed.jpg")
                Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("protected vote disputed 1/3", result.reason)

    def test_llm_vision_generic_pubic_region_claim_without_specific_evidence_is_safe(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "llm_vision_review_passes": 3,
            "llm_vision_protect_votes": 2,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })
        reviews = iter([
            {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.95,
                "sexual_findings": "pubic region and genitals are claimed visible",
                "reason": "low-angle view reveals pubic region and genitals",
            },
            {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.92,
                "sexual_findings": "covered crotch area under thong, no exact anatomical feature named",
                "reason": "generic genital exposure claim",
            },
            {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.9,
                "reason": "underwear only",
            },
        ])

        def load_vision_reviewer():
            return lambda _path, _prompt: next(reviews)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "generic-pubic.jpg")
                Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("consensus 0/3", result.reason)

    def test_llm_vision_negative_sexual_act_phrase_is_not_specific_evidence(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "llm_vision_review_passes": 1,
            "llm_vision_protect_votes": 1,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.9,
                "sexual_findings": "covered underwear; no sexual acts or sexual fluids are visible",
                "reason": "generic sexual flag with no concrete anatomy evidence",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "negative-acts.jpg")
                Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertIn("no specific visible protected anatomy evidence", result.reason)

    def test_llm_vision_two_protected_votes_are_consensus_protected(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "llm_vision_review_passes": 3,
            "llm_vision_protect_votes": 2,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })
        reviews = iter([
            {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.91,
                "reason": "visible nipple exposure through sheer fabric",
            },
            {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.82,
                "reason": "second pass uncertain",
            },
            {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.94,
                "reason": "visible areola exposure confirmed",
            },
        ])

        def load_vision_reviewer():
            return lambda _path, _prompt: next(reviews)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "consensus.jpg")
                Image.new("RGB", (48, 48), (180, 120, 110)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("consensus 2/3", result.reason)

    def test_llm_vision_safe_result_still_protects_when_prompt_matches(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": False,
            "prompt_signals_enabled": True,
            "visual_fallback_enabled": False,
        })

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.91,
                "reason": "no visible sexual exposure or gore",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "prompt-hit.jpg")
                Image.new("RGB", (48, 48), (8, 10, 12)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="人物露出乳头和性器官，写实肖像")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "prompt")
        self.assertIn("explicit sexual prompt", result.reason)

    def test_llm_vision_and_prompt_both_safe_allows_image(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": False,
            "prompt_signals_enabled": True,
            "visual_fallback_enabled": False,
        })

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.94,
                "reason": "ordinary pet dog, no sexual exposure or gore visible",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "pet-dog.jpg")
                Image.new("RGB", (48, 48), (120, 90, 70)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="一只可爱小狗坐在草地上")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "llm-vision")

    def test_llm_vision_safe_result_overrides_detector_pet_false_positive(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": True,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_GENITALIA_F", "score": 0.99}]

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": False,
                "sexual_visible": False,
                "violent_visible": False,
                "confidence": 0.93,
                "reason": "ordinary pet dog, no sexual exposure or gore visible",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "pet-dog.jpg")
                Image.new("RGB", (48, 48), (120, 90, 70)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=load_detector,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("pet dog", result.reason)

    def test_llm_vision_protects_sheer_fabric_visible_nipple_exposure(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": True,
            "detector_enabled": False,
            "prompt_signals_enabled": False,
            "visual_fallback_enabled": False,
        })

        def load_vision_reviewer():
            return lambda _path, _prompt: {
                "protected": True,
                "sexual_visible": True,
                "violent_visible": False,
                "confidence": 0.9,
                "sexual_findings": "areola and nipple visible through transparent fabric",
                "reason": "visible nipple exposure through sheer clothing",
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "sheer.jpg")
                Image.new("RGB", (48, 48), (180, 130, 120)).save(path)
                worker = ImageProtectionWorker(
                    load_detector=lambda: None,
                    load_classifier=lambda: None,
                    load_vision_reviewer=load_vision_reviewer,
                )

                result = worker.check(path, prompt="半透明薄纱材质")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "llm-vision")
        self.assertIn("nipple", result.reason.lower())

    def test_prompt_protection_blocks_violence_gore_prompt(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({
            "llm_vision_enabled": False,
            "detector_enabled": False,
            "prompt_signals_enabled": True,
            "visual_fallback_enabled": False,
        })
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "gore.jpg")
                Image.new("RGB", (48, 48), (8, 10, 12)).save(path)
                worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

                result = worker.check(path, prompt="graphic gore, exposed organs, severe injury")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "prompt")
        self.assertIn("violence/gore", result.reason)

    def test_llm_vision_review_prompt_excludes_skin_area_policy(self):
        from modules import image_protection

        self.assertIn("Do not judge skin exposure area by itself", image_protection._LLM_VISION_REVIEW_PROMPT)
        self.assertIn("Ordinary pets, cats, dogs", image_protection._LLM_VISION_REVIEW_PROMPT)
        self.assertIn("transparent, translucent, see-through", image_protection._LLM_VISION_REVIEW_PROMPT)
        self.assertIn("violence_level string", image_protection._LLM_VISION_REVIEW_PROMPT)
        self.assertIn("violence/gore", image_protection._LLM_VISION_REVIEW_PROMPT)
        self.assertIn("protected field MUST be true if and only if", image_protection._LLM_VISION_REVIEW_PROMPT)
        self.assertIn("underwear, thong, bare back", image_protection._LLM_VISION_REVIEW_PROMPT)

    def test_detector_exposed_breast_label_without_three_points_is_safe(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_BREAST_F", "score": 0.92, "box": [10, 20, 30, 40]}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "covered-breast-shape.jpg")
            Image.new("RGB", (48, 48), (170, 32, 24)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="")

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "heuristic")

    def test_detector_paired_high_confidence_exposed_breast_labels_are_protected(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [
                {"label": "EXPOSED_BREAST_F", "score": 0.86, "box": [10, 20, 30, 40]},
                {"label": "EXPOSED_BREAST_F", "score": 0.82, "box": [40, 20, 60, 40]},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paired-exposed-breast.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="")

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "detector")
        self.assertIn("paired EXPOSED_BREAST_F", result.reason)

    def test_detector_paired_low_confidence_exposed_breast_labels_stay_safe(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [
                {"label": "EXPOSED_BREAST_F", "score": 0.72, "box": [10, 20, 30, 40]},
                {"label": "EXPOSED_BREAST_F", "score": 0.51, "box": [40, 20, 60, 40]},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paired-covered-breast-shape.jpg")
            Image.new("RGB", (48, 48), (170, 32, 24)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="")

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "heuristic")

    def test_detector_high_confidence_buttocks_is_protected_for_back_view_nude(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_BUTTOCKS", "score": 0.81, "box": [10, 20, 30, 40]}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "back-view-nude.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="")

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "detector")
        self.assertIn("EXPOSED_BUTTOCKS", result.reason)

    def test_detector_weak_exposed_breast_with_prompt_risk_is_protected(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_BREAST_F", "score": 0.54, "box": [10, 20, 30, 40]}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "weak-exposed-breast.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="湿漉半透明的衬衫透出胸部和乳头，NFSW")

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "detector")
        self.assertIn("prompt risk", result.reason)

    def test_detector_weak_exposed_breast_without_prompt_risk_stays_safe(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_BREAST_F", "score": 0.54, "box": [10, 20, 30, 40]}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "weak-covered-breast-shape.jpg")
            Image.new("RGB", (48, 48), (170, 32, 24)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="红色机甲胸甲，正面半身")

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "heuristic")

    def test_detector_safe_result_prevents_prompt_only_protection(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [{"label": "FACE_FEMALE", "score": 0.99}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(24):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="没有衣服，移除所有衣物")

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "heuristic")
        self.assertIn("skin_ratio", result.reason)

    def test_obscene_gesture_prompt_does_not_apply_when_prompt_protection_is_off(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: []

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gesture.jpg")
            Image.new("RGB", (48, 48), (8, 10, 12)).save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="替换手势为竖中指")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)

    def test_fake_classifier_is_loaded_once_and_returns_protected(self):
        from modules.image_protection import ImageProtectionWorker

        calls = {"load": 0, "classify": 0}

        class FakeClassifier:
            def __call__(self, image):
                calls["classify"] += 1
                return [{"label": "nsfw", "score": 0.91}]

        def load_classifier():
            calls["load"] += 1
            return FakeClassifier()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=load_classifier)

            first = worker.check(path, prompt="")
            second = worker.check(path, prompt="")

        self.assertEqual(calls["load"], 1)
        self.assertEqual(calls["classify"], 2)
        self.assertEqual(first.status, "protected")
        self.assertEqual(second.status, "protected")
        self.assertGreaterEqual(first.score, 0.9)
        self.assertEqual(first.source, "classifier")

    def test_missing_image_fails_closed_as_protected_error(self):
        from modules.image_protection import ImageProtectionWorker

        result = ImageProtectionWorker(load_classifier=lambda: None).check("/missing/nope.jpg", prompt="")

        self.assertEqual(result.status, "error")
        self.assertGreaterEqual(result.score, 1.0)
        self.assertIn("missing", result.reason.lower())

    def test_explicit_three_points_prompt_with_skin_signal_is_safe_when_prompt_protection_is_off(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "portrait.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(24):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

            result = worker.check(path, prompt="人物露出乳头和性器官，写实肖像")

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "heuristic")
        self.assertIn("skin_ratio", result.reason)

    def test_explicit_three_points_prompt_without_image_skin_signal_is_not_enough(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dark.jpg")
            Image.new("RGB", (48, 48), (8, 10, 12)).save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

            result = worker.check(path, prompt="露出乳头和性器官，写实肖像")

        self.assertEqual(result.status, "safe")

    def test_prompt_protection_can_be_enabled_for_temporary_fallback(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({"prompt_signals_enabled": True})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "portrait.jpg")
                img = Image.new("RGB", (48, 48), (8, 10, 12))
                for x in range(24):
                    for y in range(48):
                        img.putpixel((x, y), (230, 180, 160))
                img.save(path)
                worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

                result = worker.check(path, prompt="人物露出乳头和性器官，写实肖像")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "prompt")
        self.assertIn("explicit sexual prompt", result.reason)

    def test_enabled_prompt_protection_blocks_strong_nude_prompt_even_with_low_skin_signal(self):
        from modules.image_protection import ImageProtectionWorker, configure_image_protection, get_image_protection_settings

        old_settings = get_image_protection_settings()
        configure_image_protection({"prompt_signals_enabled": True})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "low-skin.jpg")
                Image.new("RGB", (48, 48), (8, 10, 12)).save(path)
                worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

                result = worker.check(path, prompt="保持画面任务一致，让人物保持裸体")
        finally:
            configure_image_protection(old_settings)

        self.assertEqual(result.status, "protected")
        self.assertEqual(result.source, "prompt")
        self.assertIn("strong nude prompt", result.reason)

    def test_no_clothes_prompt_with_skin_signal_is_safe_when_prompt_protection_is_off(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-clothes.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(24):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

            result = worker.check(path, prompt="去除所有衣服，没有衣服，不穿衣服")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)

    def test_english_no_clothes_prompt_with_skin_signal_is_safe_when_prompt_protection_is_off(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-clothes-en.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(24):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

            result = worker.check(path, prompt="remove all clothes, no clothes")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)

    def test_chinese_nude_prompt_with_skin_signal_is_safe_when_prompt_protection_is_off(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nude-zh.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(24):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

            result = worker.check(path, prompt="全身裸体，裸体，一丝不挂")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)

    def test_chinese_full_nude_prompt_with_skin_signal_is_safe_when_detector_is_safe(self):
        from modules.image_protection import ImageProtectionWorker

        def load_detector():
            return lambda _path: [{"label": "FACE_FEMALE", "score": 0.99}]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "full-nude-zh.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(10, 30):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)

            result = worker.check(path, prompt="全裸，裸体，全身裸体")

        self.assertEqual(result.status, "safe")
        self.assertEqual(result.source, "heuristic")
        self.assertIn("skin_ratio", result.reason)

    def test_chinese_no_clothing_prompt_with_skin_signal_is_safe_when_prompt_protection_is_off(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "no-clothing-zh.jpg")
            img = Image.new("RGB", (48, 48), (8, 10, 12))
            for x in range(24):
                for y in range(48):
                    img.putpixel((x, y), (230, 180, 160))
            img.save(path)
            worker = ImageProtectionWorker(load_detector=lambda: None, load_classifier=lambda: None)

            result = worker.check(path, prompt="年轻女性，佩戴项链，无衣物，移除所有衣物")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)

    def test_high_skin_signal_without_nsfw_text_is_not_enough(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "portrait.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_classifier=lambda: None)

            result = worker.check(path, prompt="写实肖像，露肩连衣裙，自然光")

        self.assertEqual(result.status, "safe")

    def test_breast_or_topless_prompt_without_three_points_is_safe(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "topless.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            worker = ImageProtectionWorker(load_classifier=lambda: None)

            result = worker.check(path, prompt="露出乳房，上身裸露，topless portrait")

        self.assertEqual(result.status, "safe")

    def test_obscene_gesture_prompt_is_safe_without_prompt_protection(self):
        from modules.image_protection import ImageProtectionWorker

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gesture.jpg")
            Image.new("RGB", (48, 48), (8, 10, 12)).save(path)
            worker = ImageProtectionWorker(load_classifier=lambda: None)

            result = worker.check(path, prompt="替换手势为竖中指")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)

    def test_reported_prompt_examples_follow_visual_context_mode(self):
        from modules.image_protection import ImageProtectionWorker

        examples = [
            ("1ec621fd/2026-05-10/20260510_192404_a41130_thumb.jpg", "着装改成裸露，裸体。 nfsw"),
            ("7ac22882/2026-05-19/t2i-z-image_0009_thumb.jpg", "NFSW，上半身裸露，透出胸部和乳头"),
            ("1ec621fd/2026-05-20/i2i-Qwen-Edit-v2511_0006_thumb.jpg", "替换手势为竖中指，粉色极小比基尼。"),
        ]
        root = os.path.join(os.getcwd(), "data", "outputs")
        missing = [rel for rel, _prompt in examples if not os.path.isfile(os.path.join(root, rel))]
        if missing:
            self.skipTest("reported image fixtures not available: " + ", ".join(missing))
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        results = [(rel, worker.check(os.path.join(root, rel), prompt)) for rel, prompt in examples]

        self.assertEqual(results[0][1].status, "protected")
        self.assertEqual(results[1][1].status, "safe")
        self.assertEqual(results[2][1].status, "safe")

    def test_reported_visual_only_exposed_breast_points_example_is_protected(self):
        from modules.image_protection import ImageProtectionWorker

        rel = "1ec621fd/2026-05-08/20260508_100700_19dee3_thumb.jpg"
        path = os.path.join(os.getcwd(), "data", "outputs", rel)
        if not os.path.isfile(path):
            self.skipTest("reported image fixture not available: " + rel)
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        result = worker.check(path, prompt="")

        self.assertEqual(result.status, "protected")
        self.assertIn(result.source, {"detector", "heuristic"})

    def test_high_skin_safe_face_fixture_remains_safe(self):
        from modules.image_protection import ImageProtectionWorker

        rel = "1ec621fd/2026-05-22/i2i-Qwen-SeedVR2_0001_thumb.jpg"
        path = os.path.join(os.getcwd(), "data", "outputs", rel)
        if not os.path.isfile(path):
            self.skipTest("safe face fixture not available: " + rel)
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        result = worker.check(path, prompt="")

        self.assertEqual(result.status, "safe")

    def test_latest_i2i_paired_exposed_breast_fixtures_are_protected(self):
        from modules.image_protection import ImageProtectionWorker

        rels = [
            "1ec621fd/2026-05-22/i2i-FireRed-Edit-8step_0005_thumb.jpg",
            "1ec621fd/2026-05-22/i2i-FireRed-Edit-8step_0004_thumb.jpg",
        ]
        root = os.path.join(os.getcwd(), "data", "outputs")
        missing = [rel for rel in rels if not os.path.isfile(os.path.join(root, rel))]
        if missing:
            self.skipTest("latest i2i fixtures not available: " + ", ".join(missing))
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        results = [(rel, worker.check(os.path.join(root, rel), "")) for rel in rels]

        self.assertEqual(
            [(rel, result.status, result.reason) for rel, result in results if result.status != "protected"],
            [],
        )

    def test_latest_soft_nude_prompt_exposed_breast_fixtures_are_protected(self):
        from modules.image_protection import ImageProtectionWorker

        rels = [
            "1ec621fd/2026-05-22/t2i-z-image_0005_thumb.jpg",
            "1ec621fd/2026-05-22/t2i-z-image_0004_thumb.jpg",
            "1ec621fd/2026-05-22/t2i-z-image_0003_thumb.jpg",
        ]
        root = os.path.join(os.getcwd(), "data", "outputs")
        missing = [rel for rel in rels if not os.path.isfile(os.path.join(root, rel))]
        if missing:
            self.skipTest("latest soft nude fixtures not available: " + ", ".join(missing))
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        results = [(rel, worker.check(os.path.join(root, rel), "")) for rel in rels]

        self.assertEqual(
            [(rel, result.status, result.reason) for rel, result in results if result.status != "protected"],
            [],
        )

    def test_current_reported_nude_and_exposed_point_fixtures_are_protected(self):
        from modules.image_protection import ImageProtectionWorker

        examples = [
            ("7ac22882/2026-05-19/t2i-z-image_0009.png", "NFSW，上半身裸露，透出胸部和乳头"),
            ("7ac22882/2026-05-19/t2i-z-image_0005_thumb.jpg", "NFSW，上半身裸露，透出胸部和乳头"),
            ("1ec621fd/2026-05-08/20260508_114938_47ad81_thumb.jpg", "全裸的站在街头卖气球。背对着镜头站立。正背面。"),
            ("1ec621fd/2026-05-08/20260508_114800_bbe177_thumb.jpg", "全裸的站在街头卖气球。背对着镜头站立。"),
            ("1ec621fd/2026-05-08/20260508_114539_7ff39f_thumb.jpg", "全裸的站在街头卖气球。背对着镜头站立。"),
            ("1ec621fd/2026-05-07/20260507_225819_bd6689_thumb.jpg", "NFSW，无内衣，湿漉半透明的衬衫透出胸部和乳头"),
        ]
        root = os.path.join(os.getcwd(), "data", "outputs")
        missing = [rel for rel, _prompt in examples if not os.path.isfile(os.path.join(root, rel))]
        if missing:
            self.skipTest("current reported fixtures not available: " + ", ".join(missing))
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        results = [(rel, worker.check(os.path.join(root, rel), prompt)) for rel, prompt in examples]

        self.assertEqual(
            [(rel, result.status, result.reason) for rel, result in results if result.status != "protected"],
            [],
        )

    def test_uploaded_safe_examples_remain_safe(self):
        from modules.image_protection import ImageProtectionWorker

        paths = [
            "/tmp/codex-remote-attachments/019e4ef0-b808-7562-8e42-4d7133d89beb/47AADAF3-3C52-491C-B430-219616C2382F/1-照片-1.jpg",
            "/tmp/codex-remote-attachments/019e4ef0-b808-7562-8e42-4d7133d89beb/47AADAF3-3C52-491C-B430-219616C2382F/2-照片-2.jpg",
            "/tmp/codex-remote-attachments/019e4ef0-b808-7562-8e42-4d7133d89beb/47AADAF3-3C52-491C-B430-219616C2382F/3-照片-3.jpg",
        ]
        missing = [path for path in paths if not os.path.isfile(path)]
        if missing:
            self.skipTest("uploaded safe fixtures not available")
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        results = [(path, worker.check(path, "")) for path in paths]

        self.assertEqual(
            [(path, result.status, result.reason) for path, result in results if result.status != "safe"],
            [],
        )

    def test_lollipop_video_thumbnail_without_three_points_remains_safe(self):
        from modules.image_protection import ImageProtectionWorker

        rel = "1ec621fd/2026-05-23/i2v_ltx23_sulphur_0001_thumb.jpg"
        path = os.path.join(os.getcwd(), "data", "outputs", rel)
        if not os.path.isfile(path):
            self.skipTest("lollipop video thumbnail fixture not available: " + rel)
        worker = ImageProtectionWorker(load_classifier=lambda: None)

        result = worker.check(path, "美美的吃着棒棒糖，然后甜美的看着镜头。")

        self.assertEqual(result.status, "safe")
        self.assertIn("skin_ratio", result.reason)


if __name__ == "__main__":
    unittest.main()
