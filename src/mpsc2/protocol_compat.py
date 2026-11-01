"""Per-client translation of verified live SC2 ability tables.

Legacy and updated content use different IDs from burnysc2 7.3.0.
Keep the upstream enums and bot API unchanged, translating only the owned
client's protocol boundary. Never map an ability by a guessed numeric offset.
"""
from sc2.client import Client


def detect_ability_layout(data):
    """Recognize content by API names, independent of the executable/launch hash."""
    from .versions import WINDOWS_98370, LEGACY_410_ABILITY_REMAPS
    abilities = {a.ability_id: (a.link_name, a.button_name) for a in data.abilities}
    shifted = WINDOWS_98370.ability_remaps
    if all(abilities.get(wire) == (link, button) for wire, _, link, button in shifted):
        return 'shifted-4135', shifted
    if all(abilities.get(python) == (link, button) for _, python, link, button in shifted):
        return 'canonical-4132', ()
    if (max(abilities, default=0) == 3800 and
            all(abilities.get(wire) == (link, button) for wire, _, link, button in LEGACY_410_ABILITY_REMAPS)):
        return 'legacy-4.10-3800', LEGACY_410_ABILITY_REMAPS
    raise RuntimeError('Unrecognized SC2 ability layout; executable version and launch data hash '
                       'do not identify the loaded game content')


def _translate(message, mapping, blocked=()):
    for field, value in message.ListFields():
        if field.type == field.TYPE_MESSAGE:
            repeated = field.is_repeated if hasattr(field, 'is_repeated') else field.label == field.LABEL_REPEATED
            for child in value if repeated else (value,):
                _translate(child, mapping, blocked)
        elif field.name in ('ability_id', 'remaps_to_ability_id') and field.type != field.TYPE_BOOL:
            if value in blocked:
                raise RuntimeError(f'Unmapped engine ability {value} conflicts with the pinned Python ability table')
            if value in mapping:
                setattr(message, field.name, mapping[value])


class ProfileClient(Client):
    def __init__(self, ws, *, ability_remaps=(), detect_layout=False):
        super().__init__(ws)
        self.detect_layout = detect_layout
        self.ability_layout = None
        self._set_remaps(ability_remaps)

    def _set_remaps(self, ability_remaps):
        self.ability_remaps = ability_remaps
        self._from_engine = {wire: python for wire, python, _, _ in ability_remaps}
        self._to_engine = {python: wire for wire, python, _, _ in ability_remaps}
        self._collisions = self._to_engine.keys() - self._from_engine.keys()
        self._outgoing_collisions = self._from_engine.keys() - self._to_engine.keys()

    async def _execute(self, **kwargs):
        if not self.ability_remaps and not self.detect_layout:
            return await super()._execute(**kwargs)
        outgoing = {}
        for name, message in kwargs.items():
            copy = type(message)()
            copy.CopyFrom(message)
            _translate(copy, self._to_engine, self._outgoing_collisions)
            outgoing[name] = copy
        response = await super()._execute(**outgoing)
        if self.detect_layout and response.HasField('data') and response.data.abilities:
            layout, remaps = detect_ability_layout(response.data)
            if self.ability_layout is not None and self.ability_layout != layout:
                raise RuntimeError('SC2 ability layout changed during the session')
            self.ability_layout = layout
            self._set_remaps(remaps)
        if not self.ability_remaps:
            return response
        normalized = type(response)()
        normalized.CopyFrom(response)
        if response.HasField('data') and response.data.abilities:
            abilities = {a.ability_id: a for a in response.data.abilities}
            for wire, _, link, button in self.ability_remaps:
                actual = abilities.get(wire)
                if actual is None or (actual.link_name, actual.button_name) != (link, button):
                    raise RuntimeError(f'Engine ability metadata does not match the selected profile at ID {wire}')
            # Reserved/cancel slots now occupy old numeric IDs. Do not let
            # those entries replace the relocated abilities in GameData.
            del normalized.data.abilities[:]
            normalized.data.abilities.extend(a for a in response.data.abilities
                                             if a.ability_id not in self._collisions)
        _translate(normalized, self._from_engine, self._collisions)
        return normalized
