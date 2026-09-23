import unittest

from app.stats_view import build_classifiers, build_stats, parse_pedir_text, query_posts


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

    def test_pedir_duracion_menos_y_etiqueta(self):
        items = [
            {"id": 1, "media": "video", "duration": 600, "views": 10, "hashtags": ["sofia"]},
            {"id": 2, "media": "video", "duration": 1200, "views": 50, "hashtags": ["sofia"]},
            {"id": 3, "media": "video", "duration": 3000, "views": 5, "hashtags": ["otra"]},
            {"id": 4, "media": "photo", "views": 1, "hashtags": ["Sofia"]},
        ]
        page = query_posts(items, "@canal", kind="duracion", min_min=10, max_min=40)
        text = "\n".join(page["parts"])
        self.assertEqual(page["total"], 2)
        self.assertIn("https://t.me/canal/1", text)
        self.assertNotIn("https://t.me/canal/3", text)
        menos = "\n".join(query_posts(items, "@canal", kind="menos", limit=1)["parts"])
        self.assertIn("1-1 de 4", menos)
        self.assertIn("https://t.me/canal/4", menos)
        nxt = "\n".join(query_posts(items, "@canal", kind="menos", offset=1, limit=1)["parts"])
        self.assertIn("2-2 de 4", nxt)
        tagged = query_posts(items, "@canal", kind="etiqueta", tag="sofia")
        self.assertEqual(tagged["total"], 3)

    def test_comando_sin_espacios(self):
        spaced = parse_pedir_text("/pedir vistos 30")
        glued = parse_pedir_text("/pedirvistos30")
        visto = parse_pedir_text("/pedirvisto30")
        self.assertEqual(spaced["kind"], "vistos")
        self.assertEqual(spaced["limit"], 30)
        self.assertEqual(glued["kind"], "vistos")
        self.assertEqual(glued["limit"], 30)
        self.assertEqual(visto["limit"], 30)
        dur = parse_pedir_text("/pedirduracion10-40")
        self.assertEqual(dur["min_min"], 10)
        self.assertEqual(dur["max_min"], 40)
        tag = parse_pedir_text("/pediretiquetasofia-20")
        self.assertEqual(tag["tag"], "sofia")
        self.assertEqual(tag["limit"], 20)
        typed = parse_pedir_text("/pediretiketasofia-20")
        self.assertEqual(typed["tag"], "sofia")
        self.assertEqual(typed["limit"], 20)
        self.assertEqual(parse_pedir_text("/pediretiquetas")["kind"], "etiquetas")
        self.assertEqual(parse_pedir_text("/pediretiketas")["kind"], "etiquetas")
        menos = parse_pedir_text("/pedirmenos20")
        self.assertEqual(menos["kind"], "menos")
        self.assertEqual(menos["limit"], 20)
        self.assertTrue(parse_pedir_text("/mas")["mas"])
