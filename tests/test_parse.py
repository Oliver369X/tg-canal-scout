import unittest

from app.parse import extract_hashtags, extract_urls, parse_peer, url_domain


class ParsePeerTest(unittest.TestCase):
    def test_plain_username(self):
        self.assertEqual(parse_peer("cristuis"), "cristuis")

    def test_at(self):
        self.assertEqual(parse_peer("@CursosFacialix"), "CursosFacialix")

    def test_tme(self):
        self.assertEqual(parse_peer("https://t.me/CursosFacialix"), "CursosFacialix")

    def test_tme_post(self):
        self.assertEqual(parse_peer("https://t.me/cristuis/12"), "cristuis")

    def test_web_preview_s(self):
        self.assertEqual(parse_peer("https://t.me/s/cristuis"), "cristuis")

    def test_private_c(self):
        self.assertEqual(parse_peer("https://t.me/c/1234567890/5"), "-1001234567890")

    def test_invite(self):
        self.assertTrue(parse_peer("https://t.me/+AbCdEf").startswith("invite:"))

    def test_share_is_not_channel(self):
        self.assertIsNone(parse_peer("https://t.me/share/url?url=https://example.com"))

    def test_urls_and_tags(self):
        text = "mira https://drive.google.com/a y #Curso extra"
        self.assertEqual(extract_urls(text), ["https://drive.google.com/a"])
        self.assertEqual(extract_hashtags(text), ["curso"])
        self.assertEqual(url_domain("https://www.Drive.Google.com/x"), "drive.google.com")


if __name__ == "__main__":
    unittest.main()
