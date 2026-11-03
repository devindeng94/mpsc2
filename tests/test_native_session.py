import asyncio
from unittest.mock import patch

import pytest

from mpsc2.native_session import NativeFourSession, validate_executable, wait_record


def test_bridge_refuses_unrecognized_engine(tmp_path):
    executable = tmp_path / "SC2"
    executable.write_bytes(b"different executable")
    with patch("mpsc2.native_session.platform.system", return_value="Darwin"):
        with pytest.raises(RuntimeError, match="Unsupported SC2 executable"):
            validate_executable(executable)


def test_missing_historical_macos_build_explains_update_failure(tmp_path):
    with patch('mpsc2.native_session.platform.system', return_value='Darwin'):
        with pytest.raises(FileNotFoundError, match='An SC2 update may have removed this build'):
            validate_executable(tmp_path / 'Versions/Base96883/SC2.app/Contents/MacOS/SC2')


def test_bridge_detects_failed_host_without_waiting(tmp_path):
    class Exited:
        returncode = 9
        def poll(self):
            return self.returncode

    with pytest.raises(RuntimeError, match="SC2 process exited"):
        asyncio.run(wait_record(tmp_path, "held.json", 10, Exited()))


def test_bridge_propagates_native_readiness_failure(tmp_path):
    (tmp_path / "bridge-error.json").write_text('{"error":"four-player readiness timed out"}')
    with pytest.raises(RuntimeError, match="readiness timed out"):
        asyncio.run(wait_record(tmp_path, "four-ready.json", 10))


def test_reused_output_preserves_previous_evidence(tmp_path):
    map_path = tmp_path / "fixture.SC2Map"
    map_path.write_bytes(b"map")
    output = tmp_path / "previous"
    output.mkdir()
    report = output / "native-session.json"
    report.write_text('{"important":"prior measurement"}')
    session = NativeFourSession(map_path, output=output)
    with pytest.raises(FileExistsError, match="fresh output"):
        asyncio.run(session.__aenter__())
    assert report.read_text() == '{"important":"prior measurement"}'
