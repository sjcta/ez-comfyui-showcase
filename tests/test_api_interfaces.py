import unittest

import app


class _Request:
    base_url = "http://testserver/"


class ApiInterfacesTest(unittest.TestCase):
    def test_catalog_includes_submit_and_list_endpoints(self):
        result = app.api_interfaces(_Request(), current_user=None)

        self.assertTrue(result["ok"])
        self.assertGreater(result["total"], 0)
        paths = {entry["path"]: entry for entry in result["endpoints"]}
        self.assertEqual(paths["/api/generate"]["kind"], "submit")
        self.assertEqual(paths["/api/workflows"]["kind"], "list")
        self.assertEqual(paths["/api/generate"]["url"], "http://testserver/api/generate")

    def test_catalog_filters_by_kind(self):
        result = app.api_interfaces(_Request(), kind="submit", current_user=None)

        self.assertTrue(result["ok"])
        self.assertGreater(result["total"], 0)
        self.assertTrue(all(entry["kind"] == "submit" for entry in result["endpoints"]))
        self.assertIn("/api/generate", {entry["path"] for entry in result["endpoints"]})
        self.assertNotIn("/api/workflows", {entry["path"] for entry in result["endpoints"]})

    def test_catalog_filters_by_auth(self):
        result = app.api_interfaces(_Request(), auth="admin", current_user=None)

        self.assertTrue(result["ok"])
        self.assertGreater(result["total"], 0)
        self.assertTrue(all(entry["auth"] == "admin" for entry in result["endpoints"]))
        self.assertIn(
            "/api/workflows/{name}/upload-version",
            {entry["path"] for entry in result["endpoints"]},
        )


if __name__ == "__main__":
    unittest.main()
