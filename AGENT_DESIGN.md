# Agent Design — State Export & Input Injection

See `AGENT_VISION.md` first for the why. This document is the concrete "what/how":
schema, verified call table, protocol, and open items. All line references are
against this repo's `FTLGameWin32.h` / `.cpp` files as of commit `ce68ddf`
(2026-09-03).

## Architecture

```
 Python agent  <-- local socket, bidirectional -->  Hyperspace hook (in-process)
      |                                                     |
      |  read state JSON  <----------------------------------  state export
      |  write action JSON --------------------------------->  action dispatch
```

Both directions are pumped from a single per-tick hook, so everything runs on
FTL's own game thread — no cross-thread races with a single-threaded engine, no
raw-input timing games. Per tick:

1. Non-blocking check: is there a pending action message on the socket?
2. If yes, dispatch it to the matching internal call (table below).
3. Call `super()` — let the original tick logic run untouched.
4. Serialize current state to JSON and push it over the socket.

**Open item:** exact hook point for the pump. Needs to be something that runs
once per frame regardless of what UI panel is open (candidate: something in the
`WorldManager` or top-level `CommandGui` loop) — not yet chosen.

## State schema

### Event / choice state — finalized

Source: `LocationEvent` (`FTLGameWin32.h:5807`), `TextString`
(`FTLGameWin32.h:210`), `ChoiceReq` (`FTLGameWin32.h:4004`).

```json
{
  "event": {
    "name": "loc->eventName",
    "text": "loc->text.GetText()",
    "environment": "int",
    "isStore": "bool",
    "isBeacon": "bool",
    "choices": [
      {
        "index": 0,
        "text": "choice->text.GetText()",
        "requirement": {
          "object": "string",
          "minLevel": "int",
          "maxLevel": "int",
          "maxGroup": "int",
          "blue": "bool"
        },
        "hiddenReward": "bool"
      }
    ]
  }
}
```

Note: `.text` is a `TextString` (`data` + `isLiteral`), not a plain string or a
bare ID. `GetText()` is the correct accessor in general. At the
`WorldManager::CreateChoiceBox` hook point specifically, `.data` is already fully
resolved to display text (confirmed: `CustomEvents.cpp` does raw substring
replace directly on `loc->text.data` against already-translated library strings)
— but call `GetText()` anyway for correctness outside that specific hook.

### Ship / combat state — scoped, not yet schema'd in detail

- Player ship: `G_->GetShipManager(0)` or `world->playerShip->shipManager`
- Enemy ship: `G_->GetShipManager(1)` or
  `world->playerShip->enemyShip->shipManager` (`enemyShip` is a `CompleteShip*`)
- This access pattern is confirmed pervasive across the existing codebase —
  `CustomCrew.cpp`, `Augments.cpp`, `CustomBoss.cpp`, `HullNumbers.cpp`,
  `ArtillerySystem.cpp`, `CustomEvents.cpp` all read hull/shields/systems/crew
  this way. Not a hack — it's the mod's own standard pattern.
- **Open item:** enumerate exact fields wanted per system / crew member / room
  before writing the serializer (hull, shield layers, system power/levels, crew
  health/position/skills, room O2, fire/breach state, etc.)

## Action dispatch table (verified against source)

| Action | Call | Source | Notes |
|---|---|---|---|
| Select event choice `i` | `choiceBox->MouseClick(x, y)` with `(x,y)` inside `choiceBox->choiceBoxes[i]` | `ChoiceBox`, `FTLGameWin32.h:3377` | `choiceBoxes` is a `vector<Rect>` the engine already computed — no real screen coordinates involved, we just pick a point inside our own choice's rect |
| Fire weapon `i` at target | `weaponControl->SelectArmament(i)`, then `weaponControl->Fire(points, target, autoFire)` | `WeaponControl`, `FTLGameWin32.h:4117-4150` | `Fire()` takes explicit aim points + target ship id directly, no click simulation. **Open item:** how `points` should be computed (likely target-room-center world coords) and what `target` indexes |
| Move crew member to room | `crewMember->MoveToRoom(roomId, slotId, forceMove)` | `FTLGameWin32.h:2477` | Direct pathing call. No coordinates needed at all — this is the cleanest of the four |
| Adjust system power | `system->IncreasePower(amount, force)` / `system->DecreasePower(force)` | `ShipSystem`, `FTLGameWin32.h:1391,1398` | `system` obtained via `shipManager->GetSystem(systemId)`, same pattern as state export |

## Open / unverified items

- Per-tick pump hook point (see Architecture above).
- `WeaponControl::Fire` aim-point computation.
- Drone control — `DroneControl` shares the `ArmamentControl` base with
  `WeaponControl` (`FTLGameWin32.h:4093`), so likely mirrors the weapon pattern,
  but not checked yet.
- Hacking system control.
- Teleporter / boarding actions.
- Socket implementation: TCP loopback vs. Unix domain socket (macOS target), and
  message framing (newline-delimited JSON vs. length-prefixed).
- OS-level synthetic input fallback (macOS `CGEvent`) — only needed for whatever,
  if anything, doesn't end up having a clean direct call above.

## Source-diving log

Kept so future sessions don't repeat the same greps.

- `LocationEvent` struct: `FTLGameWin32.h:5807`
- `TextString` struct: `FTLGameWin32.h:210`
- `ChoiceReq` struct: `FTLGameWin32.h:4004`
- `ChoiceBox` struct: `FTLGameWin32.h:3377`
- `CombatControl` struct: `FTLGameWin32.h:4154`
- `WeaponControl` struct: `FTLGameWin32.h:4117`
- `DroneControl` struct: `FTLGameWin32.h:4093`
- `CrewControl` struct: `FTLGameWin32.h:4262`
- `CrewMember::MoveToRoom`: `FTLGameWin32.h:2477`
- `ShipSystem::IncreasePower` / `DecreasePower`: `FTLGameWin32.h:1391,1398`
- `WorldManager::CreateChoiceBox` hooked concurrently by 5 files: `ScrollingChoiceBox.cpp`,
  `Debugging.cpp`, `CustomEvents.cpp`, `CustomColors.cpp`, `CustomAugments.cpp`
- Enemy ship access (`playerShip->enemyShip`, `GetShipManager(1)`) confirmed
  pervasive in: `CustomCrew.cpp`, `Augments.cpp`, `CustomBoss.cpp`,
  `HullNumbers.cpp`, `ArtillerySystem.cpp`, `CustomEvents.cpp`
