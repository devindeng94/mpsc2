import pytest
from s2clientprotocol import raw_pb2 as raw_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from mpsc2.smoke import inspect_observation, team_of


def observation(pid):
    response = sc_pb.Response()
    obs = response.observation.observation
    obs.player_common.player_id = pid
    for owner in range(1, 5):
        alliance = raw_pb.Self if owner == pid else raw_pb.Ally if team_of(owner) == team_of(pid) else raw_pb.Enemy
        for _ in range(6):
            obs.raw_data.units.add(owner=owner, alliance=alliance)
    return response


@pytest.mark.parametrize("pid", [1, 2, 3, 4])
def test_all_perspectives(pid):
    assert inspect_observation(observation(pid), pid)["units_by_owner"] == {1: 6, 2: 6, 3: 6, 4: 6}


def test_ffa_must_not_pass_as_team_game():
    response = observation(1)
    response.observation.observation.raw_data.units[6].alliance = raw_pb.Enemy
    with pytest.raises(AssertionError, match="expected"):
        inspect_observation(response, 1)


def test_missing_fourth_army_fails():
    response = observation(1)
    del response.observation.observation.raw_data.units[-6:]
    with pytest.raises(AssertionError, match="owner 4"):
        inspect_observation(response, 1)


def test_fog_requires_hidden_opponents_and_visible_teammates():
    response = observation(1)
    with pytest.raises(AssertionError, match="outside initial team vision"):
        inspect_observation(response, 1, all_visible=False)
    del response.observation.observation.raw_data.units[12:]
    assert inspect_observation(response, 1, all_visible=False)["units_by_owner"] == {1: 6, 2: 6}
