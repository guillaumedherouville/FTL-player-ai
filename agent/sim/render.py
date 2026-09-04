"""
Terminal renderer for FTL combat state. No dependencies beyond stdlib.
"""
from __future__ import annotations

from .state import CombatState, ShipState, SYS_SHIELDS, SYS_ENGINES, SYS_WEAPONS

# ANSI
R  = "\033[0m"
B  = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BLUE   = "\033[34m"
GRAY   = "\033[90m"
WHITE  = "\033[97m"

SYS_NAMES = {SYS_SHIELDS: "shields", SYS_ENGINES: "engines", SYS_WEAPONS: "weapons"}


def _bar(filled: float, width: int = 20, fill="█", empty="░") -> str:
    n = round(filled * width)
    n = max(0, min(n, width))
    return fill * n + empty * (width - n)


def _hull_color(frac: float) -> str:
    if frac > 0.6:
        return GREEN
    if frac > 0.3:
        return YELLOW
    return RED


def _shield_bar(layers: int, max_layers: int, charger: float) -> str:
    if max_layers == 0:
        return GRAY + "  none" + R
    bars = ""
    for i in range(max_layers):
        bars += (CYAN + "█" if i < layers else GRAY + "░") + R
    pct = int(charger * 100)
    return f"{bars}  ↻{pct:2d}%"


def _cd_bar(current: float, maximum: float, width: int = 18) -> str:
    frac = current / maximum if maximum > 0 else 0.0
    n = round(frac * width)
    filled = CYAN + "═" * n + R
    empty  = GRAY + "─" * (width - n) + R
    return f"[{filled}{empty}] {int(frac*100):3d}%"


def _ship_block(ship: ShipState, label: str) -> list[str]:
    hull_frac = ship.hull / max(ship.hull_max, 1)
    hc        = _hull_color(hull_frac)
    hull_bar  = hc + _bar(hull_frac, 24) + R
    shield_s  = _shield_bar(ship.shield_layers, ship.shield_max, ship.shield_charger)
    dodge_pct = int(ship.dodge_chance() * 100)

    sys_w = ship.systems.get(SYS_WEAPONS)
    sys_s = ship.systems.get(SYS_SHIELDS)
    sys_e = ship.systems.get(SYS_ENGINES)

    def sys_hp(sys):
        if sys is None:
            return "–"
        if sys.health_current <= 0:
            return RED + "DESTROYED" + R
        if sys.on_fire:
            return RED + f"{sys.health_current:.0f}/{sys.health_max:.0f} 🔥" + R
        return f"{sys.health_current:.0f}/{sys.health_max:.0f}"

    lines = [
        f"  {B}{WHITE}{label:<18}{R}  hull {hull_bar} {hc}{int(ship.hull):3d}/{ship.hull_max}{R}"
        f"   shields {shield_s}   dodge {dodge_pct:2d}%",
        f"    systems   shields {sys_hp(sys_s)}   engines {sys_hp(sys_e)}   weapons {sys_hp(sys_w)}",
    ]

    for i, w in enumerate(ship.weapons):
        status = CYAN + "PWR" + R if w.powered else GRAY + "off" + R
        cd = _cd_bar(w.cooldown_current, w.cooldown_max)
        lines.append(f"    [{status}] {w.blueprint_name:<20} {cd}")

    return lines


def render(state: CombatState, log: list[str]) -> str:
    sep = GRAY + "─" * 78 + R
    lines = [""]

    # Events first — cause before effect
    if log:
        lines.append(f"  {B}Events:{R}")
        for entry in log:
            lines.append(f"    {GRAY}{entry}{R}")
        lines.append("")

    lines += [
        f"  {B}FTL COMBAT{R}   tick {state.tick:04d}   t = {state.time_elapsed:6.2f}s",
        sep,
        *_ship_block(state.player, "PLAYER"),
        sep,
        *_ship_block(state.enemy,  "ENEMY"),
        sep,
    ]

    if state.projectiles_in_flight:
        lines.append(f"  {B}In flight:{R}")
        for p in state.projectiles_in_flight:
            # target_id=0 → player ship is being targeted; target_id=1 → enemy ship
            who    = "PLAYER" if p.target_id == 0 else "ENEMY  "
            target = SYS_NAMES.get(p.target_system_id, f"sys{p.target_system_id}")
            lines.append(
                f"    {YELLOW}{p.weapon_name:<22}{R}"
                f"  →  {who}  [{target:<8}]"
                f"  {p.shots_remaining}× dmg   {GRAY}{p.travel_time:.2f}s{R}"
            )

    return "\n".join(lines) + "\n"
