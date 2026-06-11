import unittest

from cx_reminder.readonly_http import ReadOnlyHttpClient


class FakeOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return "response"


class ReadOnlyHttpTest(unittest.TestCase):
    def test_get_is_allowed(self):
        opener = FakeOpener()
        client = ReadOnlyHttpClient(opener=opener)

        response = client.get("https://example.com/data")

        self.assertEqual(response, "response")
        self.assertEqual(opener.requests[0][0].get_method(), "GET")

    def test_head_is_allowed(self):
        opener = FakeOpener()
        client = ReadOnlyHttpClient(opener=opener)

        response = client.head("https://example.com/data")

        self.assertEqual(response, "response")
        self.assertEqual(opener.requests[0][0].get_method(), "HEAD")

    def test_post_is_blocked_before_opener_runs(self):
        opener = FakeOpener()
        client = ReadOnlyHttpClient(opener=opener)

        with self.assertRaises(ValueError):
            client.request("POST", "https://example.com/update")

        self.assertEqual(opener.requests, [])


if __name__ == "__main__":
    unittest.main()
