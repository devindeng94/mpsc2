# Architecture

MPSC2 preserves the python-sc2 policy API and adds local multiplayer orchestration.

```mermaid
flowchart TD
    policies[Distinct BotAI instances in one Python event loop] --> launcher[MPSC2 launcher and team mapping]
    launcher --> stock[Standard one/two-player route: burnysc2]
    launcher --> session[Bundled scenario: multiplayer session]
    session --> c1[Client 1 / WebSocket / SC2 process]
    session --> c2[Client 2 / WebSocket / SC2 process]
    session --> cn[Client N / WebSocket / SC2 process]
    c1 <--> game[Native multiplayer simulation]
    c2 <--> game
    cn <--> game
```

Each participant has its own SC2 process, socket, native player ID, observations
and actions. BotAI callbacks share the calling Python event loop; independent
game clients do not imply independent Python policy processes. Offload blocking
inference if it would stall other callbacks.

## Match lifecycle

1. Validate players, teams, supported options and the bundled map checksum.
2. Prepare a match-specific map with player slots, team setup and ending rules.
3. Start owned SC2 processes with separate API/network ports. Two-client
   scenarios use stock hosting. Three through eight load the native helpers.
4. Join every participant and record its actual native ID. Join order can differ
   from input order; team assignments and result lists use the recorded mapping.
5. Complete the map handshake, check ownership/alliances, and initialize BotAI.
6. Run callbacks and actions. Stepped games advance clients together; realtime
   games request observations independently and send no `Step` requests.
7. Collect native results, optionally save a replay, and release owned resources.
   An exception or cancellation propagates and also triggers cleanup.

## Native helpers

The supported engine's stock API rejects more than two independent participants.
The host-only lobby bridge completes a verified host transition, distributes
local discovery traffic, and waits for every participant's native readiness.
It changes process-local lobby data.

A separate observation guard runs in every 3–8-client process. Base96883's
private opponent-upgrade lookup assumes `3-player_id`; IDs ≥4 underflow.
The guard changes seven bytes on a private executable-memory page to skip that
lookup. Public own-upgrade data and the simulation remain intact. Selected-player
replay views with IDs ≥4 use the same guard on this build.

These helpers require the exact executable hash, UUID and expected runtime
instructions. Unknown binaries are refused; the installation is unchanged.
See [MPSC2-001](known-issues.md) for the diagnosis and measured fix.

## Maps and output

The bundled arena and economy map contain setup/alliance and native ending rules;
a renamed ladder map cannot provide those rules automatically. See
[map sources and provenance](../maps/README.md).

Each match stores a generated map, result metadata, native IDs/ports, and protocol
journals in a fresh output directory. Replays are optional. Raw run artifacts are
local outputs; public validation summaries live in `evidence/`. There is no native
process reuse, remote-client coordinator, learning algorithm or Gym/PettingZoo
adapter in this alpha.
