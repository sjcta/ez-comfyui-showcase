import asyncio
import unittest

from modules.instance_picker import pick_best_instance, strict_preferred_instance_name


def _instances():
    return [
        {"name": "A", "url": "http://127.0.0.1:8190", "sort_order": 1},
        {"name": "B", "url": "http://127.0.0.1:8189", "sort_order": 2},
    ]


class InstancePickerTest(unittest.TestCase):
    def _pick(self, workflow, loads=None, groups=None):
        loads = loads or {}
        groups = groups or {}
        return asyncio.run(
            pick_best_instance(
                instances=_instances(),
                workflow_name=workflow,
                queue_size_getter=lambda inst: loads.get(inst["name"], 0),
                group_getter=lambda name: groups.get(name, ""),
            )
        )

    def test_i2i_prefers_b_when_instances_are_idle(self):
        picked = self._pick("i2i-FireRed-Edit-1.1.json")
        self.assertEqual(picked["name"], "B")

    def test_i2i_stays_on_b_even_when_b_has_queue_to_keep_lane_stable(self):
        picked = self._pick("i2i-FireRed-Edit-1.1.json", {"B": 1})
        self.assertEqual(picked["name"], "B")

    def test_i2i_keeps_b_even_when_b_queue_is_deeper(self):
        picked = self._pick("i2i-FireRed-Edit-1.1.json", {"B": 2})
        self.assertEqual(picked["name"], "B")

    def test_t2i_prefers_a_when_instances_are_idle(self):
        picked = self._pick("t2i-nunchaku.json")
        self.assertEqual(picked["name"], "A")

    def test_t2i_keeps_a_even_when_a_has_queue(self):
        picked = self._pick("t2i-nunchaku.json", {"A": 1, "B": 0})
        self.assertEqual(picked["name"], "A")

    def test_upscale_prefers_a(self):
        picked = self._pick("SeedVR2_upscale_4k.json", {"A": 1, "B": 0})
        self.assertEqual(picked["name"], "A")

    def test_strict_preferred_instance_keeps_retry_on_i2i_lane(self):
        self.assertEqual(strict_preferred_instance_name("i2i-FireRed-Edit-8step.json"), "B")

    def test_strict_preferred_instance_keeps_retry_on_t2i_lane(self):
        self.assertEqual(strict_preferred_instance_name("t2i-z-image.json"), "A")

    def test_matching_loaded_group_can_break_tie(self):
        picked = self._pick(
            "other-nunchaku.json",
            {"A": 1, "B": 1},
            {"B": "nunchaku"},
        )
        self.assertEqual(picked["name"], "B")

    def test_flux2_klein_t2i_and_i2i_share_model_group(self):
        picked = self._pick(
            "i2i_flux2_klein.json",
            {"A": 0, "B": 0},
            {"A": "flux2-klein"},
        )

        self.assertEqual(picked["name"], "A")

    def test_flux2_dev_variants_share_model_group(self):
        picked = self._pick(
            "t2i_flux2_dev_q6k.json",
            {"A": 0, "B": 0},
            {"B": "flux2-dev"},
        )

        self.assertEqual(picked["name"], "B")


if __name__ == "__main__":
    unittest.main()
