import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mpsc2.session import barrier


def test_barrier_starts_all_peers_before_waiting():
    async def exercise():
        seen = set()
        ready = asyncio.Event()

        async def peer(i):
            seen.add(i)
            if len(seen) == 4:
                ready.set()
            await ready.wait()
            return i

        assert await barrier([peer(i) for i in range(4)], 1) == [0, 1, 2, 3]
    asyncio.run(exercise())


def test_barrier_timeout_closes_socket_and_cancels_peer():
    async def exercise():
        closed = asyncio.Event()
        ws = SimpleNamespace(close=AsyncMock(side_effect=closed.set))
        drained = asyncio.Event()

        async def stuck_peer():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                assert closed.is_set()
                drained.set()
                raise

        with pytest.raises(TimeoutError):
            await barrier([stuck_peer()], 0.02, [SimpleNamespace(_ws=ws)])
        assert drained.is_set()
    asyncio.run(exercise())


def test_barrier_propagates_failure_and_cancels_sibling():
    async def exercise():
        async def broken():
            raise ValueError("join failed")

        async def sibling():
            await asyncio.Event().wait()

        with pytest.raises(ValueError, match="join failed"):
            await barrier([broken(), sibling()], 1)
    asyncio.run(exercise())
