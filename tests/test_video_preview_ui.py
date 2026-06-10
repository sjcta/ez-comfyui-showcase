from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VideoPreviewUiContractTests(unittest.TestCase):
    def test_video_cards_render_video_frame_when_thumbnail_is_missing(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _videoPreviewHtml", history_js)
        self.assertIn("gi-video-preview", history_js)
        self.assertIn("gi-video-thumb", history_js)
        self.assertIn("_isVideoItem(item)) return _videoPreviewHtml", history_js)
        self.assertIn("#t=0.1", history_js)
        self.assertIn("preload=\"metadata\"", history_js)

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
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        self.assertIn("function _setVideoPreviewMaskHeight", history_js)
        self.assertIn("ResizeObserver", history_js)
        self.assertIn("--gi-info-height", history_js)
        self.assertNotIn("function _setVideoPreviewMaskHeight", card_manager_js)
        self.assertNotIn("ResizeObserver", card_manager_js)

    def test_video_preview_layer_does_not_block_history_lightbox_clicks(self):
        css = (ROOT / "static/css/style.css").read_text()

        block_start = css.index(".gi-video-preview,")
        block_end = css.index(".gi-video-preview + .gi-video-poster", block_start)
        block = css[block_start:block_end]
        self.assertIn("pointer-events: none;", block)

    def test_video_cards_do_not_render_redundant_bottom_video_badge(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertNotIn("gi-media-badge\">视频", history_js)
        self.assertNotIn("gi-media-badge'>视频", card_manager_js)

    def test_video_tag_renders_in_card_text_action_row(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()
        sprite = (ROOT / "static/icons/sprite.svg").read_text()

        self.assertIn("function _infoVideoTagHtml", history_js)
        self.assertIn("gi-video-chip", history_js)
        self.assertIn("icon(\"video\", 16)", history_js.replace("'", "\""))
        self.assertIn("aria-label=\"视频\"", history_js)
        self.assertNotIn("<span>视频</span>", history_js)

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

        self.assertIn("function _isReferenceVideoField", generate_js)
        self.assertIn("cls === 'LoadVideo' && field === 'file'", generate_js)
        self.assertIn("cls === 'VHS_LoadVideo' && field === 'video'", generate_js)
        self.assertIn("f.type === 'video'", generate_js)
        self.assertIn("id=\"refVideoFile\"", generate_js)
        self.assertIn("/api/upload-video", generate_js)
        self.assertIn("/api/input-video/", generate_js)
        self.assertIn("需要先上传参考视频", generate_js)
        self.assertIn(".video-upload-preview", css)

    def test_quick_form_supports_reference_audio_upload(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _isReferenceAudioField", generate_js)
        self.assertIn("cls === 'LoadAudio' && field === 'audio'", generate_js)
        self.assertIn("f.type === 'audio'", generate_js)
        self.assertIn("id=\"refAudioFile\"", generate_js)
        self.assertIn("id=\"refAudioPreview\"", generate_js)
        self.assertIn("id=\"refAudioReplace\"", generate_js)
        self.assertIn("/api/upload-audio", generate_js)
        self.assertIn("/api/input-audio/", generate_js)
        self.assertIn("需要先上传参考音频", generate_js)
        self.assertIn(".audio-upload-preview", css)
        self.assertIn(".audio-upload-replace", css)

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
