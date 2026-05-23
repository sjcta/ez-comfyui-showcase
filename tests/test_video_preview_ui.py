from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VideoPreviewUiContractTests(unittest.TestCase):
    def test_video_cards_render_video_frame_when_thumbnail_is_missing(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        for src in (history_js, card_manager_js):
            self.assertIn("function _videoPreviewHtml", src)
            self.assertIn("gi-video-preview", src)
            self.assertIn("gi-video-thumb", src)
            self.assertIn("_isVideoItem(item)) return _videoPreviewHtml", src)
            self.assertIn("#t=0.1", src)
            self.assertIn("preload=\"metadata\"", src)

        self.assertIn(".gi-video-preview", css)
        self.assertIn(".gi-video-thumb", css)
        self.assertIn("object-fit: cover", css)

    def test_video_play_mask_covers_full_preview_without_visible_boundary(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".gi-video-preview + .gi-video-poster", css)
        self.assertIn(".gi-video-thumb + .gi-video-poster", css)
        self.assertIn("height: auto;", css)
        self.assertIn("bottom: var(--gi-info-height, 78px);", css)
        self.assertIn("transition: none;", css)
        self.assertNotIn("transition: bottom .22s ease;", css)
        for src in (
            (ROOT / "static/js/modules/history.js").read_text(),
            (ROOT / "static/js/modules/card_manager.js").read_text(),
        ):
            self.assertIn("function _setVideoPreviewMaskHeight", src)
            self.assertIn("ResizeObserver", src)
            self.assertIn("--gi-info-height", src)

    def test_video_cards_do_not_render_redundant_bottom_video_badge(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertNotIn("gi-media-badge\">视频", history_js)
        self.assertNotIn("gi-media-badge'>视频", card_manager_js)

    def test_video_tag_renders_in_card_text_action_row(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()
        sprite = (ROOT / "static/icons/sprite.svg").read_text()

        for src in (history_js, card_manager_js):
            self.assertIn("function _infoVideoTagHtml", src)
            self.assertIn("gi-video-chip", src)
            self.assertIn("icon(\"video\", 16)", src.replace("'", "\""))
            self.assertIn("aria-label=\"视频\"", src)
            self.assertNotIn("<span>视频</span>", src)

        self.assertIn('id="icon-video"', sprite)
        self.assertIn('<symbol id="icon-video" viewBox="0 0 24 24" fill="currentColor" stroke="none">', sprite)
        self.assertIn(".gi-video-chip", css)
        self.assertIn("width: var(--gi-corner-icon-size);", css)
        self.assertIn("height: var(--gi-corner-icon-size);", css)
        self.assertIn("border-radius: 0;", css)
        self.assertIn("width: var(--gi-corner-icon-size);", css)
        self.assertIn("color: #3b82f6;", css)
        self.assertIn("background: transparent;", css)
        self.assertIn("box-shadow: none;", css)
        self.assertIn("justify-content: flex-start;", css)
        self.assertIn("margin-left: auto;", css)

    def test_lightbox_video_autoplays_without_persistent_play_overlay(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _syncLightboxVideoPlayingState", history_js)
        self.assertIn("video.controls = false", history_js)
        self.assertIn("video.playsInline = true", history_js)
        self.assertIn("video.play()", history_js)
        self.assertIn("video.onplay", history_js)
        self.assertIn("video.onpause", history_js)
        self.assertIn("lb-video-playing", history_js)
        self.assertIn(".lb-stage.lb-video-playing", css)

    def test_quick_form_supports_reference_video_upload(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("f.class_type === 'LoadVideo' && f.field === 'file'", generate_js)
        self.assertIn("id=\"refVideoFile\"", generate_js)
        self.assertIn("/api/upload-video", generate_js)
        self.assertIn("/api/input-video/", generate_js)
        self.assertIn("视频放大需要先上传参考视频", generate_js)
        self.assertIn(".video-upload-preview", css)

    def test_seedvr2_video_upscale_uses_long_edge_target(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("function _readVideoFileMetadata", generate_js)
        self.assertIn("function _setRefVideoMetadata", generate_js)
        self.assertIn("function _applyVideoUpscaleLongEdgeResolution", generate_js)
        self.assertIn("Math.min(width, height) / Math.max(width, height)", generate_js)
        self.assertIn("fields[resolutionKey] = computedResolution", generate_js)
        self.assertIn("data-video-width", generate_js)
        self.assertIn("data-video-height", generate_js)


if __name__ == "__main__":
    unittest.main()
