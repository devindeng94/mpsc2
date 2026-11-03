# Experimental multiplayer protocol 1.0

The local server and Python clients are implemented in `mpsc2.service`. See
[service setup and coverage](../docs/service.md). The [design RFC](../docs/designs/general-multiplayer-api.md)
explains the backend boundary and remaining engine research.

The protocol keeps Blizzard's `SC2APIProtocol.Request/Response` for ordinary
gameplay and defines two additional endpoint contracts:

- `ControlRequest/ControlResponse`: negotiation, match setup, teams and lifecycle.
- `TurnRequest/TurnResponse`: optional simultaneous-action research rounds.

An authenticated player's endpoint is permanently bound to one native SC2
client. Existing SC2 messages are reused through imports; no Blizzard schema or
generated code is copied into this directory. The `s2clientprotocol` source
directory from [Blizzard's repository](https://github.com/Blizzard/s2client-proto)
is needed for normal compilation:

```sh
protoc -I protocols -I /path/to/s2client-proto \
  --include_imports --descriptor_set_out=/tmp/mpsc2-v1.pb \
  protocols/mpsc2/v1/multiplayer.proto
```

The installed Python dependency also contains the upstream descriptors. The
schema can be validated offline using those descriptors; this avoids requiring
a network checkout and tests compatibility with the installed protocol package:

```sh
python - <<'PY'
from pathlib import Path
from google.protobuf.descriptor_pb2 import FileDescriptorSet
from s2clientprotocol import sc2api_pb2

result, seen = FileDescriptorSet(), set()
def add(file):
    if file.name in seen:
        return
    seen.add(file.name)
    for dependency in file.dependencies:
        add(dependency)
    file.CopyToProto(result.file.add())
add(sc2api_pb2.DESCRIPTOR)
Path('/tmp/mpsc2-upstream.pb').write_bytes(result.SerializeToString())
PY
protoc -I protocols --descriptor_set_in=/tmp/mpsc2-upstream.pb \
  --include_imports --descriptor_set_out=/tmp/mpsc2-v1.pb \
  protocols/mpsc2/v1/multiplayer.proto
protoc -I protocols --descriptor_set_in=/tmp/mpsc2-upstream.pb \
  --encode=mpsc2.v1.ControlRequest protocols/mpsc2/v1/multiplayer.proto \
  < protocols/examples/prepare-2v2.textproto > /tmp/mpsc2-prepare.bin
```

Examples use illustrative installation IDs, map hashes and slot credentials;
they are schema fixtures, not runnable game launch commands. Use the executable examples and registered map hashes in the service guide to launch games.
