import asyncio
import unittest

from app.human_read import iter_history_human


class Msg:
    def __init__(self, i: int) -> None:
        self.id = i


class FakeClient:
    def __init__(self, total: int = 80) -> None:
        self.ids = list(range(total, 0, -1))
        self.calls: list[tuple[int, int]] = []

    async def get_messages(self, entity, limit: int, offset_id: int = 0):
        self.calls.append((limit, offset_id))
        pool = self.ids if not offset_id else [i for i in self.ids if i < offset_id]
        return [Msg(i) for i in pool[:limit]]


class HumanReadTest(unittest.IsolatedAsyncioTestCase):
    async def test_small_batches_and_offset(self):
        client = FakeClient(80)
        got = []
        async for msg in iter_history_human(
            client,
            "chan",
            limit=50,
            page_min=20,
            page_max=20,
            wait_min=0,
            wait_max=0,
            look_min=0,
            look_max=0,
            idle_p=0,
            idle_max=0,
            warmup_min=0,
            warmup_max=0,
        ):
            got.append(msg.id)
        self.assertEqual(len(got), 50)
        self.assertEqual(len(client.calls), 3)
        self.assertTrue(all(lim <= 20 for lim, _ in client.calls))
        self.assertEqual(client.calls[0][1], 0)
        self.assertGreater(client.calls[1][1], 0)


if __name__ == "__main__":
    unittest.main()
