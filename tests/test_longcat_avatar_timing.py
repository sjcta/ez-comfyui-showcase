import unittest
from unittest import mock

import app


def _workflow(duration=0, fps=25.0):
    return {
        "3": {"class_type": "LoadAudio", "inputs": {"audio": "u1/voice.wav"}},
        "4": {"class_type": "TrimAudioDuration", "inputs": {"duration": duration}},
        "6": {"class_type": "LongCatAvatarWhisperEmbeds", "inputs": {"num_frames": 81, "fps": fps}},
        "13": {"class_type": "WanVideoLongCatAvatarExtendEmbeds", "inputs": {"num_frames": 81}},
        "17": {"class_type": "VHS_VideoCombine", "inputs": {"frame_rate": fps}},
    }


class LongCatAvatarTimingTests(unittest.TestCase):
    def test_zero_duration_auto_matches_uploaded_audio(self):
        wf = _workflow(duration=0, fps=25)
        fields = {"3::audio": "u1/voice.wav", "4::duration": 0, "6::fps": 25}

        with mock.patch.object(app, "_safe_comfy_input_path", return_value="/tmp/voice.wav"):
            with mock.patch.object(app.os.path, "isfile", return_value=True):
                with mock.patch.object(app, "_probe_audio_duration_seconds", return_value=4.0):
                    normalized = app._normalize_workflow_field_values(wf, fields, "longcat_avatar15_q4_smoke.json")

        self.assertEqual(normalized["4::duration"], 4.04)
        self.assertEqual(normalized["6::num_frames"], 101)
        self.assertEqual(normalized["13::num_frames"], 101)
        self.assertEqual(normalized["17::frame_rate"], 25.0)
        self.assertEqual(normalized["__longcat_timing_mode"], "audio_auto")

    def test_manual_duration_overrides_audio_duration(self):
        wf = _workflow(duration=0, fps=24)
        fields = {"3::audio": "u1/voice.wav", "4::duration": 2.0, "6::fps": 24}

        with mock.patch.object(app, "_safe_comfy_input_path", return_value="/tmp/voice.wav"):
            with mock.patch.object(app.os.path, "isfile", return_value=True):
                with mock.patch.object(app, "_probe_audio_duration_seconds", return_value=6.0):
                    normalized = app._normalize_workflow_field_values(wf, fields, "longcat_avatar15_q4_smoke.json")

        self.assertEqual(normalized["4::duration"], 2.042)
        self.assertEqual(normalized["6::num_frames"], 49)
        self.assertEqual(normalized["13::num_frames"], 49)
        self.assertEqual(normalized["17::frame_rate"], 24.0)
        self.assertEqual(normalized["__longcat_timing_mode"], "manual")

    def test_long_audio_is_capped_by_node_frame_limit(self):
        wf = _workflow(duration=0, fps=25)
        fields = {"3::audio": "u1/voice.wav", "4::duration": 0, "6::fps": 25}

        with mock.patch.object(app, "_safe_comfy_input_path", return_value="/tmp/voice.wav"):
            with mock.patch.object(app.os.path, "isfile", return_value=True):
                with mock.patch.object(app, "_probe_audio_duration_seconds", return_value=11.6115):
                    normalized = app._normalize_workflow_field_values(wf, fields, "longcat_avatar15_q4_smoke.json")

        self.assertEqual(normalized["4::duration"], 10.12)
        self.assertEqual(normalized["6::num_frames"], 253)
        self.assertEqual(normalized["13::num_frames"], 253)
        self.assertEqual(normalized["__longcat_frame_cap"], 253)


if __name__ == "__main__":
    unittest.main()
