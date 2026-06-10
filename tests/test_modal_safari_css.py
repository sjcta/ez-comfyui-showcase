from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModalSafariCssContractTests(unittest.TestCase):
    def test_modal_backdrop_uses_stable_pseudo_layer(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".auth-modal-overlay::before", css)
        self.assertIn(".v4-overlay:not(.page)::before", css)
        self.assertIn(".confirm-modal::before", css)
        self.assertIn("background: transparent !important;", css)
        self.assertIn("backdrop-filter: none !important;", css)
        self.assertIn("-webkit-backdrop-filter: none !important;", css)
        self.assertIn(".auth-modal-overlay.open::before", css)
        self.assertIn("will-change: opacity;", css)
        before_block = css[css.index(".v4-overlay:not(.page)::before") : css.index(".v4-overlay.page", css.index(".v4-overlay:not(.page)::before"))]
        self.assertIn("opacity: 1;", before_block)
        self.assertIn("transition: none;", before_block)

    def test_shared_modal_overlay_mask_is_immediate_on_open(self):
        css = (ROOT / "static/css/style.css").read_text()

        open_block = css[css.index(".v4-overlay:not(.page).open") : css.index(".v4-overlay:not(.page).modal-closing")]
        closing_block = css[css.index(".v4-overlay:not(.page).modal-closing") : css.index(".v4-overlay.open::before")]
        self.assertIn(".auth-modal-overlay.open", open_block)
        self.assertIn(".confirm-modal.open", open_block)
        self.assertIn("transition: none;", open_block)
        self.assertIn("opacity 180ms var(--modal-motion-ease)", closing_block)

    def test_modal_cards_use_gpu_stable_transforms(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("transform: translate3d(0, 24px, 0) scale(0.975);", css)
        self.assertIn("-webkit-transform: translate3d(0, 24px, 0) scale(0.975);", css)
        self.assertIn("transform: translate3d(0, 0, 0) scale(1);", css)
        self.assertIn("-webkit-backface-visibility: hidden;", css)

    def test_auth_modal_focus_does_not_trigger_mobile_safari_keyboard_during_open(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()

        self.assertIn("function _shouldAutoFocusAuthInput()", auth_js)
        self.assertIn("(hover: hover) and (pointer: fine)", auth_js)
        self.assertIn("overlay.classList.contains('open')", auth_js)
        self.assertIn("}, 320);", auth_js)

    def test_index_busts_cached_modal_css_and_loader(self):
        index_html = (ROOT / "static/index.html").read_text()
        loader_js = (ROOT / "static/js/module_loader.js").read_text()

        self.assertIn("static/js/module_loader.js?v=1781000019", index_html)
        self.assertIn("var version = '1781000019';", loader_js)


if __name__ == "__main__":
    unittest.main()
