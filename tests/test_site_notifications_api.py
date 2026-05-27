import os
import sqlite3
import tempfile
import unittest

import app


class SiteNotificationsApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_auth_db = app.AUTH_DB
        app.AUTH_DB = os.path.join(self._tmp.name, "auth.db")
        app._init_auth_db()

    def tearDown(self):
        app.AUTH_DB = self._old_auth_db
        self._tmp.cleanup()

    def test_access_token_lasts_at_least_one_month(self):
        self.assertGreaterEqual(app.ACCESS_TOKEN_EXPIRE_DAYS, 31)

    def test_admin_can_create_and_list_site_notifications(self):
        result = app.api_site_notification_create(
            app.SiteNotificationCreateRequest(title="维护通知", content="今晚 23:00 更新。"),
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["title"], "维护通知")
        self.assertEqual(result["data"]["created_by"], "admin")

        user_list = app.api_site_notifications(current_user={"sub": "user1", "role": "user"})
        self.assertEqual(len(user_list["data"]), 1)
        self.assertEqual(user_list["data"][0]["content"], "今晚 23:00 更新。")

        admin_list = app.api_site_notifications_admin(current_user={"sub": "admin", "role": "admin"})
        self.assertEqual(len(admin_list["data"]), 1)

    def test_admin_can_update_and_delete_site_notifications(self):
        created = app.api_site_notification_create(
            app.SiteNotificationCreateRequest(title="旧标题", content="旧内容"),
            current_user={"sub": "admin", "role": "admin"},
        )["data"]

        updated = app.api_site_notification_update(
            created["id"],
            app.SiteNotificationUpdateRequest(title="新标题", content="新内容"),
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertTrue(updated["ok"])
        self.assertEqual(updated["data"]["id"], created["id"])
        self.assertEqual(updated["data"]["title"], "新标题")
        self.assertEqual(updated["data"]["content"], "新内容")
        user_list = app.api_site_notifications(current_user={"sub": "user1", "role": "user"})
        self.assertEqual(user_list["data"][0]["title"], "新标题")

        deleted = app.api_site_notification_delete(created["id"], current_user={"sub": "admin", "role": "admin"})

        self.assertTrue(deleted["ok"])
        self.assertEqual(app.api_site_notifications(current_user={"sub": "user1", "role": "user"})["data"], [])
        self.assertEqual(app.api_site_notifications_admin(current_user={"sub": "admin", "role": "admin"})["data"], [])

    def test_dismiss_suppresses_until_new_notification(self):
        first = app.api_site_notification_create(
            app.SiteNotificationCreateRequest(title="第一条", content="A"),
            current_user={"sub": "admin", "role": "admin"},
        )["data"]
        second = app.api_site_notification_create(
            app.SiteNotificationCreateRequest(title="第二条", content="B"),
            current_user={"sub": "admin", "role": "admin"},
        )["data"]

        app.api_site_notification_dismiss(
            app.SiteNotificationDismissRequest(notification_id=second["id"]),
            current_user={"sub": "user1", "role": "user"},
        )
        muted = app.api_site_notifications(current_user={"sub": "user1", "role": "user"})
        self.assertEqual(muted["data"], [])
        self.assertGreaterEqual(muted["suppressed_until_id"], first["id"])

        third = app.api_site_notification_create(
            app.SiteNotificationCreateRequest(title="第三条", content="C"),
            current_user={"sub": "admin", "role": "admin"},
        )["data"]
        after_new = app.api_site_notifications(current_user={"sub": "user1", "role": "user"})
        self.assertEqual([item["id"] for item in after_new["data"]], [third["id"]])

    def test_notification_tables_are_created_in_auth_db(self):
        conn = sqlite3.connect(app.AUTH_DB)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()

        self.assertIn("site_notifications", tables)
        self.assertIn("site_notification_state", tables)


if __name__ == "__main__":
    unittest.main()
