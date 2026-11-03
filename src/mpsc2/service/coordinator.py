"""Match lifecycle and lockstep coordination, independent of SC2 binary layout."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from s2clientprotocol import sc2api_pb2 as api
from . import multiplayer_pb2 as pb
from .contract import (GAMEPLAY, READS, ServiceError, canonical, copy, operation,
                       present, require, validate_action, validate_read, validate_spec)


class Match:
    def __init__(self, match_id, spec, backend, report, *, lease_seconds=3600, cache_bytes=128*1024*1024):
        self.id, self.generation = match_id, uuid.uuid4().hex
        self.spec, self.backend, self.report = copy(spec), backend, copy(report)
        self.slots = [p.slot_id for p in spec.players if p.kind == pb.PLAYER_AGENT]
        self.tokens = {s: secrets.token_hex(32).encode('ascii') for s in self.slots}
        self.expires = int((time.time() + lease_seconds) * 1000)
        self.state = pb.MATCH_PREPARING
        self.epoch, self.loop = 0, None
        self.reason, self.terminated, self.truncated = '', False, False
        self.error = None
        self.observations, self.submissions, self.results, self.steps = {}, {}, {}, {}
        self.futures = {}
        self.lock = asyncio.Lock()
        self.lifecycle_lock = asyncio.Lock()
        self.round_task = self.timer = None
        self.lease_task = asyncio.create_task(self._lease(lease_seconds))
        self.cache_bytes, self.used_bytes = cache_bytes, 0

    def reference(self):
        return pb.MatchRef(match_id=self.id, generation=self.generation)

    def verify_ref(self, ref):
        require(ref.match_id == self.id and ref.generation == self.generation,
                'Wrong match generation', pb.ERROR_STALE_GENERATION)

    def snapshot(self):
        result = pb.MatchSnapshot(match=self.reference(), state=self.state, current_epoch=self.epoch,
                                 terminated=self.terminated, truncated=self.truncated, reason=self.reason)
        result.players.extend(self.backend.bindings)
        if self.loop is not None:
            result.game_loop = self.loop
        if self.terminated and self.observations:
            result.player_results.extend(next(iter(self.observations.values())).observation.player_result)
        return result

    async def prepare(self):
        try:
            await self.backend.prepare()
            require(self.state == pb.MATCH_PREPARING, 'Preparation was closed', pb.ERROR_INVALID_STATE)
            self._check_bindings()
            self.state = pb.MATCH_PREPARED
            result = pb.PreparedMatch(match_id=self.id, generation=self.generation, engine=self.backend.identity,
                                      accepted_spec=self.spec, capabilities=self.report.capabilities,
                                      players=self.backend.bindings, lease_expires_at_unix_ms=self.expires,
                                      materialized_map=self.backend.materialized_map)
            for slot, token in self.tokens.items():
                result.credentials.add(slot_id=slot, bearer_token=token, expires_at_unix_ms=self.expires)
            return result
        except BaseException:
            await self.close('Preparation failed')
            raise

    async def start(self):
        async with self.lifecycle_lock:
            if self.state in (pb.MATCH_RUNNING, pb.MATCH_ENDED):
                return self.snapshot()
            require(self.state == pb.MATCH_PREPARED, 'Match is not prepared', pb.ERROR_INVALID_STATE)
            self.state = pb.MATCH_STARTING
            try:
                observations = await self.backend.start()
                require(self.state == pb.MATCH_STARTING, 'Start interrupted', pb.ERROR_INVALID_STATE)
                self._commit_observations(observations)
                self.state = pb.MATCH_ENDED if self.terminated else pb.MATCH_RUNNING
                if self.state == pb.MATCH_RUNNING:
                    self._deadline()
                return self.snapshot()
            except BaseException as exc:
                await self.fail(pb.ERROR_ROSTER_MISMATCH, f'Start failed: {exc}')
                raise

    def _check_bindings(self):
        bindings = self.backend.bindings
        agents = [p for p in self.spec.players if p.kind == pb.PLAYER_AGENT]
        require([b.slot_id for b in bindings] == self.slots,
                'Backend bindings must follow declared agent slot order', pb.ERROR_ROSTER_MISMATCH)
        require(all(b.team_id == p.team_id and b.transport == self.spec.transport for b, p in zip(bindings, agents)),
                'Backend changed the team or transport assignment', pb.ERROR_ROSTER_MISMATCH)
        require(all(b.engine_instance_id for b in bindings) and len({b.engine_instance_id for b in bindings}) == len(bindings),
                'Engine instance bindings are not independent', pb.ERROR_ROSTER_MISMATCH)

    def _commit_observations(self, responses, previous=None):
        self._check_bindings()
        require(len(responses) == len(self.slots), 'Missing observations', pb.ERROR_ROSTER_MISMATCH)
        ids = [b.native_player_id for b in self.backend.bindings]
        require(len(set(ids)) == len(self.slots) and all(ids), 'Native IDs are not independent', pb.ERROR_ROSTER_MISMATCH)
        loops, tables = [], []
        for slot, pid, response in zip(self.slots, ids, responses):
            require(response.HasField('observation') and not response.error, 'Engine observation failed', pb.ERROR_UNCERTAIN_EXECUTION)
            require(response.observation.observation.player_common.player_id == pid,
                    'Observation belongs to another player', pb.ERROR_ROSTER_MISMATCH)
            loops.append(response.observation.observation.game_loop)
            tables.append({p.player_id: p.result for p in response.observation.player_result})
        terminal = any(tables)
        if terminal:
            require(all(r.status == api.ended for r in responses), 'Terminal results require every native client to be ended', pb.ERROR_UNCERTAIN_EXECUTION)
            require(all(result in (api.Victory, api.Defeat, api.Tie) for t in tables for result in t.values()),
                    'Incomplete native outcomes', pb.ERROR_UNCERTAIN_EXECUTION)
            require(all(t == tables[0] and set(t) == set(ids) for t in tables), 'Clients disagree on terminal results', pb.ERROR_UNCERTAIN_EXECUTION)
        if self.spec.clock == pb.CLOCK_STEPPED:
            if terminal:
                # Terminal observations are asynchronous completion records,
                # not another synchronized decision boundary. SC2 keeps advancing
                # some clients while GameOver propagates. Preserve actual frames;
                # require ended status and identical full outcomes above.
                if previous is not None:
                    require(min(loops) >= previous, 'Terminal frame moved backwards', pb.ERROR_UNCERTAIN_EXECUTION)
            else:
                require(len(set(loops)) == 1, f'Clients disagree on game loop: {loops}', pb.ERROR_UNCERTAIN_EXECUTION)
                if previous is not None:
                    require(loops[0] == previous + self.spec.step_count,
                            'Unexpected simulation advancement', pb.ERROR_UNCERTAIN_EXECUTION)
            self.loop = loops[0] if len(set(loops)) == 1 else None
        self.observations = {s: copy(r) for s, r in zip(self.slots, responses)}
        self.terminated = terminal

    def _future(self, epoch):
        if epoch not in self.futures:
            self.futures[epoch] = asyncio.get_running_loop().create_future()
        return self.futures[epoch]

    def _deadline(self):
        if self.spec.clock != pb.CLOCK_STEPPED:
            return
        if self.timer:
            self.timer.cancel()
        self.timer = asyncio.create_task(self._expire_round(self.epoch))

    async def _expire_round(self, epoch):
        await asyncio.sleep(self.spec.round_timeout_ms / 1000)
        if self.state == pb.MATCH_RUNNING and self.epoch == epoch:
            await self.fail(pb.ERROR_ROUND_TIMEOUT, 'Missing player or engine round deadline exceeded')

    async def _lease(self, seconds):
        await asyncio.sleep(seconds)
        await self.close('Match lease expired')

    def _running(self):
        if self.error:
            raise self.error
        require(self.state == pb.MATCH_RUNNING, 'Match is not running', pb.ERROR_INVALID_STATE)

    async def submit(self, slot, turn):
        present(turn, 'epoch', 'expected_game_loop', 'actions')
        validate_action(turn.actions)
        key, fingerprint = (turn.epoch, slot), canonical(turn)
        async with self.lock:
            if key in self.submissions:
                require(self.submissions[key][0] == fingerprint, 'Conflicting turn', pb.ERROR_ROUND_CONFLICT)
                return pb.TurnAccepted(epoch=turn.epoch)
            self._running()
            require(turn.epoch == self.epoch and turn.expected_game_loop == self.loop,
                    'Stale/future epoch or wrong game loop', pb.ERROR_ROUND_CONFLICT)
            require(self.used_bytes + len(fingerprint) <= self.cache_bytes, 'Match history limit reached', pb.ERROR_RESOURCE_LIMIT)
            self.used_bytes += len(fingerprint)
            self.submissions[key] = (fingerprint, copy(turn.actions))
            self._future(self.epoch)
            if all((self.epoch, s) in self.submissions for s in self.slots):
                self.round_task = asyncio.create_task(self._round(self.epoch))
            return pb.TurnAccepted(epoch=turn.epoch)

    async def await_turn(self, slot, epoch):
        require(epoch <= self.epoch, 'Future epoch', pb.ERROR_ROUND_CONFLICT)
        require((epoch, slot) in self.submissions, 'Submit your turn before awaiting it', pb.ERROR_INVALID_STATE)
        await asyncio.shield(self._future(epoch))
        if (epoch, slot) not in self.results:
            self._running()
            raise ServiceError(pb.ERROR_INVALID_STATE, 'Round did not complete')
        return copy(self.results[epoch, slot])

    async def _round(self, epoch):
        async with self.lock:
            if self.state != pb.MATCH_RUNNING:
                return
            before, phase = self.loop, 'actions'
            try:
                if self.spec.transport == pb.TRANSPORT_JOINT_TURN:
                    actions = await asyncio.gather(*(self.backend.request(s, api.Request(action=self.submissions[epoch, s][1])) for s in self.slots))
                    require(all(a.HasField('action') and not a.error for a in actions), 'Action response failed', pb.ERROR_PARTIAL_DISPATCH)
                else:
                    actions = [api.Response(action=api.ResponseAction()) for _ in self.slots]
                phase = 'advance'
                steps = await self.backend.advance_all(self.spec.step_count)
                require(all(s.HasField('step') and not s.error for s in steps), 'Step failed', pb.ERROR_UNCERTAIN_EXECUTION)
                observations = await self.backend.observe_all()
                self._running()  # A deadline or disconnect may have closed the backend.
                self._commit_observations(observations, before)
                results = [pb.TurnResult(epoch=epoch, previous_game_loop=before, game_loop=o.observation.observation.game_loop,
                                        action_result=a.action, observation=o.observation,
                                        terminated=self.terminated, truncated=False) for a, o in zip(actions, observations)]
                size = sum(r.ByteSize() for r in results)
                require(self.used_bytes + size <= self.cache_bytes, 'Match result cache exhausted', pb.ERROR_RESOURCE_LIMIT)
                self.used_bytes += size
                for slot, result, step in zip(self.slots, results, steps):
                    self.results[epoch, slot] = result
                    if self.spec.transport == pb.TRANSPORT_SC2_COMPAT:
                        self.steps[epoch, slot] = copy(step)
                self.epoch += 1
                if self.terminated:
                    self.state = pb.MATCH_ENDED
                    if self.timer:
                        self.timer.cancel()
                else:
                    self._deadline()
                self._future(epoch).set_result(True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = exc.proto.code if isinstance(exc, ServiceError) else (pb.ERROR_PARTIAL_DISPATCH if phase == 'actions' else pb.ERROR_UNCERTAIN_EXECUTION)
                await self.fail(code, f'Round failed during {phase}: {exc}')

    async def read(self, slot, request):
        validate_read(request, self.loop, realtime=self.spec.clock == pb.CLOCK_REALTIME)
        if self.spec.clock == pb.CLOCK_REALTIME:
            require(self.state in (pb.MATCH_RUNNING, pb.MATCH_ENDED), 'Match unavailable', pb.ERROR_INVALID_STATE)
            return await self._realtime_request(slot, request)
        async with self.lock:
            require(self.state in (pb.MATCH_RUNNING, pb.MATCH_ENDED), 'Match unavailable', pb.ERROR_INVALID_STATE)
            if operation(request) == 'observation' and self.spec.clock == pb.CLOCK_STEPPED:
                response = copy(self.observations[slot])
                if request.HasField('id'):
                    response.id = request.id
                return response
            return await self.backend.request(slot, request)

    async def compat(self, slot, request):
        name = operation(request)
        require(name in GAMEPLAY, 'Message belongs to the controller or is unsupported', pb.ERROR_UNSUPPORTED_MESSAGE)
        if name in ('leave_game', 'quit'):
            await self.close('Participant left the match')
            return api.Response(**{name: getattr(api, 'ResponseLeaveGame' if name == 'leave_game' else 'ResponseQuit')()}, status=api.quit)
        if name == 'step':
            require(self.spec.clock == pb.CLOCK_STEPPED, 'Step is unavailable in realtime', pb.ERROR_UNSUPPORTED_MESSAGE)
            require(request.step.count == self.spec.step_count, 'Step count differs from negotiated count', pb.ERROR_ROUND_CONFLICT)
            epoch = self.epoch
            await self.submit(slot, pb.SubmitTurn(epoch=epoch, expected_game_loop=self.loop, actions=api.RequestAction()))
            await self.await_turn(slot, epoch)
            return copy(self.steps[epoch, slot])
        if name in READS:
            return await self.read(slot, request)
        if name == 'action':
            validate_action(request.action)
        if self.spec.clock == pb.CLOCK_REALTIME:
            require(self.state == pb.MATCH_RUNNING or (self.state == pb.MATCH_ENDED and name == 'save_replay'),
                    'Match unavailable', pb.ERROR_INVALID_STATE)
            return await self._realtime_request(slot, request)
        async with self.lock:
            require(self.state in (pb.MATCH_RUNNING, pb.MATCH_ENDED) and (self.state == pb.MATCH_RUNNING or name == 'save_replay'),
                    'Match unavailable', pb.ERROR_INVALID_STATE)
            # A player that already voted Step must not change its pending round.
            require((self.epoch, slot) not in self.submissions, 'Action after Step vote', pb.ERROR_ROUND_CONFLICT)
            try:
                return await self.backend.request(slot, request)
            except Exception as exc:
                await self.fail(pb.ERROR_UNCERTAIN_EXECUTION, f'Engine request failed: {exc}')
                raise self.error from exc

    async def _realtime_request(self, slot, request):
        try:
            response = await self.backend.request(slot, request)
            if response.HasField('observation'):
                binding = next(b for b in self.backend.bindings if b.slot_id == slot)
                require(response.observation.observation.player_common.player_id == binding.native_player_id,
                        'Realtime observation belongs to another player', pb.ERROR_ROSTER_MISMATCH)
            if response.HasField('observation') and response.observation.player_result:
                async with self.lock:
                    if self.state == pb.MATCH_RUNNING:
                        self._commit_observations(await self.backend.observe_all())
                        if self.terminated:
                            self.state = pb.MATCH_ENDED
            return response
        except Exception as exc:
            code = exc.proto.code if isinstance(exc, ServiceError) else pb.ERROR_UNCERTAIN_EXECUTION
            await self.fail(code, f'Realtime request failed: {exc}')
            raise self.error from exc

    async def fail(self, code, reason):
        if self.state in (pb.MATCH_CLOSED, pb.MATCH_FAILED):
            return
        self.error = ServiceError(code, reason)
        self.state, self.reason, self.truncated = pb.MATCH_FAILED, reason, True
        self._wake()
        await self.backend.close()

    def _wake(self):
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        for future in self.futures.values():
            if not future.done():
                future.set_result(False)

    async def close(self, reason='Closed by controller'):
        if self.state == pb.MATCH_CLOSED:
            return self.snapshot()
        if self.state not in (pb.MATCH_ENDED, pb.MATCH_FAILED):
            self.truncated = True
            self.reason = reason
        self.state = pb.MATCH_CLOSED
        self._wake()
        if self.lease_task is not asyncio.current_task():
            self.lease_task.cancel()
        await self.backend.close()
        if self.round_task and self.round_task is not asyncio.current_task() and not self.round_task.done():
            self.round_task.cancel()
            await asyncio.gather(self.round_task, return_exceptions=True)
        return self.snapshot()


class Coordinator:
    def __init__(self, factory, *, maximum_matches=1, lease_seconds=3600, maximum_records=64, cache_bytes=128*1024*1024):
        self.factory, self.matches = factory, {}
        self.closing = False
        self.maximum_matches, self.lease_seconds = maximum_matches, lease_seconds
        self.maximum_records, self.cache_bytes = maximum_records, cache_bytes

    async def prepare(self, spec):
        require(not self.closing, 'Service is shutting down', pb.ERROR_INVALID_STATE)
        validate_spec(spec)
        require(len(self.matches) < self.maximum_records, 'Service record limit reached; restart after closing matches', pb.ERROR_RESOURCE_LIMIT)
        live = sum(m.state not in (pb.MATCH_FAILED, pb.MATCH_CLOSED) for m in self.matches.values())
        require(live < self.maximum_matches, 'Concurrent match limit reached', pb.ERROR_RESOURCE_LIMIT)
        report = self.factory.probe(spec)
        match_id = uuid.uuid4().hex
        backend = self.factory.create(spec, match_id)
        match = Match(match_id, spec, backend, report, lease_seconds=self.lease_seconds, cache_bytes=self.cache_bytes)
        self.matches[match_id] = match
        try:
            return await match.prepare()
        except BaseException:
            await match.close('Prepare failed')
            raise

    def get(self, reference):
        require(reference.match_id in self.matches, 'Unknown match', pb.ERROR_INVALID_REQUEST)
        match = self.matches[reference.match_id]
        match.verify_ref(reference)
        return match

    async def close(self):
        self.closing = True
        await asyncio.gather(*(m.close('Service shutdown') for m in self.matches.values()))
