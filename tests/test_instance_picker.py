import asyncio
import unittest

from modules.instance_picker import pick_best_instance


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

    def test_i2i_stays_on_b_for_short_b_queue_to_protect_vram_lane(self):
        picked = self._pick("i2i-FireRed-Edit-1.1.json", {"B": 1})
        self.assertEqual(picked["name"], "B")

    def test_i2i_can_spill_to_idle_a_when_b_queue_is_too_deep(self):
        picked = self._pick("i2i-FireRed-Edit-1.1.json", {"B": 2})
        self.assertEqual(picked["name"], "A")

    def test_t2i_spills_to_idle_b_when_a_is_busy(self):
        picked = self._pick("t2i-nunchaku.json", {"A": 1, "B": 0})
        self.assertEqual(picked["name"], "B")

    def test_matching_loaded_group_can_break_tie(self):
        picked = self._pick(
            "t2i-nunchaku.json",
            {"A": 1, "B": 1},
            {"B": "nunchaku"},
        )
        self.assertEqual(picked["name"], "B")


if __name__ == "__main__":
    unittest.main()
