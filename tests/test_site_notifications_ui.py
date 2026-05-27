from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SiteNotificationsUiTests(unittest.TestCase):
    def test_admin_account_menu_exposes_site_notifications(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")

        self.assertIn("网站通知", auth_js)
        self.assertIn("CW.auth.showAccountTab(\\'notifications\\')", auth_js)
        self.assertIn("data-tab=\"notifications\"", auth_js)
        self.assertIn("sendSiteNotification: sendSiteNotification", auth_js)

    def test_site_notification_modal_supports_next_close_and_mute(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")

        for token in (
            "siteNotificationOverlay",
            "CW.auth.nextSiteNotification()",
            "CW.auth.closeSiteNotification()",
            "CW.auth.muteSiteNotifications()",
            "apiFetch(_withCacheBust(API + '/api/site-notifications')",
            "apiFetch(API + '/api/site-notifications/dismiss'",
        ):
            self.assertIn(token, auth_js)

    def test_notification_admin_supports_edit_and_delete(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")

        for token in (
            "editSiteNotification(",
            "cancelEditSiteNotification",
            "deleteSiteNotification(",
            "siteNoticeEditingId",
            "保存修改",
            "/api/site-notifications/' + id",
            "method: 'PUT'",
            "method: 'DELETE'",
        ):
            self.assertIn(token, auth_js)

    def test_site_notification_styles_are_present(self):
        css = (ROOT / "static/css/style.css").read_text("utf-8")

        for token in (
            ".notice-compose-card",
            ".notice-record-row",
            ".site-notice-modal",
            ".site-notice-actions",
            ".auth-modal-overlay .site-notice-modal",
        ):
            self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
