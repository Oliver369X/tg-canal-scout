import unittest

from app.stats_view import build_classifiers, build_stats


class StatsViewTest(unittest.TestCase):
    def test_buckets_stamp_and_duplicate(self):
        items = [
            {
                "id": 10,
                "date": "2024-05-01T20:00:00+00:00",
                "media": "video",
                "mime": "video/mp4",
                "duration": 90,
                "size": 8 * 1024 * 1024,
                "w": 1280,
                "h": 720,
                "name": "clip.mp4",
                "grouped_id": 5,
            },
            {
                "id": 11,
                "date": "2024-05-02T20:00:00+00:00",
                "media": "video",
                "mime": "video/mp4",
                "duration": 90,
                "size": 8 * 1024 * 1024,
                "w": 1280,
                "h": 720,
                "grouped_id": 5,
            },
            {
                "id": 12,
                "date": "2025-03-01T12:00:00+00:00",
                "media": "photo",
                "mime": "image/jpeg",
                "size": 80_000,
                "w": 800,
                "h": 600,
            },
        ]
        out = build_stats(items, "@canal", "Canal")
        text = "\n".join(out["overview"] + out["files"])
        self.assertIn("Posts: 3", text)
        self.assertIn("video/mp4: 2", text)
        self.assertIn("image/jpeg: 1", text)
        self.assertIn("1–10 min: 2", text)
        self.assertIn("2024: 2", text)
        self.assertIn("2025-03: 1", text)
        self.assertIn("clip.mp4", text)
        self.assertIn("×2", text)
        self.assertIn("https://t.me/canal/10", text)
        self.assertIn("1280×720", text)
        self.assertIn("Peso total del canal:", text)
        classes = "\n".join(build_classifiers(items, "@canal", "Canal"))
        self.assertIn("Peso total del canal:", classes)
        self.assertIn("Videos repetidos", classes)
        self.assertIn("×2", classes)
