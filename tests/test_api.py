import http.client
import json
from http.server import ThreadingHTTPServer
import tempfile
import threading
import unittest
from forex_agent.api import handler_factory
from forex_agent.models import RiskPolicy


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.token = "test-token-" + "a" * 40
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(
            cls.folder.name + "/journal.sqlite3", cls.token, RiskPolicy()))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.folder.cleanup()

    def request(self, method, path, body=None, auth=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        result = (response.status, json.loads(response.read()))
        connection.close()
        return result

    def test_health_and_authentication(self):
        status, body = self.request("GET", "/health", auth=False)
        self.assertEqual(status, 200)
        self.assertFalse(body["execution_enabled"])
        self.assertEqual(self.request("GET", "/v1/journal", auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/v1/journal")[0], 200)

    def test_malformed_request_and_nan_rejected(self):
        self.assertEqual(self.request("POST", "/v1/analyze", "{")[0], 400)
        self.assertEqual(self.request("POST", "/v1/analyze", '{"value": NaN}')[0], 400)

    def test_no_file_paths_or_execution_route(self):
        self.assertEqual(self.request("POST", "/v1/order", "{}")[0], 404)
        self.assertEqual(self.request("POST", "/v1/analyze", '{"snapshot":"/etc/passwd"}')[0], 400)


if __name__ == "__main__":
    unittest.main()
