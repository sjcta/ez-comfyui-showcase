from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AccountHistoryUiContractTests(unittest.TestCase):
    def test_favorite_filter_is_visually_separated_from_share_filters(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("account-history-share-filter-group", auth_js)
        self.assertIn("role=\"group\" aria-label=\"分享状态筛选\"", auth_js)
        self.assertIn("account-history-favorite-filter", auth_js)
        self.assertIn("account-history-hidden-filter", auth_js)
        self.assertIn("data-hidden-filter", auth_js)
        self.assertIn("已隐藏", auth_js)
        self.assertNotIn("showAccountTab('hidden')", auth_js)
        self.assertNotIn('data-tab="hidden"', auth_js)
        self.assertLess(
            auth_js.index("account-history-share-filter-group"),
            auth_js.index("account-history-favorite-filter"),
        )
        self.assertLess(
            auth_js.index("account-history-favorite-filter"),
            auth_js.index("account-history-hidden-filter"),
        )
        self.assertIn(".account-history-filter-segments", css)
        self.assertIn("gap: 9px", css)
        self.assertIn(".account-history-share-filter-group", css)
        self.assertIn("min-width: 76px", css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", css)
        self.assertIn("flex: 0 0 76px", css)
        self.assertIn(".account-history-favorite-filter.active", css)
        self.assertIn(".account-history-hidden-filter.active", css)
        segment_rule = css[css.index("  .account-history-filter-segments {"):]
        segment_rule = segment_rule[: segment_rule.index("  .account-history-count {")]
        self.assertNotIn("grid-template-columns: repeat(4, minmax(0, 1fr))", segment_rule)

    def test_account_history_row_has_confirm_free_icon_delete(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function deleteHistoryItem(id)", auth_js)
        self.assertIn("apiFetch(API + '/api/history/' + encodeURIComponent(id), { method: 'DELETE' })", auth_js)
        delete_fn = auth_js[auth_js.index("function deleteHistoryItem(id)") : auth_js.index("function _postHistoryBatch")]
        self.assertNotIn("confirm(", delete_fn)
        self.assertIn("account-hist-quick-delete", auth_js)
        self.assertIn("aria-label=\"删除\"", auth_js)
        self.assertIn("CW.auth.deleteHistoryItem", auth_js)
        self.assertIn("deleteHistoryItem: deleteHistoryItem", auth_js)
        self.assertLess(auth_js.index("download>"), auth_js.index("account-hist-quick-delete"))
        self.assertIn(".account-hist-quick-delete", css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr)) 32px", css)
        self.assertIn(".account-hist-actions .account-hist-quick-delete", css)
        self.assertNotIn("repeat(3, minmax(0, 1fr)) 32px", css)
        self.assertNotIn("position: absolute", css[css.index(".account-hist-quick-delete {") : css.index(".account-hist-quick-delete:hover")])
        mobile_action_btn = css[
            css.index("  .account-hist-actions .account-action-btn {") :
            css.index("  .account-hist-row.is-admin {")
        ]
        self.assertNotIn("grid-row: 2;", mobile_action_btn)

    def test_trash_view_has_no_selection_checkbox_and_uses_restore_all(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("(trashMode ? '' : '<input type=\"checkbox\" class=\"hist-select\"", auth_js)
        self.assertIn("function restoreAllTrash()", auth_js)
        self.assertIn("CW.auth.restoreAllTrash()", auth_js)
        self.assertIn("全部恢复", auth_js)
        trash_toolbar = auth_js[auth_js.index("(trashMode") : auth_js.index(": '<button class=\"wf-mgr-btn account-action-btn\" type=\"button\" onclick=\"CW.auth.downloadSelected()")]
        self.assertNotIn("恢复选中", trash_toolbar)
        self.assertNotIn("permanentDeleteSelected", trash_toolbar)
        self.assertIn(".account-hist-row.is-deleted", css)
        self.assertIn("grid-template-columns: 64px minmax(0,1fr)", css)
        self.assertIn(".account-hist-row.is-deleted .account-hist-actions", css)
        self.assertIn("grid-template-columns: 72px minmax(0,1fr)", css)

    def test_account_history_hover_preview_uses_thumbnail_not_original(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()

        self.assertIn("title=\"悬停查看缩略预览，点击打开原图\"", auth_js)
        self.assertIn("showHistoryHoverPreview(\\'' + escA(thumbUrl)", auth_js)
        self.assertIn("onclick=\"window.open(\\'' + escA(imageUrl)", auth_js)
        self.assertNotIn("showHistoryHoverPreview(\\'' + escA(imageUrl)", auth_js)

    def test_gallery_cards_do_not_render_hide_buttons(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertNotIn("_hideBadgeHtml", history_js)
        self.assertNotIn("_hideBadgeHtml", card_manager_js)
        self.assertNotIn("gi-hide-btn", history_js)
        self.assertNotIn("gi-hide-btn", card_manager_js)
        self.assertNotIn(".gi-hide-btn", css)

    def test_account_history_uses_compact_lists_and_lazy_prompt_details(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()

        self.assertIn("/api/history/user-counts", auth_js)
        self.assertNotIn("/api/history?scope=all&limit=5000", auth_js)
        self.assertIn("'&compact=1'", auth_js)
        self.assertIn("async function _hydrateHistoryDetail(item)", auth_js)
        self.assertIn("await window.CW.getHistoryDetail(item)", auth_js)
        self.assertIn("async function toggleHistoryPrompt(id)", auth_js)
        self.assertIn("async function copyHistoryPromptById(id)", auth_js)


if __name__ == "__main__":
    unittest.main()
