import unittest

from cx_reminder.edge_cookies import CookieRecord, build_cookie_header


class EdgeCookiesTest(unittest.TestCase):
    def test_build_cookie_header_filters_matching_domains(self):
        cookies = [
            CookieRecord(".chaoxing.com", "UID", "1"),
            CookieRecord("example.com", "OTHER", "2"),
            CookieRecord("mooc1.chaoxing.com", "fid", "3"),
        ]

        header = build_cookie_header(cookies, ["chaoxing.com"])

        self.assertEqual(header, "UID=1; fid=3")

    def test_build_cookie_header_returns_empty_for_no_match(self):
        cookies = [CookieRecord("example.com", "OTHER", "2")]

        header = build_cookie_header(cookies, ["chaoxing.com"])

        self.assertEqual(header, "")


if __name__ == "__main__":
    unittest.main()
