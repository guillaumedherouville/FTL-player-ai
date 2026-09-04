from __future__ import annotations

from .blueprints import WeaponType, WEAPONS, WeaponBlueprint
from .state import ShipState, SYS_SHIELDS, SYS_ENGINES, SYS_WEAPONS


class EnemyAI:
    """
    Rule-based enemy AI — port of CombatAI::PrioritizeSystem + UpdateWeapons
    (FTLGameWin32.h:3101-3104, stance=0 aggressive).

    Enemy ships never reallocate power mid-combat in the base game, so only
    weapon targeting is dynamic here.
    """

    def choose_weapon_targets(
        self,
        self_ship: ShipState,
        target_ship: ShipState,
    ) -> list[int]:
        """
        Return a target system_id for each weapon slot.
        -1 = unpowered slot (no target chosen).
        """
        return [
            self._prioritize(WEAPONS[w.blueprint_name], target_ship)
            if w.powered and w.blueprint_name in WEAPONS
            else -1
            for w in self_ship.weapons
        ]

    def _prioritize(self, weapon: WeaponBlueprint, target: ShipState) -> int:
        """
        Port of CombatAI::PrioritizeSystem(weaponType).

        Targeting table (stance=0):
          LASER / BURST / ION:
            if shields up        → SYS_SHIELDS   (drain layers first)
            if weapons alive     → SYS_WEAPONS
            if engines alive     → SYS_ENGINES
            fallback             → SYS_SHIELDS
          MISSILE / BEAM:
            missiles bypass shields; beams deal 0 through shields.
            → SYS_WEAPONS first, then SYS_ENGINES, then SYS_SHIELDS
        """
        shields_up = target.shield_layers > 0

        if weapon.weapon_type in (WeaponType.MISSILE, WeaponType.BEAM):
            if _sys_alive(target, SYS_WEAPONS):
                return SYS_WEAPONS
            if _sys_alive(target, SYS_ENGINES):
                return SYS_ENGINES
            return SYS_SHIELDS

        # LASER / BURST / ION
        if shields_up and _sys_alive(target, SYS_SHIELDS):
            return SYS_SHIELDS
        if _sys_alive(target, SYS_WEAPONS):
            return SYS_WEAPONS
        if _sys_alive(target, SYS_ENGINES):
            return SYS_ENGINES
        return SYS_SHIELDS


def _sys_alive(ship: ShipState, sys_id: int) -> bool:
    sys = ship.systems.get(sys_id)
    return sys is not None and sys.health_current > 0
