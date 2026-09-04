from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .blueprints import WEAPONS, ShipConfig, DamageSpec

# System ID constants — mirror C++ SYS_* enum values from FTLGameWin32.h
SYS_SHIELDS    = 0
SYS_ENGINES    = 1
SYS_OXYGEN     = 2
SYS_WEAPONS    = 3
SYS_DRONES     = 4
SYS_MEDBAY     = 5
SYS_PILOTING   = 6
SYS_SENSORS    = 7
SYS_DOORS      = 8
SYS_TELEPORTER = 9
SYS_CLOAKING   = 10
SYS_ARTILLERY  = 11

# Physics / timing constants
SHIELD_CHARGE_TIME_BASE = 7.0   # seconds per layer (shield power=2, 1-layer baseline)
INTERSHIP_DISTANCE      = 300   # pixels between ships in combat
ION_DURATION            = 5.0   # seconds of ion disable per 1 ion damage


@dataclass
class WeaponState:
    blueprint_name:   str
    cooldown_current: float   # counts up from 0 to cooldown_max
    cooldown_max:     float
    powered:          bool
    charge_level:     int   = 0
    ion_stacks:       int   = 0

    @property
    def ready(self) -> bool:
        return self.powered and self.cooldown_current >= self.cooldown_max


@dataclass
class SystemState:
    sys_id:          int
    power_current:   int
    power_max:       int
    health_current:  float
    health_max:      float
    on_fire:         bool  = False
    breached:        bool  = False
    ion_timer:       float = 0.0   # seconds; > 0 reduces effective power

    @property
    def effective_power(self) -> int:
        """Power available after ion disabling. Mirrors ShipSystem::GetEffectivePower()."""
        ion_reduction = math.ceil(self.ion_timer / ION_DURATION) if self.ion_timer > 0 else 0
        return max(0, self.power_current - ion_reduction)

    @property
    def functional(self) -> bool:
        return self.health_current > 0 and self.effective_power > 0


@dataclass
class ShipState:
    """
    Full runtime state of one ship. Mirrors the key fields of ShipManager
    (FTLGameWin32.h:7456) + Shields (7157) + ProjectileFactory vector (6755).

    Construct from a ShipConfig for synthetic training, or from a live game
    state snapshot via from_snapshot() once AgentHook exports combat state.
    """
    ship_id:            int
    hull:               int
    hull_max:           int
    shield_layers:      int
    shield_max:         int
    shield_charger:     float   # 0.0–1.0 progress toward next layer
    shield_charge_time: float   # seconds per layer
    engine_power:       int
    weapons:            list[WeaponState]
    systems:            dict[int, SystemState]   # sys_id → SystemState
    missiles:           int
    reactor_power:      int  = 8
    is_automated:       bool = False

    def dodge_chance(self) -> float:
        """
        Mirrors ShipManager::GetDodgeFactor(): each engine power bar = 5% dodge,
        capped at 60%. Uses engine_power which is kept in sync with the engine
        system's effective_power by _apply_action.
        """
        return min(self.engine_power * 0.05, 0.60)

    @classmethod
    def from_config(cls, ship_id: int, config: ShipConfig) -> ShipState:
        """Build initial combat state from a hardcoded ShipConfig."""
        shield_layers = config.shields_power // 2
        shield_max    = shield_layers

        # Power weapons greedily in slot order until weapons_power is exhausted
        weapon_states: list[WeaponState] = []
        remaining_wpower = config.weapons_power
        for wname in config.weapons:
            bp = WEAPONS[wname]
            powered = remaining_wpower >= bp.power
            if powered:
                remaining_wpower -= bp.power
            weapon_states.append(WeaponState(
                blueprint_name=wname,
                cooldown_current=0.0,
                cooldown_max=bp.cooldown,
                powered=powered,
            ))

        systems: dict[int, SystemState] = {
            SYS_SHIELDS: SystemState(
                SYS_SHIELDS,
                power_current=config.shields_power,
                power_max=config.shields_power,
                health_current=100.0, health_max=100.0,
            ),
            SYS_ENGINES: SystemState(
                SYS_ENGINES,
                power_current=config.engines_power,
                power_max=config.engines_power,
                health_current=100.0, health_max=100.0,
            ),
            SYS_WEAPONS: SystemState(
                SYS_WEAPONS,
                power_current=config.weapons_power,
                power_max=config.weapons_power,
                health_current=100.0, health_max=100.0,
            ),
        }

        return cls(
            ship_id=ship_id,
            hull=config.hull, hull_max=config.hull,
            shield_layers=shield_layers, shield_max=shield_max,
            shield_charger=0.0,
            shield_charge_time=SHIELD_CHARGE_TIME_BASE,
            engine_power=config.engines_power,
            weapons=weapon_states,
            systems=systems,
            missiles=config.missiles,
            reactor_power=config.reactor_power,
            is_automated=config.is_automated,
        )

    @classmethod
    def from_snapshot(cls, ship_id: int, snapshot: dict) -> ShipState:
        """
        Reconstruct from a JSON snapshot exported by AgentHook.
        Wired up once AgentHook exports full combat state (open item in
        AGENT_DESIGN.md: ship/combat state serialization).
        """
        raise NotImplementedError(
            "from_snapshot() requires AgentHook combat state export — "
            "not yet implemented on the C++ side (see AGENT_DESIGN.md)."
        )


@dataclass
class ProjectileInFlight:
    """
    A fired weapon volley in transit between ships.

    We skip spatial simulation: travel_time counts down to zero, then
    DamageResolver.resolve_projectile() runs all shots sequentially against
    the target's current shield state. This preserves the key FTL mechanic —
    multi-shot bursts can drain shields one layer at a time within a single
    volley — without needing 2-D coordinates.
    """
    weapon_name:      str
    damage_spec:      DamageSpec
    shots_remaining:  int        # volley size; resolve runs once per shot
    travel_time:      float      # seconds until first impact
    target_id:        int        # ship_id of target ship
    target_system_id: Optional[int]   # which system to aim at
    is_missile:       bool
    is_beam:          bool = False   # beams are blocked (not drained) by shields


@dataclass
class CombatState:
    player:                ShipState
    enemy:                 ShipState
    projectiles_in_flight: list[ProjectileInFlight] = field(default_factory=list)
    tick:                  int   = 0
    time_elapsed:          float = 0.0

    def get_ship(self, ship_id: int) -> ShipState:
        return self.player if ship_id == 0 else self.enemy
