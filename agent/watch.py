#!/usr/bin/env python3
"""
Watch an FTL combat simulation play out in the terminal.

Both sides are driven by the rule-based EnemyAI.
The display only updates when a notable event occurs (weapon impact, fire).
The Events section shows exactly what happened since the last render — nothing older.

Usage:
    python watch.py
    python watch.py --player KESTREL_A --enemy PIRATE_ASSAULT --speed 4 --seed 7
    python watch.py --list-ships
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from sim.blueprints import SHIPS
from sim.env import FTLCombatEnv, N_WEAPON_SLOTS
from sim.ai import EnemyAI
from sim.render import render, SYS_NAMES
from sim.state import SYS_SHIELDS, SYS_ENGINES, SYS_WEAPONS

_SYS_TO_ACT     = {SYS_SHIELDS: 0, SYS_WEAPONS: 1, SYS_ENGINES: 2}
TICKS_PER_FRAME = 16   # 1 game-second per iteration


def _build_action(env: FTLCombatEnv, ai: EnemyAI) -> dict:
    state   = env._state
    targets = ai.choose_weapon_targets(state.player, state.enemy)
    acts    = [_SYS_TO_ACT.get(t, 3) for t in targets]
    acts   += [0] * max(0, N_WEAPON_SLOTS - len(acts))
    return {
        "weapon_targets":      np.array(acts[:N_WEAPON_SLOTS], dtype=np.int64),
        "power_shields_delta": np.int64(1),
        "power_engines_delta": np.int64(1),
        "power_weapons_delta": np.int64(1),
    }


def _format_impact(imp: dict) -> list[str]:
    target = "PLAYER" if imp["target_id"] == 0 else "ENEMY "
    weapon = imp["weapon"]
    if imp["dodged"]:
        return [f"  {target}  dodged  {weapon}"]
    lines = []
    if imp["shields_drained"]:
        lines.append(f"  {target}  shield drained by {weapon}")
    if imp["hull_dealt"]:
        suffix = "  ☠ KILLED" if imp["fatal"] else ""
        lines.append(f"  {target}  -{imp['hull_dealt']} hull  ← {weapon}{suffix}")
    if not lines:
        lines.append(f"  {target}  hit by {weapon}  (no effect)")
    return lines


def _clear():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Watch an FTL combat simulation")
    parser.add_argument("--player", default="KESTREL_A")
    parser.add_argument("--enemy",  default="REBEL_FIGHTER")
    parser.add_argument("--speed",  type=float, default=2.0,
                        help="Playback speed multiplier (default: 2.0)")
    parser.add_argument("--seed",   type=int, default=42)
    parser.add_argument("--list-ships", action="store_true")
    args = parser.parse_args()

    if args.list_ships:
        print("\nAvailable ship configs:")
        for name, cfg in SHIPS.items():
            print(f"  {name:<20}  hull={cfg.hull:2d}  shields={cfg.shields_power}"
                  f"  engines={cfg.engines_power}  weapons={', '.join(cfg.weapons)}")
        print()
        return

    for attr, label in (("player", "player"), ("enemy", "enemy")):
        if getattr(args, attr) not in SHIPS:
            print(f"Unknown {label} ship '{getattr(args, attr)}'. Use --list-ships.")
            sys.exit(1)

    env = FTLCombatEnv(args.player, args.enemy, seed=args.seed)
    ai  = EnemyAI()
    env.reset()

    frame_sleep = TICKS_PER_FRAME * env._dt / args.speed
    known_fires: set = set()

    def _active_fires(state):
        return {(0, sid) for sid, s in state.player.systems.items() if s.on_fire} | \
               {(1, sid) for sid, s in state.enemy.systems.items() if s.on_fire}

    # Initial render so screen isn't blank while weapons charge
    _clear()
    sys.stdout.write(render(env._state, []))
    sys.stdout.flush()

    while True:
        frame_impacts: list[dict] = []
        frame_fires:   list[dict] = []
        terminated = truncated = False
        final_info: dict = {}

        for _ in range(TICKS_PER_FRAME):
            _, _, terminated, truncated, info = env.step(_build_action(env, ai))
            frame_impacts.extend(info.get("impacts", []))
            frame_fires.extend(info.get("fires",   []))
            final_info = info
            if terminated or truncated:
                break

        # Collect events that happened in this frame only
        frame_events: list[str] = []

        current_fires = _active_fires(env._state)
        for ship_id, sys_id in current_fires - known_fires:
            ship_name = "PLAYER" if ship_id == 0 else "ENEMY "
            frame_events.append(f"  {ship_name}  {SYS_NAMES.get(sys_id, 'sys')} caught FIRE 🔥")
        known_fires = current_fires

        for f in frame_fires:
            shooter = "PLAYER" if f["attacker_id"] == 0 else "ENEMY "
            target  = "PLAYER" if f["target_id"]   == 0 else "ENEMY "
            frame_events.append(
                f"  {shooter}  fired {f['weapon']} → {target}  ({f['travel_time']}s travel)"
            )
        for imp in frame_impacts:
            frame_events.extend(_format_impact(imp))

        # Only redraw when something happened — or on the final frame
        if frame_events or terminated or truncated:
            t   = env._state.time_elapsed
            log = [f"\033[90m── t={t:.1f}s {'─'*30}\033[0m"] + frame_events
            _clear()
            sys.stdout.write(render(env._state, log))
            sys.stdout.flush()

        if terminated or truncated:
            winner = final_info.get("winner", "?")
            color  = "\033[32m" if winner == "player" else "\033[31m"
            print(f"\n  {color}\033[1m══  COMBAT ENDED  ══\033[0m"
                  f"  winner: {winner}"
                  f"   ticks: {final_info['ticks']}"
                  f"   time: {final_info['ticks'] * env._dt:.1f}s\n")
            break

        time.sleep(frame_sleep)


if __name__ == "__main__":
    main()
