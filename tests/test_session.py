import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mpsc2.session import OwnedSC2Process, SC2LaunchError, barrier


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


@pytest.mark.parametrize('returncode', [0, 1, -9])
def test_exited_engine_stops_connect_and_cleans_owned_resources(returncode):
    process = OwnedSC2Process.__new__(OwnedSC2Process)
    child = Mock(pid=1234, returncode=returncode, args=['/fixture/SC2', '-port', '5000'])
    child.poll.return_value = returncode
    process._launch = Mock(return_value=child)
    process._close_connection = AsyncMock()
    process._clean = Mock()
    cancelled = []

    async def waiting():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    async def exercise():
        with pytest.raises(SC2LaunchError, match='before its API became available') as error:
            await asyncio.wait_for(process.__aenter__(), 2)
        assert error.value.returncode == returncode
        assert error.value.pid == 1234
        assert error.value.executable == '/fixture/SC2'

    with patch('sc2.sc2process.SC2Process._connect', side_effect=waiting):
        asyncio.run(exercise())
    assert cancelled == [True]
    process._close_connection.assert_awaited_once()
    process._clean.assert_called_once()


def test_connect_preserves_upstream_success_and_errors():
    process = OwnedSC2Process.__new__(OwnedSC2Process)
    process._process = Mock()
    process._process.poll.return_value = None
    websocket = object()
    with patch('sc2.sc2process.SC2Process._connect', new_callable=AsyncMock, return_value=websocket):
        assert asyncio.run(process._connect()) is websocket
    with patch('sc2.sc2process.SC2Process._connect', new_callable=AsyncMock, side_effect=OSError('handshake')):
        with pytest.raises(OSError, match='handshake'):
            asyncio.run(process._connect())


def test_cancelled_connect_drains_upstream_task():
    process = OwnedSC2Process.__new__(OwnedSC2Process)
    process._process = Mock()
    process._process.poll.return_value = None
    drained = []

    async def waiting():
        try:
            await asyncio.Event().wait()
        finally:
            drained.append(True)

    async def exercise():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(process._connect(), .02)

    with patch('sc2.sc2process.SC2Process._connect', side_effect=waiting):
        asyncio.run(exercise())
    assert drained == [True]
