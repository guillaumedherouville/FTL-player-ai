from __future__ import annotations

import random
from typing import Optional

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from .blueprints import WEAPONS, SHIPS, WeaponType, ShipConfig
from .state import (
    ShipState, ProjectileInFlight, CombatState,
    SYS_SHIELDS, SYS_ENGINES, SYS_WEAPONS,
    INTERSHIP_DISTANCE,
)
from .damage import DamageResolver
from .ai import EnemyAI

# Action target categories (index into action["weapon_targets"])
ACT_SHIELDS = 0
ACT_WEAPONS = 1
ACT_ENGINES = 2
ACT_RANDOM  = 3

# Observation constants
N_WEAPON_SLOTS       = 4
N_OBS                = 34      # 17 per ship × 2
DT                   = 1.0 / 16.0   # seconds per tick (≈ FTL's frame rate)
FIRE_DMG_PER_SECOND  = 0.1    # hull damage per second from an active fire


class FTLCombatEnv(gym.Env):
    """
    Gymnasium environment simulating FTL: Faster Than Light ship combat.

    Observation : Box(34,) float32 — normalised player + enemy ship state
    Action      : Dict — weapon targets per slot + power allocation deltas
    Reward      : Hull differential with terminal bonuses
    Episode ends: either ship reaches 0 hull, or max_ticks exceeded

    Usage::
        env = FTLCombatEnv("KESTREL_A", "REBEL_FIGHTER", seed=42)
        obs, _ = env.reset()
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        player_config: str | ShipConfig = "KESTREL_A",
        enemy_config:  str | ShipConfig = "REBEL_FIGHTER",
        seed:          Optional[int]    = None,
        max_ticks:     int              = 5000,
        dt:            float            = DT,
    ):
        super().__init__()

        self._player_cfg = SHIPS[player_config] if isinstance(player_config, str) else player_config
        self._enemy_cfg  = SHIPS[enemy_config]  if isinstance(enemy_config,  str) else enemy_config
        self._max_ticks  = max_ticks
        self._dt         = dt
        self._ai         = EnemyAI()
        self._seed       = seed
        self._rng: random.Random = random.Random(seed)

        # Action space: per-weapon target + per-system power delta
        self.action_space = spaces.Dict({
            # Which system category each weapon slot aims at
            "weapon_targets": spaces.MultiDiscrete([4] * N_WEAPON_SLOTS),
            # Power deltas: 0=decrease, 1=hold, 2=increase
            "power_shields_delta": spaces.Discrete(3),
            "power_engines_delta": spaces.Discrete(3),
            "power_weapons_delta": spaces.Discrete(3),
        })

        # Observation space: 34 normalised floats in [0, 1]
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(N_OBS,), dtype=np.float32,
        )

        self._state: Optional[CombatState] = None

    # ------------------------------------------------------------------
    # Gym interface
    # ------------------------------------------------------------------

    def reset(
        self,
        seed:    Optional[int]  = None,
        options: Optional[dict] = None,
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)   # sets self._np_random for gymnasium compliance
        if seed is not None:
            self._rng = random.Random(seed)
        elif self._seed is not None:
            self._rng = random.Random(self._seed)

        self._state = CombatState(
            player=ShipState.from_config(0, self._player_cfg),
            enemy =ShipState.from_config(1, self._enemy_cfg),
        )
        return self._observe(), {}

    def step(
        self, action: dict
    ) -> tuple[np.ndarray, float, bool, bool, dict]:
        assert self._state is not None, "Call reset() before step()"

        prev_player_hull = self._state.player.hull
        prev_enemy_hull  = self._state.enemy.hull

        # 1. Apply player power + targeting action
        self._apply_action(action)

        # 2. Enemy AI chooses weapon targets
        enemy_targets = self._ai.choose_weapon_targets(
            self._state.enemy, self._state.player
        )

        # 3. Advance weapon cooldowns and fire ready weapons (both ships)
        fires: list[dict] = []
        fires += self._advance_weapons(self._state.player, self._state.enemy,
                                       list(action["weapon_targets"]))
        fires += self._advance_weapons(self._state.enemy, self._state.player,
                                       enemy_targets)

        # 4. Decay ion timers
        _decay_ion(self._state.player, self._dt)
        _decay_ion(self._state.enemy,  self._dt)

        # 5. Advance projectiles; resolve impacts
        impacts = self._advance_projectiles()

        # 6. Recharge shields
        _recharge_shields(self._state.player, self._dt)
        _recharge_shields(self._state.enemy,  self._dt)

        # 7. Fire damage — accumulates; only whole-point hits are logged
        fire_dmg_player = _apply_fire(self._state.player, self._dt)
        fire_dmg_enemy  = _apply_fire(self._state.enemy,  self._dt)
        if fire_dmg_player:
            impacts.append({"weapon": "fire", "target_id": 0,
                            "hull_dealt": fire_dmg_player, "shields_drained": 0,
                            "dodged": False, "fatal": self._state.player.hull <= 0})
        if fire_dmg_enemy:
            impacts.append({"weapon": "fire", "target_id": 1,
                            "hull_dealt": fire_dmg_enemy, "shields_drained": 0,
                            "dodged": False, "fatal": self._state.enemy.hull <= 0})

        # 8. Tick
        self._state.tick        += 1
        self._state.time_elapsed += self._dt

        # Compute reward and check terminal conditions
        player_hull_lost = prev_player_hull - self._state.player.hull
        enemy_hull_lost  = prev_enemy_hull  - self._state.enemy.hull
        reward           = self._reward(enemy_hull_lost, player_hull_lost)

        terminated = (self._state.player.hull <= 0 or self._state.enemy.hull <= 0)
        truncated  = (self._state.tick >= self._max_ticks)

        if self._state.enemy.hull <= 0:
            winner = "player"
        elif self._state.player.hull <= 0:
            winner = "enemy"
        elif truncated:
            winner = "timeout"
        else:
            winner = None

        return (
            self._observe(),
            reward,
            terminated,
            truncated,
            {"winner": winner, "ticks": self._state.tick, "impacts": impacts, "fires": fires},
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict, **kwargs) -> FTLCombatEnv:
        """
        Reconstruct an environment from a live AgentHook combat snapshot.
        Wired up when AgentHook exports full combat state (AGENT_DESIGN.md
        open item). Useful for transfer learning: initialise from a real
        game state, then run synthetic rollouts without the game running.
        """
        raise NotImplementedError(
            "from_snapshot() requires AgentHook combat state serialisation "
            "(open item in AGENT_DESIGN.md)."
        )

    # ------------------------------------------------------------------
    # Internal tick logic
    # ------------------------------------------------------------------

    def _apply_action(self, action: dict) -> None:
        p = self._state.player

        # Apply power deltas for shields / engines / weapons
        for sys_id, key in (
            (SYS_SHIELDS, "power_shields_delta"),
            (SYS_ENGINES, "power_engines_delta"),
            (SYS_WEAPONS, "power_weapons_delta"),
        ):
            delta = int(action[key]) - 1   # 0→−1, 1→0, 2→+1
            if delta == 0:
                continue
            sys = p.systems.get(sys_id)
            if sys is None:
                continue

            new_power = sys.power_current + delta
            new_power = max(0, min(new_power, sys.power_max))

            # Enforce reactor budget
            other_power = sum(
                s.power_current for sid, s in p.systems.items() if sid != sys_id
            )
            new_power = min(new_power, p.reactor_power - other_power)
            new_power = max(0, new_power)

            sys.power_current = new_power

        # Re-derive shield state from shield system power
        shield_sys = p.systems.get(SYS_SHIELDS)
        if shield_sys:
            p.shield_max    = shield_sys.effective_power // 2
            p.shield_layers = min(p.shield_layers, p.shield_max)

        # Re-derive engine power from engine system
        engine_sys = p.systems.get(SYS_ENGINES)
        if engine_sys:
            p.engine_power = engine_sys.effective_power

        # Re-derive which weapons are powered from weapons system
        weapon_sys = p.systems.get(SYS_WEAPONS)
        if weapon_sys:
            remaining = weapon_sys.effective_power
            for w in p.weapons:
                bp = WEAPONS.get(w.blueprint_name)
                if bp is None:
                    continue
                w.powered = remaining >= bp.power
                if w.powered:
                    remaining -= bp.power

    def _advance_weapons(
        self,
        attacker: ShipState,
        target:   ShipState,
        targets:  list[int],
    ) -> list[dict]:
        fires = []
        for i, w in enumerate(attacker.weapons):
            if not w.powered:
                continue

            bp = WEAPONS.get(w.blueprint_name)
            if bp is None:
                continue

            w.cooldown_current = min(w.cooldown_current + self._dt, w.cooldown_max)

            if w.cooldown_current < w.cooldown_max:
                continue  # still charging

            # Consume missile ammo if required
            if bp.missiles > 0:
                if attacker.missiles < bp.missiles:
                    continue  # out of ammo
                attacker.missiles -= bp.missiles

            # Compute travel time
            if bp.weapon_type == WeaponType.BEAM:
                travel_time = 1.5   # beam sweep duration
            elif bp.weapon_type == WeaponType.BOMB:
                travel_time = 2.5   # bombs teleport across
            else:
                travel_time = INTERSHIP_DISTANCE / max(bp.speed, 1.0)

            # Resolve action target → concrete system_id
            act_target = targets[i] if i < len(targets) else ACT_SHIELDS
            sys_target = _resolve_target(act_target, target, self._rng)

            self._state.projectiles_in_flight.append(ProjectileInFlight(
                weapon_name=w.blueprint_name,
                damage_spec=bp.damage,
                shots_remaining=bp.shots,
                travel_time=travel_time,
                target_id=target.ship_id,
                target_system_id=sys_target,
                is_missile=(bp.weapon_type == WeaponType.MISSILE),
                is_beam=(bp.weapon_type == WeaponType.BEAM),
            ))
            fires.append({
                "weapon":     w.blueprint_name,
                "attacker_id": attacker.ship_id,
                "target_id":   target.ship_id,
                "travel_time": round(travel_time, 2),
            })
            w.cooldown_current = 0.0   # reset for next volley
        return fires

    def _advance_projectiles(self) -> list[dict]:
        still_flying = []
        impacts = []
        for p in self._state.projectiles_in_flight:
            p.travel_time -= self._dt
            if p.travel_time > 0:
                still_flying.append(p)
                continue
            target = self._state.get_ship(p.target_id)
            if target.hull <= 0:
                continue   # ship already dead — skip post-mortem impacts
            hull_before    = target.hull
            shields_before = target.shield_layers
            results = DamageResolver.resolve_projectile(p, target, self._rng)
            hull_dealt     = max(0, int(hull_before - target.hull))
            shields_drained = max(0, shields_before - target.shield_layers)
            all_dodged      = bool(results) and all(r.dodged for r in results)
            impacts.append({
                "weapon":          p.weapon_name,
                "target_id":       p.target_id,
                "hull_dealt":      hull_dealt,
                "shields_drained": shields_drained,
                "dodged":          all_dodged,
                "fatal":           target.hull <= 0,
            })
        self._state.projectiles_in_flight = still_flying
        return impacts

    def _reward(self, enemy_hull_lost: int, player_hull_lost: int) -> float:
        p, e = self._state.player, self._state.enemy
        r  = 2.0 * (enemy_hull_lost  / max(e.hull_max, 1))
        r -= 3.0 * (player_hull_lost / max(p.hull_max, 1))
        if e.hull <= 0:
            r += 5.0
        if p.hull <= 0:
            r -= 5.0
        if p.shield_max > 0:
            r += 0.05 * (p.shield_layers / p.shield_max)
        return r

    def _observe(self) -> np.ndarray:
        obs = np.zeros(N_OBS, dtype=np.float32)
        _fill_ship_obs(self._state.player, obs, offset=0)
        _fill_ship_obs(self._state.enemy,  obs, offset=17)
        return obs


# ------------------------------------------------------------------
# Module-level helpers (pure functions, no env state)
# ------------------------------------------------------------------

def _fill_ship_obs(ship: ShipState, obs: np.ndarray, offset: int) -> None:
    obs[offset + 0]  = ship.hull / max(ship.hull_max, 1)
    obs[offset + 1]  = ship.shield_layers / max(ship.shield_max, 1) if ship.shield_max > 0 else 0.0
    obs[offset + 2]  = ship.shield_charger
    obs[offset + 3]  = ship.engine_power / 8.0

    for i in range(N_WEAPON_SLOTS):
        if i < len(ship.weapons):
            w = ship.weapons[i]
            obs[offset + 4 + i] = w.cooldown_current / max(w.cooldown_max, 1.0)
            obs[offset + 8 + i] = 1.0 if w.powered else 0.0

    obs[offset + 12] = min(ship.missiles / 30.0, 1.0)

    for j, sys_id in enumerate((SYS_SHIELDS, SYS_ENGINES, SYS_WEAPONS)):
        sys = ship.systems.get(sys_id)
        if sys:
            obs[offset + 13 + j] = sys.health_current / max(sys.health_max, 1.0)

    # obs[offset + 16] reserved for future use (stays 0)


def _decay_ion(ship: ShipState, dt: float) -> None:
    for sys in ship.systems.values():
        if sys.ion_timer > 0:
            sys.ion_timer = max(0.0, sys.ion_timer - dt)


def _recharge_shields(ship: ShipState, dt: float) -> None:
    if ship.shield_layers >= ship.shield_max:
        return
    shield_sys = ship.systems.get(SYS_SHIELDS)
    # Shields don't recharge while ion-disabled
    if shield_sys and shield_sys.ion_timer > 0:
        return
    ship.shield_charger += dt / ship.shield_charge_time
    if ship.shield_charger >= 1.0:
        ship.shield_layers += 1
        ship.shield_charger = 0.0


def _apply_fire(ship: ShipState, dt: float) -> int:
    """Accumulate fire damage; deal and return whole-point hull hits only."""
    fires_burning = sum(1 for s in ship.systems.values() if s.on_fire)
    if not fires_burning:
        return 0
    ship.fire_damage_acc += FIRE_DMG_PER_SECOND * fires_burning * dt
    damage = int(ship.fire_damage_acc)
    if damage >= 1:
        ship.fire_damage_acc -= damage
        ship.hull = max(0, ship.hull - damage)
        return damage
    return 0


def _resolve_target(
    act_target: int,
    target_ship: ShipState,
    rng: random.Random,
) -> Optional[int]:
    if act_target == ACT_SHIELDS:
        return SYS_SHIELDS
    if act_target == ACT_WEAPONS:
        return SYS_WEAPONS
    if act_target == ACT_ENGINES:
        return SYS_ENGINES
    # ACT_RANDOM: pick a living system at random
    candidates = [sid for sid, s in target_ship.systems.items() if s.health_current > 0]
    return rng.choice(candidates) if candidates else SYS_SHIELDS
