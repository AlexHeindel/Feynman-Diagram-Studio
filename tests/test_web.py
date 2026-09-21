import http.client
import json
import threading
import unittest

from feynman_studio.latex import latex_source
from feynman_studio.model import templates
from feynman_studio.web import _create_server, create_server


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server("127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, payload=None, *, authorized=True):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        if authorized:
            headers["X-FDS-Token"] = self.server.token
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_editor_and_bootstrap_are_served(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"Feynman Diagram Studio Web", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")

        status, _headers, body = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        bootstrap = json.loads(body)
        self.assertEqual(len(bootstrap["templates"]), 10)
        self.assertEqual(len(bootstrap["latexFormats"]), 6)
        self.assertEqual(bootstrap["token"], self.server.token)

        for path, marker in (("/app.css", b".workspace"), ("/app.js", b"renderCanvas")):
            status, _headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn(marker, body)

    def test_api_requires_the_editor_token_and_validates_projects(self):
        document = templates()[0].to_dict()
        status, _headers, body = self.request(
            "POST", "/api/validate", {"diagram": document}, authorized=False
        )
        self.assertEqual(status, 403)
        self.assertIn("did not come from the editor", json.loads(body)["error"])

        status, _headers, body = self.request("POST", "/api/validate", {"diagram": document})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["diagram"], document)

        invalid = dict(document)
        invalid["version"] = 99
        status, _headers, body = self.request("POST", "/api/validate", {"diagram": invalid})
        self.assertEqual(status, 400)
        self.assertIn("version 1", json.loads(body)["error"])

    def test_latex_api_uses_the_desktop_exporter(self):
        document = templates()[1]
        status, _headers, body = self.request(
            "POST",
            "/api/latex",
            {"diagram": document.to_dict(), "format": "tikz-feynhand"},
        )
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["source"], latex_source(document, "tikz-feynhand"))
        self.assertIn(r"\documentclass", result["standalone"])

    def test_all_native_export_formats_are_downloadable(self):
        document = templates()[2].to_dict()
        signatures = {
            "svg": b"<svg",
            "pdf": b"%PDF-",
            "png": b"\x89PNG\r\n\x1a\n",
            "jpg": b"\xff\xd8\xff",
        }
        for format_name, signature in signatures.items():
            with self.subTest(format=format_name):
                status, headers, body = self.request(
                    "POST",
                    "/api/export",
                    {
                        "diagram": document,
                        "format": format_name,
                        "ppi": 300,
                        "transparent": format_name in ("svg", "png"),
                    },
                )
                self.assertEqual(status, 200)
                self.assertTrue(body.startswith(signature))
                self.assertIn("attachment", headers["Content-Disposition"])
                self.assertIn("one-loop-self-energy", headers["Content-Disposition"])

    def test_missing_routes_are_json_errors(self):
        status, headers, body = self.request("GET", "/missing")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body)["error"], "Not found.")

    def test_default_port_conflicts_fall_back_to_a_free_port(self):
        occupied = create_server("127.0.0.1", 0)
        port = occupied.server_address[1]
        fallback = None
        try:
            fallback, used_fallback = _create_server("127.0.0.1", port, True)
            self.assertTrue(used_fallback)
            self.assertNotEqual(fallback.server_address[1], port)
            with self.assertRaises(OSError):
                _create_server("127.0.0.1", port, False)
        finally:
            if fallback is not None:
                fallback.server_close()
            occupied.server_close()


if __name__ == "__main__":
    unittest.main()
