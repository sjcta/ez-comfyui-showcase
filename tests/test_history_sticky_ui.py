from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistoryStickyUiTests(unittest.TestCase):
    def test_history_header_and_filters_stay_sticky_in_center_column(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".col-center > .col-header", css)
        self.assertIn("position: sticky;", css)
        self.assertIn("top: 0;", css)
        self.assertIn(".col-center > .gallery-filters", css)
        self.assertIn("top: var(--history-header-h);", css)
        self.assertIn("--history-header-h: 44px;", css)
        self.assertIn("--history-header-h: 42px;", css)
        self.assertIn("--gallery-filters-h: 41px;", css)
        self.assertIn("--gallery-filters-h: 42px;", css)
        self.assertIn("height: var(--gallery-filters-h);", css)
        self.assertIn("max-height: var(--gallery-filters-h);", css)

    def test_mobile_history_filters_use_compact_horizontal_scroller(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".col-center > .gallery-filters {\n    flex-wrap: nowrap;", css)
        self.assertIn("overflow: visible;", css)
        self.assertIn(".col-center > .gallery-filters .gf-segment {\n    width: auto;", css)
        self.assertIn("flex: 0 0 auto;", css)
        self.assertIn(".col-center > .gallery-filters .gf-segment-btn", css)
        self.assertIn("height: 24px;", css)
        self.assertNotIn("--gallery-filters-h: 86px;", css)

    def test_mobile_history_type_filter_uses_dropdown_menu(self):
        css = (ROOT / "static/css/style.css").read_text()
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertIn(".gf-type-trigger", css)
        self.assertIn(".gf-type-menu", css)
        self.assertIn(".col-center > .gallery-filters .gf-type-segment.open .gf-type-menu", css)
        self.assertIn("position: absolute;", css)
        self.assertIn("flex-direction: column;", css)
        self.assertIn("function _toggleHistoryTypeMenu(e)", history_js)
        self.assertIn("window.CW.toggleHistoryTypeMenu = _toggleHistoryTypeMenu", history_js)
        self.assertIn("function _toggleHistoryTypeMenu(e)", card_manager_js)
        self.assertIn("onclick=\"CW.toggleHistoryTypeMenu(event)\"", history_js)
        self.assertIn("onclick=\"CW.toggleHistoryTypeMenu(event)\"", card_manager_js)

    def test_mobile_workspace_bands_fill_viewport_width(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".workspace { padding: 0; }", css)
        self.assertIn(".col-center { --history-header-h: 42px; --gallery-filters-h: 42px; padding: 0; }", css)
        self.assertNotIn(".workspace { padding: 0 6px; }", css)
        self.assertNotIn(".col-center { --history-header-h: 42px; --gallery-filters-h: 42px; padding: 0 6px; }", css)

    def test_mobile_gallery_cards_keep_side_gutter(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("--history-mobile-gutter: 12px;", css)
        self.assertIn(".masonry { padding: 10px var(--history-mobile-gutter) 14px; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }", css)
        self.assertIn(".col-center > .col-header { padding-left: var(--history-mobile-gutter); padding-right: var(--history-mobile-gutter); }", css)
        self.assertIn(".col-center > .gallery-filters { padding: 5px var(--history-mobile-gutter); }", css)
        self.assertNotIn(".masonry { padding: 6px; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }", css)

    def test_history_filters_match_header_glass_surface(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("--history-glass-bg:", css)
        self.assertGreaterEqual(css.count("background: var(--history-glass-bg);"), 2)
        self.assertGreaterEqual(css.count("backdrop-filter: blur(14px) saturate(1.08);"), 2)
        self.assertGreaterEqual(css.count("-webkit-backdrop-filter: blur(14px) saturate(1.08);"), 2)
        self.assertNotIn(".col-center > .gallery-filters {\n  position: sticky;\n  top: var(--history-header-h);\n  z-index: 31;\n  height: var(--gallery-filters-h);\n  min-height: var(--gallery-filters-h);\n  max-height: var(--gallery-filters-h);\n  flex: 0 0 var(--gallery-filters-h);\n  display: flex;\n  align-items: center;\n  gap: 6px;\n  padding: 5px 10px;\n  flex-shrink: 0;\n  background: var(--bg-base);", css)

    def test_checking_job_status_overlay_is_stable_and_centered(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".gi.job-card.checking .gi-img", css)
        self.assertIn("flex-direction: column;", css)
        self.assertIn(".gi.job-card.checking .job-checking-preview", css)
        self.assertIn("position: absolute;", css)
        self.assertIn(".gi.job-card.checking .job-spinner", css)
        self.assertIn("flex: 0 0 auto;", css)
        self.assertIn(".gi.job-card.checking .job-status-text", css)
        self.assertIn("text-align: center;", css)

    def test_history_has_back_to_top_button_after_one_screen_scroll(self):
        css = (ROOT / "static/css/style.css").read_text()
        index_html = (ROOT / "static/index.html").read_text()
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        sprite_svg = (ROOT / "static/icons/sprite.svg").read_text()

        self.assertIn('id="historyBackTop"', index_html)
        self.assertIn('aria-label="返回顶部"', index_html)
        self.assertIn('onclick="if(window.CW&&CW.scrollHistoryToTop)CW.scrollHistoryToTop()"', index_html)
        self.assertIn('<use href="#icon-arrow-up"/>', index_html)
        self.assertIn('symbol id="icon-arrow-up"', sprite_svg)
        self.assertIn(".history-back-top", css)
        self.assertIn("position: fixed;", css)
        self.assertIn("border-radius: 50%;", css)
        self.assertIn("background: var(--accent);", css)
        self.assertIn(".history-back-top.is-visible", css)
        self.assertIn("function _bindHistoryBackTopButton()", history_js)
        self.assertIn("function _syncHistoryBackTopButton()", history_js)
        self.assertIn("top > Math.max(1, threshold)", history_js)
        self.assertIn("window.CW.scrollHistoryToTop = scrollHistoryToTop", history_js)
        self.assertIn("root.scrollTo({ top: 0, left: 0, behavior: 'smooth' });", history_js)


if __name__ == "__main__":
    unittest.main()
