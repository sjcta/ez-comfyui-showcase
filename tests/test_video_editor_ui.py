from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VideoEditorUiTests(unittest.TestCase):
    def test_lightbox_exposes_video_frame_editor_controls(self):
        index = (ROOT / "static/index.html").read_text()
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn('id="lbVideoEditor"', index)
        self.assertIn('id="lbVideoEditBtn"', index)
        self.assertIn("#icon-clapperboard", index)
        self.assertIn('class="lb-video-timeline-panel"', index)
        self.assertIn('class="lb-video-track"', index)
        self.assertIn('id="lbVideoTimeline"', index)
        self.assertIn('id="lbVideoTicks"', index)
        self.assertIn('id="lbVideoExportBtn"', index)
        self.assertIn('id="lbVideoExportMenu"', index)
        self.assertIn('lb-video-icon-btn', index)
        self.assertIn('#icon-camera', index)
        self.assertIn('#icon-upload', index)
        self.assertIn('#icon-edit', index)
        self.assertIn('#icon-video', index)
        self.assertIn('#icon-scaleup', index)
        self.assertIn("CW.enableLBVideoEditor", index)
        self.assertIn("CW.setLBVideoCover", index)
        self.assertIn("CW.toggleLBVideoExportMenu", index)
        self.assertIn("导出到图生图", index)
        self.assertIn("导出到视频制作", index)
        self.assertIn("importLBVideoFrame('视频制作', event)", index)
        self.assertNotIn("importLBVideoFrame('图生视频', event)", index)
        self.assertIn("导出到放大", index)
        self.assertIn("function enableLBVideoEditor", history_js)
        self.assertIn("function toggleLBVideoExportMenu", history_js)
        self.assertIn("function setLBVideoCover", history_js)
        self.assertIn("function importLBVideoFrame", history_js)
        self.assertIn("_syncHistoryItemFrameThumb(itemId, thumb, protection)", history_js)
        self.assertIn("item.protection_status = protection.protection_status", history_js)
        self.assertIn("item.protection_checked_at = protection.protection_checked_at", history_js)
        self.assertIn("function _workflowMatchesImportType", history_js)
        self.assertIn("typeText === '视频制作'", history_js)
        self.assertIn("tags.indexOf('图生视频') >= 0", history_js)
        self.assertIn("_prepareLightboxVideoEditor(_lbCurrentItem)", history_js)
        self.assertIn("els.root.addEventListener(eventName", history_js)
        self.assertIn("ev.stopPropagation", history_js)
        self.assertIn("lb-video-editing", history_js)
        self.assertIn("_formatVideoTimeFrame", history_js)
        self.assertIn('style="left:\' + pct.toFixed(4) + \'%"', history_js)
        self.assertIn("/api/history/' + encodeURIComponent(_lbCurrentItem.id) + '/video-frame", history_js)

    def test_video_editor_clamps_exports_before_duration_boundary(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _lastLightboxVideoFrameTime(duration, fps)", history_js)
        self.assertIn("els.timeline.max = String(_lastLightboxVideoFrameTime(duration, fps));", history_js)
        self.assertIn("String(_lastLightboxVideoFrameTime(duration, fps)) : '0'", history_js)
        self.assertIn("if (Number.isFinite(maxTime) && maxTime > 0) value = Math.min(value, maxTime);", history_js)
        self.assertIn("? _lastLightboxVideoFrameTime(duration, fps)", history_js)
        self.assertIn("maxTime > 0 ? Math.min(value, maxTime) : value", history_js)

    def test_video_editing_hides_non_close_lightbox_actions(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".lightbox.lb-video-editing .lb-actions", css)
        self.assertIn(".lightbox.lb-video-editing .lb-download", css)
        self.assertIn(".lightbox.lb-video-editing .lb-image-export-wrap", css)
        self.assertIn(".lightbox.lb-video-editing .lb-nav", css)
        self.assertIn(".lightbox.lb-video-editing .lb-info", css)

    def test_video_timeline_ticks_share_mobile_track_width(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".lb-video-track", css)
        self.assertIn(".lb-video-editor-toolbar", css)
        self.assertIn(".lb-video-export-menu", css)
        self.assertIn("right: calc(100% + 8px);", css)
        self.assertIn("transform: translateY(-50%);", css)
        self.assertIn(".lb-video-timeline-panel", css)
        self.assertIn(".lb-video-icon-btn", css)
        self.assertIn("border-radius: 50%;", css)
        self.assertIn("width: calc(100vw - 32px);", css)
        self.assertIn("padding: 9px 18px;", css)
        self.assertIn("z-index: 10046;", css)
        self.assertIn("background: rgba(18,24,38,.34);", css)
        self.assertIn("border: 0;", css)
        self.assertIn(".lb-action-btn,\n  .lb-video-icon-btn,", css)
        self.assertIn(".lb-action-btn svg,\n  .lb-video-icon-btn svg,", css)
        self.assertIn(".lb-video-ticks {\n  position: relative;", css)
        self.assertIn(".lb-video-tick {\n  position: absolute;", css)
        self.assertIn(".lb-video-tick-time,\n.lb-video-tick-frame", css)
        self.assertIn("@media (hover: none) and (pointer: coarse) and (orientation: landscape)", css)
        self.assertIn("calc(100vw - max(224px", css)
        self.assertIn("@media (max-width: 560px)", css)
        self.assertIn(".lb-video-timeline-row {\n    grid-template-columns: minmax(0, 1fr);", css)

    def test_video_timeline_tick_density_uses_track_width(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _formatVideoTickLabel(sec, fps)", history_js)
        self.assertIn("var trackWidth = Number(els.ticks.clientWidth || 0);", history_js)
        self.assertIn("trackWidth < 520 ? 3", history_js)
        self.assertIn("_formatVideoTickLabel(t, fps)", history_js)

    def test_video_timeline_thumb_uses_primary_round_button(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("accent-color: var(--accent);", css)
        self.assertIn(".lb-video-timeline::-webkit-slider-thumb", css)
        self.assertIn("width: 26px;", css)
        self.assertIn("height: 26px;", css)
        self.assertIn("background: var(--accent);", css)
        self.assertIn(".lb-video-timeline:active::-webkit-slider-thumb", css)
        self.assertIn(".lb-video-timeline:focus-visible::-webkit-slider-thumb", css)

    def test_video_edit_button_uses_cut_icon_and_mobile_alignment(self):
        css = (ROOT / "static/css/style.css").read_text()
        sprite = (ROOT / "static/icons/sprite.svg").read_text()

        self.assertIn('id="icon-clapperboard"', sprite)
        self.assertIn(".lb-video-edit-icon", css)
        self.assertIn("color: var(--accent);", css)
        self.assertIn(".lb-video-edit {\n    left: max(var(--lb-round-edge-offset), env(safe-area-inset-left));", css)
        self.assertIn("bottom: calc(max(var(--lb-round-edge-offset), env(safe-area-inset-bottom)) + var(--lb-round-bottom-offset) + var(--lb-round-step) + var(--lb-round-step));", css)


if __name__ == "__main__":
    unittest.main()
