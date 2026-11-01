import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from s2clientprotocol import sc2api_pb2 as api, raw_pb2, query_pb2
from sc2.ids.ability_id import AbilityId
from sc2.unit import UnitOrder

from mpsc2.protocol_compat import ProfileClient
from mpsc2.versions import WINDOWS_98370, LEGACY_410_ABILITY_REMAPS


def metadata():
    response = api.Response()
    # An old numeric slot now describes an unrelated reserved ability.
    response.data.abilities.add(ability_id=4132, link_name='SalvageEffect', button_name='')
    for wire, _, link, button in WINDOWS_98370.ability_remaps:
        response.data.abilities.add(ability_id=wire, link_name=link, button_name=button)
    response.data.abilities.add(ability_id=16, link_name='Move', button_name='Move')
    return response


def client():
    return ProfileClient(object(), ability_remaps=WINDOWS_98370.ability_remaps)


def test_shifted_gather_order_uses_existing_enum_without_mutating_upstream():
    response = metadata()
    original = response.SerializeToString()
    members = dict(AbilityId.__members__)
    async def exercise():
        c = client()
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response):
            data = await c.get_game_data()
        obs = api.Response()
        obs.observation.observation.raw_data.units.add(tag=17).orders.add(ability_id=4135, progress=0.25)
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=obs):
            normalized = await c._execute(observation=api.RequestObservation())
        order = UnitOrder.from_proto(normalized.observation.observation.raw_data.units[0].orders[0],
                                     SimpleNamespace(game_data=data))
        assert order.ability.id is AbilityId.WORKERSTOPIDLEABILITYVESPENE_GATHER
        assert order.ability.link_name == 'WorkerStopIdleAbilityVespene'
        assert order.progress == 0.25
        assert obs.observation.observation.raw_data.units[0].orders[0].ability_id == 4135
        for wire, python, link, button in WINDOWS_98370.ability_remaps:
            assert (data.abilities[python].link_name, data.abilities[python].button_name) == (link, button)
        assert data.abilities[16].id is AbilityId.MOVE_MOVE
    asyncio.run(exercise())
    assert response.SerializeToString() == original
    assert dict(AbilityId.__members__) == members


@pytest.mark.parametrize('canonical,wire', [(4121, 4124), (4124, 4127), (4126, 4129), (4132, 4135), (16, 16)])
def test_commands_and_placement_queries_translate_once_without_changing_callers(canonical, wire):
    action = api.RequestAction()
    action.actions.add().action_raw.unit_command.CopyFrom(raw_pb2.ActionRawUnitCommand(ability_id=canonical, unit_tags=[17]))
    query = query_pb2.RequestQuery()
    query.placements.add(ability_id=canonical)
    async def exercise():
        c = client()
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=api.Response()) as execute:
            await c._execute(action=action)
            assert execute.call_args.kwargs['action'].actions[0].action_raw.unit_command.ability_id == wire
            await c._execute(query=query)
            assert execute.call_args.kwargs['query'].placements[0].ability_id == wire
    asyncio.run(exercise())
    assert action.actions[0].action_raw.unit_command.ability_id == canonical
    assert query.placements[0].ability_id == canonical


def test_available_abilities_preserve_existing_constants_in_both_query_apis():
    response = api.Response()
    row = response.query.abilities.add(unit_tag=17)
    row.abilities.add(ability_id=4129)
    async def exercise():
        c = client()
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response):
            assert await c.query_available_abilities([SimpleNamespace(tag=17)]) == [[AbilityId.ENERGYRECHARGE_ENERGYRECHARGE]]
            assert await c.query_available_abilities_with_tag([SimpleNamespace(tag=17)]) == {17: {AbilityId.ENERGYRECHARGE_ENERGYRECHARGE}}
    asyncio.run(exercise())


@pytest.mark.parametrize('change', ['wrong_name', 'missing_id'])
def test_changed_ability_metadata_is_refused(change):
    response = metadata()
    if change == 'wrong_name':
        response.data.abilities[-2].link_name = 'DifferentAbility'
    else:
        del response.data.abilities[-2]
    with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response):
        with pytest.raises(RuntimeError, match='metadata does not match'):
            asyncio.run(client().get_game_data())


def test_unmapped_colliding_order_fails_instead_of_becoming_a_different_ability():
    response = api.Response()
    response.observation.observation.raw_data.units.add().orders.add(ability_id=4121)
    with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response):
        with pytest.raises(RuntimeError, match='Unmapped engine ability 4121'):
            asyncio.run(client()._execute(observation=api.RequestObservation()))


def test_other_profiles_keep_the_original_protocol_objects():
    response = metadata()
    request = api.RequestData(ability_id=True)
    with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response) as execute:
        assert asyncio.run(ProfileClient(object())._execute(data=request)) is response
    assert execute.call_args.kwargs['data'] is request


def layout_metadata(layout):
    response = api.Response()
    remaps = LEGACY_410_ABILITY_REMAPS if layout == 'legacy-4.10-3800' else WINDOWS_98370.ability_remaps
    for wire, python, link, button in remaps:
        response.data.abilities.add(ability_id=python if layout == 'canonical-4132' else wire,
                                    link_name=link, button_name=button)
    return response


@pytest.mark.parametrize('layout', ['legacy-4.10-3800', 'canonical-4132', 'shifted-4135'])
def test_auto_selection_uses_live_metadata_and_reverses_only_that_layout(layout):
    response = layout_metadata(layout)
    canonical = 3966 if layout == 'legacy-4.10-3800' else 4132
    expected = 3797 if layout == 'legacy-4.10-3800' else 4135 if layout == 'shifted-4135' else 4132
    async def exercise():
        c = ProfileClient(object(), detect_layout=True)
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response):
            data = await c.get_game_data()
        assert c.ability_layout == layout
        assert data.abilities[canonical].exact_id is AbilityId(canonical)
        request = api.RequestAction()
        request.actions.add().action_raw.unit_command.ability_id = canonical
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=api.Response()) as execute:
            await c._execute(action=request)
        assert execute.call_args.kwargs['action'].actions[0].action_raw.unit_command.ability_id == expected
    asyncio.run(exercise())


def test_clients_with_different_game_data_cannot_change_each_others_translation():
    async def exercise():
        clients = [ProfileClient(object(), detect_layout=True) for _ in range(3)]
        layouts = ['shifted-4135', 'canonical-4132', 'legacy-4.10-3800']
        for c, layout in zip(clients, layouts):
            with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=layout_metadata(layout)):
                await c.get_game_data()
        assert clients[0]._to_engine[4132] == 4135
        assert clients[1]._to_engine == {}
        assert clients[2]._to_engine[3966] == 3797
    asyncio.run(exercise())


def test_unknown_and_changing_live_layouts_are_refused():
    async def exercise():
        c = ProfileClient(object(), detect_layout=True)
        response = layout_metadata('legacy-4.10-3800')
        response.data.abilities[-1].link_name = 'Unknown'
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=response):
            with pytest.raises(RuntimeError, match='Unrecognized SC2 ability layout'):
                await c.get_game_data()
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=layout_metadata('canonical-4132')):
            await c.get_game_data()
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=layout_metadata('shifted-4135')):
            with pytest.raises(RuntimeError, match='changed during the session'):
                await c.get_game_data()
    asyncio.run(exercise())


def test_newer_constant_cannot_trigger_an_unrelated_legacy_ability():
    async def exercise():
        c = ProfileClient(object(), detect_layout=True)
        with patch('sc2.client.Client._execute', new_callable=AsyncMock, return_value=layout_metadata('legacy-4.10-3800')):
            await c.get_game_data()
        request = api.RequestAction()
        request.actions.add().action_raw.unit_command.ability_id = AbilityId.LOADOUTSPRAY_LOADOUTSPRAY1.value
        with patch('sc2.client.Client._execute', new_callable=AsyncMock) as execute:
            with pytest.raises(RuntimeError, match='conflicts with the pinned Python ability table'):
                await c._execute(action=request)
        execute.assert_not_awaited()
    asyncio.run(exercise())
