from ..ai import EnemyAI
from ..blueprints import WEAPONS, SHIPS
from ..state import ShipState, SYS_SHIELDS, SYS_ENGINES, SYS_WEAPONS


def _make_ships():
    attacker = ShipState.from_config(1, SHIPS["REBEL_FIGHTER"])
    target   = ShipState.from_config(0, SHIPS["KESTREL_A"])
    return attacker, target


AI = EnemyAI()


class TestPrioritizeSystem:
    def test_laser_targets_shields_when_up(self):
        """LASER_BURST_1 vs 2-layer-shielded player → target shields."""
        attacker, target = _make_ships()
        target.shield_layers = 2
        targets = AI.choose_weapon_targets(attacker, target)
        assert targets[0] == SYS_SHIELDS

    def test_laser_targets_weapons_when_shields_down(self):
        """LASER_BURST_1 vs 0-layer player with healthy weapon sys → target weapons."""
        attacker, target = _make_ships()
        target.shield_layers = 0
        targets = AI.choose_weapon_targets(attacker, target)
        assert targets[0] == SYS_WEAPONS

    def test_laser_targets_engines_when_weapons_destroyed(self):
        """LASER vs shields-down, weapons-destroyed player → target engines."""
        attacker, target = _make_ships()
        target.shield_layers = 0
        target.systems[SYS_WEAPONS].health_current = 0.0
        targets = AI.choose_weapon_targets(attacker, target)
        assert targets[0] == SYS_ENGINES

    def test_missile_goes_for_weapons_ignoring_shields(self):
        """PIRATE_ASSAULT has MISSILE_1 — targets weapons even when player has shields."""
        attacker = ShipState.from_config(1, SHIPS["PIRATE_ASSAULT"])
        target   = ShipState.from_config(0, SHIPS["KESTREL_A"])
        target.shield_layers = 3
        targets = AI.choose_weapon_targets(attacker, target)
        # PIRATE_ASSAULT weapons: LASER_HEAVY_1 (slot 0), MISSILE_1 (slot 1)
        assert targets[1] == SYS_WEAPONS   # missile slot

    def test_beam_targets_weapons_not_shields(self):
        """Beam weapon AI skips shields (beams deal 0 through shields)."""
        from ..blueprints import WEAPONS, WeaponType, DamageSpec, WeaponBlueprint
        from ..state import WeaponState
        attacker, target = _make_ships()
        # Replace attacker weapon with a beam
        bp = WEAPONS["BEAM_HALBERD"]
        attacker.weapons[0] = WeaponState(
            blueprint_name="BEAM_HALBERD",
            cooldown_current=0.0,
            cooldown_max=bp.cooldown,
            powered=True,
        )
        target.shield_layers = 2
        targets = AI.choose_weapon_targets(attacker, target)
        assert targets[0] == SYS_WEAPONS   # beam skips shield targeting

    def test_unpowered_weapon_returns_minus_one(self):
        attacker, target = _make_ships()
        attacker.weapons[0].powered = False
        targets = AI.choose_weapon_targets(attacker, target)
        assert targets[0] == -1
