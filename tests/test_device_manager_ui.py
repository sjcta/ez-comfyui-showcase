from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeviceManagerUiContractTests(unittest.TestCase):
    def test_desktop_device_cards_do_not_reserve_empty_grid_columns(self):
        css = (ROOT / "static/css/style.css").read_text()

        container_rule = re.search(r"#deviceListContainer\s*\{[^}]+\}", css, re.S)
        self.assertIsNotNone(container_rule)
        self.assertIn("repeat(auto-fit, minmax(min(100%, 520px), 1fr))", container_rule.group(0))
        self.assertNotIn("repeat(auto-fill, minmax(340px, 1fr))", container_rule.group(0))

    def test_device_card_width_is_desktop_bounded_and_mobile_fluid(self):
        css = (ROOT / "static/css/style.css").read_text()

        desktop_rule = re.search(r"\.device-card\s*\{[^}]+max-width:\s*760px;[^}]+\}", css, re.S)
        self.assertIsNotNone(desktop_rule)
        self.assertIn("width: 100%", desktop_rule.group(0))

        self.assertIn("#deviceListContainer { grid-template-columns: 1fr; }", css)
        self.assertIn(".device-card { max-width: none; }", css)


if __name__ == "__main__":
    unittest.main()
