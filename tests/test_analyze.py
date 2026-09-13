import unittest

from app.analyze import summarize
from app.bot import format_ficha


class SummarizeTest(unittest.TestCase):
    def test_mix_and_cadence(self):
        items = [
            {
                "id": 1,
                "date": "2026-09-10T12:00:00+00:00",
                "media": "photo",
                "urls": ["https://drive.google.com/a"],
                "hashtags": ["curso"],
                "views": 100,
                "size": 50_000,
            },
            {
                "id": 2,
                "date": "2026-09-12T12:00:00+00:00",
                "media": "video",
                "duration": 720,
                "size": 120 * 1024 * 1024,
                "w": 1920,
                "h": 1080,
                "views": 500,
                "fwd": "@otro",
            },
            {
                "id": 3,
                "date": "2026-09-12T13:00:00+00:00",
                "media": "text",
                "urls": [],
            },
        ]
        s = summarize(items, {"title": "Demo", "kind": "canal", "peer": "@demo"})
        self.assertEqual(s["sampled"], 3)
        self.assertEqual(s["photos"], 1)
        self.assertEqual(s["videos"], 1)
        self.assertEqual(s["videos_ge_10min"], 1)
        self.assertEqual(s["files_ge_100mb"], 1)
        self.assertEqual(s["forwarded"], 1)
        self.assertEqual(s["with_url"], 1)
        self.assertGreater(s["posts_per_day"], 0)
        self.assertEqual(s["resolutions"].get("1080p+"), 1)
        self.assertEqual(s["top_domains"][0][0], "drive.google.com")
        text = format_ficha(s, 9)
        self.assertIn("Ficha — Demo", text)
        self.assertIn("Videos", text)
        self.assertLessEqual(len(text), 3900)

    def test_merge_and_paging(self):
        from app.analyze import merge_items, oldest_msg_id, set_paging

        a = [{"id": 10}, {"id": 9}]
        b = [{"id": 9}, {"id": 8}]
        m = merge_items(a, b)
        self.assertEqual([i["id"] for i in m], [10, 9, 8])
        self.assertEqual(oldest_msg_id(m), 8)
        s = set_paging({"sampled": 300}, exhausted=False, max_sample=4000, continue_hint=300)
        self.assertTrue(s["can_continue"])
        s2 = set_paging({"sampled": 120}, exhausted=True, max_sample=4000)
        self.assertFalse(s2["can_continue"])


class PaceTest(unittest.TestCase):
    def test_amounts(self):
        from app.pace import PACES, parse_amount, pace_for_amount

        self.assertIsNone(parse_amount("all"))
        self.assertEqual(parse_amount("300"), 300)
        self.assertEqual(pace_for_amount("100"), "fast")
        self.assertEqual(pace_for_amount("all"), "crawl")
        for p in PACES.values():
            self.assertLessEqual(p["page_max"], 43)

    def test_delays_are_not_flat(self):
        from app.human_read import skewed_delay

        vals = [round(skewed_delay(1.0, 3.0), 3) for _ in range(40)]
        self.assertGreater(len(set(vals)), 8)
        self.assertTrue(min(vals) < 1.2 or max(vals) > 2.8)


if __name__ == "__main__":
    unittest.main()
