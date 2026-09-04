from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class WeaponType(IntEnum):
    LASER   = 0
    MISSILE = 1
    BEAM    = 2
    BOMB    = 3
    BURST   = 4  # flak / scatter


@dataclass(frozen=True)
class DamageSpec:
    hull:          int  = 0
    shield_pierce: int  = 0   # iShieldPiercing — bypass N shield layers
    ion:           int  = 0   # iIonDamage
    system:        int  = 0   # iSystemDamage
    fire_chance:   int  = 0   # 0-100 integer percent
    breach_chance: int  = 0   # 0-100 integer percent
    hull_buster:   bool = False


@dataclass(frozen=True)
class WeaponBlueprint:
    name:          str
    weapon_type:   WeaponType
    damage:        DamageSpec
    shots:         int   = 1
    missiles:      int   = 0     # ammo cost per volley
    cooldown:      float = 10.0  # seconds
    power:         int   = 1     # power bars required
    charge_levels: int   = 0     # 0 = instant-fire
    speed:         float = 60.0  # px/s for travel time
    length:        int   = 0     # beam sweep length in px
    radius:        int   = 0     # flak scatter radius


@dataclass(frozen=True)
class ShipConfig:
    name:          str
    hull:          int
    weapons:       tuple          # (blueprint_name, ...)
    shields_power: int            # bars allocated to shields
    engines_power: int
    weapons_power: int
    reactor_power: int  = 8
    missiles:      int  = 0
    is_automated:  bool = False   # bAutomated (no crew)


# ---------------------------------------------------------------------------
# Weapon blueprints — stats sourced from the FTL wiki
# ---------------------------------------------------------------------------
WEAPONS: dict[str, WeaponBlueprint] = {
    # Lasers
    "LASER_BURST_1": WeaponBlueprint(
        "LASER_BURST_1", WeaponType.LASER, DamageSpec(hull=1),
        shots=2, cooldown=11.0, power=1),
    "LASER_BURST_2": WeaponBlueprint(
        "LASER_BURST_2", WeaponType.LASER, DamageSpec(hull=1),
        shots=3, cooldown=12.0, power=2),
    "LASER_BURST_3": WeaponBlueprint(
        "LASER_BURST_3", WeaponType.LASER, DamageSpec(hull=1),
        shots=5, cooldown=14.0, power=3),
    "LASER_HEAVY_1": WeaponBlueprint(
        "LASER_HEAVY_1", WeaponType.LASER, DamageSpec(hull=2, hull_buster=True),
        shots=1, cooldown=13.0, power=1),
    "LASER_HEAVY_2": WeaponBlueprint(
        "LASER_HEAVY_2", WeaponType.LASER, DamageSpec(hull=2, hull_buster=True),
        shots=1, cooldown=11.0, power=2),
    # Ion
    "ION_BLAST_1": WeaponBlueprint(
        "ION_BLAST_1", WeaponType.LASER, DamageSpec(ion=1),
        shots=1, cooldown=10.0, power=1),
    "ION_BLAST_2": WeaponBlueprint(
        "ION_BLAST_2", WeaponType.LASER, DamageSpec(ion=2),
        shots=1, cooldown=15.0, power=2),
    # Missiles
    "MISSILE_1": WeaponBlueprint(
        "MISSILE_1", WeaponType.MISSILE,
        DamageSpec(hull=3, fire_chance=10, breach_chance=30),
        shots=1, missiles=1, cooldown=14.0, power=1, speed=45.0),
    "MISSILE_BREACH": WeaponBlueprint(
        "MISSILE_BREACH", WeaponType.MISSILE,
        DamageSpec(hull=2, breach_chance=80),
        shots=1, missiles=1, cooldown=17.0, power=2, speed=45.0),
    # Beams — speed=0 signals beam; travel_time computed from length
    "BEAM_HULL_1": WeaponBlueprint(
        "BEAM_HULL_1", WeaponType.BEAM, DamageSpec(hull=1),
        shots=1, cooldown=15.0, power=1, speed=0.0, length=50),
    "BEAM_HALBERD": WeaponBlueprint(
        "BEAM_HALBERD", WeaponType.BEAM, DamageSpec(hull=2),
        shots=1, cooldown=17.0, power=2, speed=0.0, length=60),
    "BEAM_FIRE": WeaponBlueprint(
        "BEAM_FIRE", WeaponType.BEAM, DamageSpec(hull=1, fire_chance=100),
        shots=1, cooldown=17.0, power=1, speed=0.0, length=70),
    # Flak
    "FLAK_1": WeaponBlueprint(
        "FLAK_1", WeaponType.BURST, DamageSpec(hull=1),
        shots=3, cooldown=14.0, power=2, speed=80.0, radius=20),
    # Charge weapons
    "CHARGE_LASER_1": WeaponBlueprint(
        "CHARGE_LASER_1", WeaponType.LASER, DamageSpec(hull=1),
        shots=1, cooldown=14.0, power=1, charge_levels=3),
}


# ---------------------------------------------------------------------------
# Ship configs — hardcoded player ships and common enemy archetypes
# ---------------------------------------------------------------------------
SHIPS: dict[str, ShipConfig] = {
    # Player ships
    "KESTREL_A": ShipConfig(
        "KESTREL_A", hull=30,
        weapons=("LASER_BURST_1", "LASER_BURST_1"),
        shields_power=4, engines_power=3, weapons_power=3,
        reactor_power=10, missiles=8),
    "ENGI_A": ShipConfig(
        "ENGI_A", hull=30,
        weapons=("LASER_BURST_1", "ION_BLAST_1"),
        shields_power=4, engines_power=3, weapons_power=3,
        reactor_power=10, missiles=8),
    "MANTIS_A": ShipConfig(
        "MANTIS_A", hull=30,
        weapons=("LASER_BURST_1",),
        shields_power=4, engines_power=3, weapons_power=2,
        reactor_power=9, missiles=4),
    # Enemy archetypes
    "REBEL_FIGHTER": ShipConfig(
        "REBEL_FIGHTER", hull=14,
        weapons=("LASER_BURST_1",),
        shields_power=2, engines_power=2, weapons_power=2,
        reactor_power=6, missiles=0),
    "AUTOMATED_SCOUT": ShipConfig(
        "AUTOMATED_SCOUT", hull=12,
        weapons=("LASER_BURST_1",),
        shields_power=2, engines_power=2, weapons_power=2,
        reactor_power=6, missiles=0, is_automated=True),
    "PIRATE_ASSAULT": ShipConfig(
        "PIRATE_ASSAULT", hull=16,
        weapons=("LASER_HEAVY_1", "MISSILE_1"),
        shields_power=2, engines_power=3, weapons_power=3,
        reactor_power=8, missiles=4),
    "REBEL_RIGGER": ShipConfig(
        "REBEL_RIGGER", hull=18,
        weapons=("LASER_BURST_2",),
        shields_power=4, engines_power=2, weapons_power=3,
        reactor_power=9, missiles=0),
    "MANTIS_FIGHTER": ShipConfig(
        "MANTIS_FIGHTER", hull=16,
        weapons=("LASER_BURST_1",),
        shields_power=2, engines_power=4, weapons_power=2,
        reactor_power=8, missiles=0),
}


def load_blueprints_from_xml(xml_path: str) -> dict[str, WeaponBlueprint]:
    """Parse FTL blueprints.xml if present. Falls back to hardcoded WEAPONS."""
    # Stub — full XML parsing would go here when game assets are available.
    return WEAPONS
