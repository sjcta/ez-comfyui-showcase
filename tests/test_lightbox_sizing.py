import pathlib
import re
import unittest


class LightboxSizingTest(unittest.TestCase):
    def test_mobile_lightbox_pinch_does_not_trigger_navigation(self):
        app_js = pathlib.Path("static/js/app.js").read_text()

        self.assertIn("function suppressLightboxNav(ms)", app_js)
        self.assertIn("function isLightboxNavSuppressed()", app_js)
        self.assertIn("e.touches.length > 1", app_js)
        self.assertIn("suppressLightboxNav(800)", app_js)
        self.assertIn("resetLightboxSwipeStart();", app_js)
        self.assertIn("e.target.closest('.lb-nav')", app_js)
        self.assertIn("e.stopImmediatePropagation();", app_js)
        self.assertIn("touchmove", app_js)
        self.assertIn("touchcancel", app_js)

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

    def test_lightbox_exposes_click_toggle_image_compare_for_i2i_history(self):
        js = pathlib.Path("static/js/modules/history.js").read_text()
        css = pathlib.Path("static/css/style.css").read_text()
        html = pathlib.Path("static/index.html").read_text()
        sprite = pathlib.Path("static/icons/sprite.svg").read_text()

        self.assertIn('id="lbCompareBtn"', html)
        self.assertIn("图片对比", html)
        self.assertIn('class="lb-action-btn lb-compare"', html)
        self.assertIn("lb-compare-icon", html)
        self.assertIn('href="#icon-compare"', html)
        self.assertIn('id="icon-compare"', sprite)
        self.assertIn('fill="currentColor" stroke="none"', sprite)
        self.assertIn('<path d="M20 11v2"/>', sprite)
        self.assertIn("onclick=\"if(window.CW&&CW.toggleLBCompareImage)", html)
        self.assertNotIn("onmouseenter=\"if(window.CW&&CW.showLBOriginalImage)", html)
        self.assertNotIn("onpointerdown=\"if(window.CW&&CW.showLBOriginalImage)", html)
        self.assertIn("function _historyOriginalImageRef", js)
        self.assertIn("function _syncLightboxCompare", js)
        self.assertIn("function showLBOriginalImage", js)
        self.assertIn("function restoreLBGeneratedImage", js)
        self.assertIn("function toggleLBCompareImage", js)
        self.assertIn("/api/input-image/", js)
        self.assertIn("_syncLightboxCompare(h)", js)
        self.assertIn("window.CW.toggleLBCompareImage = toggleLBCompareImage", js)
        self.assertNotIn("lb-action-row", html)
        self.assertNotIn(".lb-action-row", css)
        self.assertRegex(css, r"\.lb-compare\s*\{[^}]*left:\s*max\(24px,\s*env\(safe-area-inset-left\)\)", re.S)
        self.assertRegex(css, r"\.lb-compare\s*\{[^}]*bottom:\s*calc\(max\(24px,\s*env\(safe-area-inset-bottom\)\)\s*\+\s*72px\)", re.S)
        self.assertRegex(css, r"\.lb-compare\.is-active\s*\{[^}]*color:\s*#f59e0b", re.S)

    def test_lightbox_favorite_share_hide_stack_below_delete(self):
        css = pathlib.Path("static/css/style.css").read_text()
        html = pathlib.Path("static/index.html").read_text()

        self.assertLess(html.index('id="lbDeleteBtn"'), html.index('id="lbActions"'))
        self.assertLess(html.index('id="lbFavoriteBtn"'), html.index('id="lbImageShareHomeBtn"'))
        self.assertLess(html.index('id="lbImageShareHomeBtn"'), html.index('id="lbHideBtn"'))
        self.assertLess(html.index('id="lbHideBtn"'), html.index('id="lbShareBtn"'))
        self.assertLess(html.index('id="lbShareBtn"'), html.index('id="lbDownload"'))
        self.assertLess(html.index('id="lbActions"'), html.index('id="lbDownload"'))
        self.assertRegex(css, r"\.lb-actions\s*\{[^}]*left:\s*max\(24px,\s*env\(safe-area-inset-left\)\)", re.S)
        self.assertRegex(css, r"\.lb-actions\s*\{[^}]*top:\s*68px", re.S)
        self.assertRegex(css, r"\.lb-actions\s*\{[^}]*flex-direction:\s*column", re.S)
        self.assertRegex(css, r"\.lb-hide\s*\{[^}]*position:\s*static", re.S)
        self.assertRegex(css, r"\.lb-download\s*\{[^}]*right:\s*max\(24px,\s*env\(safe-area-inset-right\)\)", re.S)
        self.assertRegex(css, r"\.lb-download\s*\{[^}]*bottom:\s*calc\(max\(24px,\s*env\(safe-area-inset-bottom\)\)\s*\+\s*72px\)", re.S)
        self.assertRegex(css, r"\.lb-image-export-wrap\s*\{[^}]*right:\s*max\(24px,\s*env\(safe-area-inset-right\)\)", re.S)
        self.assertRegex(css, r"\.lb-image-export-wrap\s*\{[^}]*bottom:\s*calc\(max\(24px,\s*env\(safe-area-inset-bottom\)\)\s*\+\s*124px\)", re.S)

    def test_lightbox_exposes_permission_gated_delete_action_on_left_axis(self):
        js = pathlib.Path("static/js/modules/history.js").read_text()
        css = pathlib.Path("static/css/style.css").read_text()
        html = pathlib.Path("static/index.html").read_text()

        self.assertIn('id="lbDeleteBtn"', html)
        self.assertIn('class="lb-action-btn lb-delete"', html)
        self.assertIn('href="#icon-trash-2"', html)
        self.assertIn("deleteCurrentLightboxItem", html)
        self.assertIn("var deleteBtn = $('#lbDeleteBtn')", js)
        self.assertIn("actionState.canDelete", js)
        self.assertIn("deleteBtn.dataset.historyId", js)
        self.assertIn("function deleteCurrentLightboxItem", js)
        self.assertIn("await delHist(id)", js)
        self.assertIn("renderLB();", js)
        self.assertIn("return { ok: true, deletedIds: deleteIds }", js)
        self.assertIn("window.CW.deleteCurrentLightboxItem = deleteCurrentLightboxItem", js)
        self.assertRegex(css, r"\.lb-delete\s*\{[^}]*left:\s*max\(24px,\s*env\(safe-area-inset-left\)\)", re.S)
        self.assertRegex(css, r"\.lb-delete\s*\{[^}]*top:\s*16px", re.S)
        self.assertIn(".lb-delete {\n    left: max(16px, env(safe-area-inset-left));\n  }", css)

    def test_lightbox_share_button_opens_image_export_menu(self):
        js = pathlib.Path("static/js/modules/history.js").read_text()
        css = pathlib.Path("static/css/style.css").read_text()
        html = pathlib.Path("static/index.html").read_text()

        self.assertIn('id="lbImageExportMenu"', html)
        self.assertIn('class="lb-action-btn lb-share lb-image-export-toggle"', html)
        self.assertIn('href="#icon-upload"', html)
        self.assertIn('href="#icon-edit"', html)
        self.assertIn('href="#icon-video"', html)
        self.assertIn('href="#icon-scaleup"', html)
        self.assertIn("CW.toggleLBImageExportMenu", html)
        self.assertIn("importLBImage('图生图', event)", html)
        self.assertIn("importLBImage('视频制作', event)", html)
        self.assertIn("importLBImage('放大', event)", html)
        self.assertIn('id="lbImageShareHomeBtn"', html)
        self.assertIn("CW.toggleLBShareHome", html)
        self.assertIn("function toggleLBImageExportMenu", js)
        self.assertIn("function _requestLightboxImageInput", js)
        self.assertIn("API + '/api/upload-image'", js)
        self.assertIn("function importLBImage(typeText, e)", js)
        self.assertIn("_setImportedReferenceImage(data.filename)", js)
        self.assertIn("window.CW.importLBImage = importLBImage", js)
        self.assertIn("window.CW.toggleLBShareHome = toggleLBShareHome", js)
        self.assertIn(".lb-image-export-menu", css)
        self.assertRegex(css, r"\.lb-image-export-menu\s*\{[^}]*right:\s*calc\(100%\s*\+\s*8px\)", re.S)

    def test_lightbox_hide_action_uses_visible_eye_default_and_hidden_eye_off_state(self):
        js = pathlib.Path("static/js/modules/history.js").read_text()
        css = pathlib.Path("static/css/style.css").read_text()
        html = pathlib.Path("static/index.html").read_text()

        self.assertIn('id="lbHideBtn"', html)
        self.assertIn('href="#icon-eye"', html)
        self.assertIn("hideIcon.setAttribute('href', isHidden ? '#icon-eye-off' : '#icon-eye')", js)
        self.assertRegex(css, r"\.lb-hide\s*\{[^}]*color:\s*#fff", re.S)
        self.assertRegex(css, r"\.lb-hide\.is-active\s*\{[^}]*color:\s*#050508", re.S)


if __name__ == "__main__":
    unittest.main()
