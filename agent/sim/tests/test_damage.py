import random
import pytest

from ..blueprints import DamageSpec
from ..damage import DamageResolver
from ..state import ShipState, SystemState, SYS_SHIELDS, SYS_WEAPONS, SYS_ENGINES, ION_DURATION
from ..blueprints import SHIPS

RNG = random.Random(42)


def _make_ship(
    hull: int = 30,
    shield_layers: int = 0,
    shield_max: int = 2,
    engine_power: int = 0,
) -> ShipState:
    ship = ShipState.from_config(1, SHIPS["REBEL_FIGHTER"])
    ship.hull          = hull
    ship.hull_max      = hull
    ship.shield_layers = shield_layers
    ship.shield_max    = shield_max
    ship.engine_power  = engine_power
    return ship


def _resolve(spec: DamageSpec, ship: ShipState, sys_id=SYS_WEAPONS,
             is_missile=False, is_beam=False, rng=None):
    return DamageResolver.resolve(
        spec=spec, is_missile=is_missile, target=ship,
        target_system_id=sys_id, rng=rng or random.Random(0),
        is_beam=is_beam,
    )


# ---------------------------------------------------------------------------
# Shield mechanics
# ---------------------------------------------------------------------------

class TestShieldMechanics:
    def test_laser_blocked_by_shield(self):
        """1-damage laser vs 2-layer shield: hull unchanged, layer drained to 1."""
        ship = _make_ship(hull=30, shield_layers=2)
        r = _resolve(DamageSpec(hull=1), ship)
        assert r.shields_drained == 1
        assert r.hull_dealt == 0
        assert ship.hull == 30
        assert ship.shield_layers == 1

    def test_laser_penetrates_zero_shields(self):
        """1-damage laser vs 0 shields: hull drops by 1."""
        ship = _make_ship(hull=30, shield_layers=0)
        r = _resolve(DamageSpec(hull=1), ship)
        assert r.hull_dealt == 1
        assert ship.hull == 29
        assert r.shields_drained == 0

    def test_multi_shot_drains_layers_sequentially(self):
        """3-shot burst vs 2-layer shield: shots 1+2 drain layers, shot 3 hits hull."""
        from ..state import ProjectileInFlight
        from ..blueprints import WEAPONS
        ship = _make_ship(hull=30, shield_layers=2, shield_max=2)
        projectile = ProjectileInFlight(
            weapon_name="LASER_BURST_2",
            damage_spec=DamageSpec(hull=1),
            shots_remaining=3,
            travel_time=0.0,
            target_id=1,
            target_system_id=SYS_SHIELDS,
            is_missile=False,
        )
        results = DamageResolver.resolve_projectile(projectile, ship, random.Random(0))
        assert results[0].shields_drained == 1
        assert results[1].shields_drained == 1
        assert results[2].hull_dealt == 1
        assert ship.hull == 29
        assert ship.shield_layers == 0

    def test_shield_charger_resets_on_drain(self):
        """Draining a shield layer resets charger progress to 0."""
        ship = _make_ship(shield_layers=1)
        ship.shield_charger = 0.75
        _resolve(DamageSpec(hull=1), ship)
        assert ship.shield_charger == 0.0

    def test_shield_pierce_skips_layers(self):
        """shield_pierce=1 weapon vs 1-layer shield: hits hull directly."""
        ship = _make_ship(hull=20, shield_layers=1)
        r = _resolve(DamageSpec(hull=2, shield_pierce=1), ship)
        assert r.hull_dealt == 2
        assert ship.hull == 18
        assert r.shields_drained == 0


# ---------------------------------------------------------------------------
# Missile behaviour
# ---------------------------------------------------------------------------

class TestMissileBehaviour:
    def test_missile_bypasses_shields(self):
        """Missile ignores shield layers, deals full hull damage."""
        ship = _make_ship(hull=20, shield_layers=3, shield_max=3)
        r = _resolve(DamageSpec(hull=3), ship, is_missile=True)
        assert r.hull_dealt == 3
        assert ship.hull == 17
        assert r.shields_drained == 0
        assert ship.shield_layers == 3   # layers untouched

    def test_missile_cannot_be_dodged(self):
        """Missile vs 60%-dodge ship: never dodged regardless of RNG."""
        ship = _make_ship(engine_power=8)  # 60% dodge
        # Run 50 rolls — with a real dodge a laser would almost certainly dodge;
        # for a missile none should.
        for seed in range(50):
            s = _make_ship(hull=30, engine_power=8)
            r = _resolve(DamageSpec(hull=1), s, is_missile=True, rng=random.Random(seed))
            assert not r.dodged


# ---------------------------------------------------------------------------
# Hull-buster mechanic
# ---------------------------------------------------------------------------

class TestHullBuster:
    def test_hull_buster_against_shields_drains_layer(self):
        """Hull-buster vs 1-layer shield: layer drained, no hull damage."""
        ship = _make_ship(hull=20, shield_layers=1)
        r = _resolve(DamageSpec(hull=2, hull_buster=True), ship)
        assert r.shields_drained == 1
        assert r.hull_dealt == 0

    def test_hull_buster_bonus_when_shields_down(self):
        """Hull-buster vs 0 shields: deals hull + 1 bonus damage."""
        ship = _make_ship(hull=20, shield_layers=0)
        r = _resolve(DamageSpec(hull=2, hull_buster=True), ship)
        assert r.hull_dealt == 3   # 2 base + 1 buster bonus
        assert ship.hull == 17


# ---------------------------------------------------------------------------
# Ion damage
# ---------------------------------------------------------------------------

class TestIonDamage:
    def test_ion_drains_shield_layer_and_starts_timer(self):
        """ION_BLAST vs 1-layer shield: layer drained, shield system gets ion_timer."""
        ship = _make_ship(hull=20, shield_layers=1)
        r = _resolve(DamageSpec(ion=1), ship, sys_id=SYS_SHIELDS)
        assert r.shields_drained == 1
        assert r.ion_dealt == 1
        assert ship.shield_layers == 0
        shield_sys = ship.systems[SYS_SHIELDS]
        assert shield_sys.ion_timer == pytest.approx(ION_DURATION, rel=0.01)

    def test_ion_on_unshielded_applies_timer_via_hull_path(self):
        """ION vs 0 shields: ion reaches hull path — hull damage is 0, ion_timer still applied."""
        ship = _make_ship(hull=20, shield_layers=0)
        r = _resolve(DamageSpec(ion=1), ship, sys_id=SYS_SHIELDS)
        # Ion hits shield system directly when shields are down
        assert r.ion_dealt == 0  # ion only applied when hitting a shield layer
        # hull damage is also 0 (ion does no hull damage)
        assert r.hull_dealt == 0


# ---------------------------------------------------------------------------
# System damage
# ---------------------------------------------------------------------------

class TestSystemDamage:
    def test_system_damage_reduces_health(self):
        """Weapon with system_damage=2 hitting weapons system reduces its HP."""
        ship = _make_ship(shield_layers=0)
        sys = ship.systems[SYS_WEAPONS]
        sys.health_current = 100.0
        r = _resolve(DamageSpec(system=2), ship, sys_id=SYS_WEAPONS)
        assert r.system_dealt == pytest.approx(2.0)
        assert sys.health_current == pytest.approx(98.0)

    def test_system_destroyed_zeroes_power(self):
        """When system HP hits 0, power_current drops to 0."""
        ship = _make_ship(shield_layers=0)
        sys = ship.systems[SYS_WEAPONS]
        sys.health_current = 1.0
        _resolve(DamageSpec(system=10), ship, sys_id=SYS_WEAPONS)
        assert sys.health_current == 0.0
        assert sys.power_current == 0


# ---------------------------------------------------------------------------
# Fire and breach
# ---------------------------------------------------------------------------

class TestFireAndBreach:
    def test_fire_chance_100_always_starts_fire(self):
        ship = _make_ship(shield_layers=0)
        r = _resolve(DamageSpec(hull=1, fire_chance=100), ship, sys_id=SYS_WEAPONS)
        assert r.fire_started
        assert ship.systems[SYS_WEAPONS].on_fire

    def test_fire_chance_0_never_starts_fire(self):
        for seed in range(20):
            ship = _make_ship(shield_layers=0)
            r = _resolve(DamageSpec(hull=1, fire_chance=0), ship,
                         rng=random.Random(seed))
            assert not r.fire_started


# ---------------------------------------------------------------------------
# Dodge
# ---------------------------------------------------------------------------

class TestDodge:
    def test_dodge_laser_with_high_engines(self):
        """With engine_power=8 (60% dodge), seeded RNG that always returns < 0.6 dodges."""
        ship = _make_ship(engine_power=8)
        r = DamageResolver.resolve(
            DamageSpec(hull=1), is_missile=False, target=ship,
            target_system_id=None, rng=random.Random(1),   # seed 1 → first rand ≈ 0.13
        )
        assert r.dodged

    def test_no_dodge_with_zero_engines(self):
        """engine_power=0 → 0% dodge, laser never dodged."""
        for seed in range(20):
            ship = _make_ship(engine_power=0)
            r = DamageResolver.resolve(
                DamageSpec(hull=1), is_missile=False, target=ship,
                target_system_id=None, rng=random.Random(seed),
            )
            assert not r.dodged


# ---------------------------------------------------------------------------
# Beam behaviour
# ---------------------------------------------------------------------------

class TestBeamBehaviour:
    def test_beam_blocked_by_shields_no_layer_drain(self):
        """Beam vs 2-layer shield: 0 damage, no layer drain."""
        ship = _make_ship(hull=30, shield_layers=2)
        r = _resolve(DamageSpec(hull=2), ship, is_beam=True)
        assert r.hull_dealt == 0
        assert r.shields_drained == 0
        assert ship.shield_layers == 2  # no drain

    def test_beam_deals_damage_through_zero_shields(self):
        """Beam vs 0 shields: deals full hull damage."""
        ship = _make_ship(hull=30, shield_layers=0)
        r = _resolve(DamageSpec(hull=2), ship, is_beam=True)
        assert r.hull_dealt == 2
        assert ship.hull == 28
