from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .blueprints import DamageSpec
from .state import ShipState, ProjectileInFlight, SYS_SHIELDS, ION_DURATION


@dataclass
class DamageResult:
    hull_dealt:       int   = 0
    system_dealt:     float = 0.0
    ion_dealt:        int   = 0
    shields_drained:  int   = 0
    dodged:           bool  = False
    fire_started:     bool  = False
    breach_created:   bool  = False
    target_system_id: Optional[int] = None


class DamageResolver:
    """
    Stateless damage pipeline. Mirrors the hit resolution in:
      ShipManager::CollisionMoving  (FTLGameWin32.h:7562)
      ShieldSystem::CollisionReal   (FTLGameWin32.h:7188)
      ShipManager::DamageHull       (FTLGameWin32.h:7576)
      ShipManager::DamageSystem     (FTLGameWin32.h:7577)

    All randomness goes through the explicit `rng` parameter so tests are
    deterministic without patching.

    Pipeline (per shot):
      1. Dodge roll          — skipped for missiles
      2. Shield check        — drain layer or pass through
      3. System damage       — reduce system HP, kill power if destroyed
      4. Hull damage         — reduce hull HP
      5. Fire / breach rolls — probabilistic secondary effects
    """

    @staticmethod
    def resolve(
        spec: DamageSpec,
        is_missile: bool,
        target: ShipState,
        target_system_id: Optional[int],
        rng: random.Random,
        is_beam: bool = False,
    ) -> DamageResult:
        result = DamageResult(target_system_id=target_system_id)

        # 1. DODGE ROLL
        # Missiles cannot be dodged; beams can be (they have a travel sweep time).
        if not is_missile and rng.random() < target.dodge_chance():
            result.dodged = True
            return result

        # 2. SHIELD CHECK
        # Beams are blocked by shields but don't drain layers — they simply deal
        # 0 damage when any shield layer is present (unlike lasers which drain).
        if is_beam and target.shield_layers > 0:
            return result   # beam blocked, no effect

        # Missiles bypass shields entirely.
        # hull_buster weapons still consume a shield layer but deal hull dmg
        # when shields are gone — handled below at step 4.
        if not is_missile and target.shield_layers > 0:
            effective_layers = target.shield_layers - spec.shield_pierce
            if effective_layers > 0:
                target.shield_layers -= 1
                target.shield_charger = 0.0
                result.shields_drained = 1

                # Ion blasts also apply a timer to the shield system itself
                if spec.ion > 0:
                    result.ion_dealt = spec.ion
                    shield_sys = target.systems.get(SYS_SHIELDS)
                    if shield_sys:
                        shield_sys.ion_timer += spec.ion * ION_DURATION

                return result
            # shield_pierce reduced effective_layers to ≤ 0 → fall through to hull

        # 3. SYSTEM DAMAGE
        sys_dealt = 0.0
        if target_system_id is not None and spec.system > 0:
            sys = target.systems.get(target_system_id)
            if sys and sys.health_current > 0:
                sys_dealt = min(float(spec.system), sys.health_current)
                sys.health_current -= sys_dealt
                if sys.health_current <= 0:
                    sys.health_current = 0.0
                    sys.power_current  = 0   # destroyed system loses all power
                result.system_dealt = sys_dealt

        # 4. HULL DAMAGE
        hull_dmg = spec.hull
        if spec.hull_buster and target.shield_layers == 0:
            hull_dmg += 1   # bonus damage when penetrating an unshielded hull
        if hull_dmg > 0:
            target.hull = max(0, target.hull - hull_dmg)
            result.hull_dealt = hull_dmg

        # 5. FIRE AND BREACH ROLLS
        if spec.fire_chance > 0 and target_system_id is not None:
            if rng.randint(1, 100) <= spec.fire_chance:
                sys = target.systems.get(target_system_id)
                if sys:
                    sys.on_fire = True
                    result.fire_started = True

        if spec.breach_chance > 0 and target_system_id is not None:
            if rng.randint(1, 100) <= spec.breach_chance:
                sys = target.systems.get(target_system_id)
                if sys:
                    sys.breached = True
                    result.breach_created = True

        return result

    @staticmethod
    def resolve_projectile(
        projectile: ProjectileInFlight,
        target: ShipState,
        rng: random.Random,
    ) -> list[DamageResult]:
        """
        Resolve all shots in a volley sequentially against the current shield
        state. Each shot re-checks shields independently — so a 3-shot burst
        can drain layers 1 and 2 before the third shot hits hull.
        """
        results = []
        for _ in range(projectile.shots_remaining):
            r = DamageResolver.resolve(
                spec=projectile.damage_spec,
                is_missile=projectile.is_missile,
                target=target,
                target_system_id=projectile.target_system_id,
                rng=rng,
                is_beam=projectile.is_beam,
            )
            results.append(r)
            if target.hull <= 0:
                break   # ship destroyed mid-volley
        return results
