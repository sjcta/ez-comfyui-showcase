import pathlib
import re
import unittest


class LightboxSizingTest(unittest.TestCase):
    def test_history_lightbox_uses_record_dimensions_to_prevent_preview_jump(self):
        src = pathlib.Path("static/js/modules/history.js").read_text()

        self.assertRegex(src, r"function\s+_lockLightboxDisplaySize\s*\(")
        self.assertIn("lbImg.style.width", src)
        self.assertIn("expectedSize", src)
        self.assertRegex(
            src,
            r"expectedSize:\s*\{\s*width:\s*h\.width\s*\|\|\s*0,\s*height:\s*h\.height\s*\|\|\s*0\s*\}",
            re.S,
        )

    def test_lightbox_uses_blurred_preview_and_fades_in_full_layer(self):
        js = pathlib.Path("static/js/modules/history.js").read_text()
        css = pathlib.Path("static/css/style.css").read_text()
        html = pathlib.Path("static/index.html").read_text()

        self.assertIn('id="lbFullImg"', html)
        self.assertIn('id="lbVideo"', html)
        self.assertIn("function _fadeInLightboxFullImage", js)
        self.assertIn("mediaType", js)
        self.assertIn("fullImg.src = fullSrc", js)
        self.assertIn("fullImg.classList.add('lb-full-visible')", js)
        self.assertIn("lbImg.src = ''", js)
        self.assertIn("function _lockLightboxVideoSize", js)
        self.assertIn("video.onloadedmetadata", js)
        self.assertNotIn("flight.style.filter = 'blur(0px)'", js)
        self.assertIn("flight.style.filter = 'blur(5px)'", js)
        self.assertRegex(css, r"\.lb-flight\s*\{[^}]*filter:\s*blur\(5px\)", re.S)
        self.assertRegex(css, r"#lbImg\.lb-preview\s*\{[^}]*filter:\s*blur\(5px\)", re.S)
        self.assertIn("#lbVideo", css)
        self.assertRegex(css, r"\.lb-stage\.is-video\s+#lbImg,\s*\.lb-stage\.is-video\s+#lbFullImg\s*\{[^}]*display:\s*none", re.S)
        self.assertRegex(css, r"#lbFullImg\s*\{[^}]*opacity:\s*0", re.S)
        self.assertRegex(css, r"#lbFullImg\.lb-full-visible\s*\{[^}]*opacity:\s*1", re.S)

    def test_lightbox_close_defers_image_cleanup_until_after_motion(self):
        js = pathlib.Path("static/js/modules/history.js").read_text()

        self.assertIn("function _cleanupClosedLightbox", js)
        self.assertIn("afterClose: _cleanupClosedLightbox", js)
        close_body = re.search(r"function closeLB\(\)\s*\{(?P<body>.*?)\n  \}", js, re.S)
        self.assertIsNotNone(close_body)
        body = close_body.group("body")
        set_modal_idx = body.index("CW.setModalOpen")
        self.assertNotIn("_resetLightboxFullLayer()", body[:set_modal_idx])
        self.assertNotIn("_clearLightboxDisplaySize()", body[:set_modal_idx])


if __name__ == "__main__":
    unittest.main()
