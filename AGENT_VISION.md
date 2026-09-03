# Agent Vision — Autonomous FTL Player

## Goal

Build an AI agent that plays *FTL: Faster Than Light* in Guillaume's place, with the
eventual aim of winning full runs (beating the flagship) with no human input.

This document is the entry point for anyone (human or Claude Code session) picking
this project up cold. Read this first, then `AGENT_DESIGN.md` for the technical
detail.

## Why this repo

This checkout is **upstream FTL-Hyperspace** (github.com/FTL-Hyperspace/FTL-Hyperspace),
a mature, actively maintained C++ binary-mod framework for FTL, built on the ZHL
hooking library. We are not forking it to change gameplay — we're using it as the
vehicle to get an agent clean, structured, real-time access to FTL's internal game
state, and a way to inject actions back in.

FTL has no official API. The realistic options for state access were:
1. Memory-reading via a mod framework (chosen)
2. Vision / OCR on the rendered window
3. A hybrid of the two

Hyperspace was chosen over rolling a from-scratch memory reader because it already
exposes deep internal game state (ship/combat/crew/event data) that dozens of
existing mods in this same codebase already consume — piggybacking on that is far
less work and far more robust than reverse-engineering the binary from zero.

## Core architectural decision

A custom hook layer (not yet written) added to this Hyperspace checkout will:
1. Serialize live game state (ship, combat, event/choice state) to JSON once per
   game tick.
2. Push it over a local socket to an external Python agent process.
3. Read any pending "action" message back from that same socket.
4. Dispatch the action to FTL's own internal engine functions **directly** —
   calling the same functions the game's own UI code calls (e.g.
   `weaponControl->Fire(...)`, `crewMember->MoveToRoom(...)`) rather than
   simulating OS-level mouse/keyboard input against the game window.

This last point was a deliberate pivot during design: FTL's own controller classes
(`WeaponControl`, `CrewControl`, `ChoiceBox`, `ShipSystem`, ...) already expose
clean, high-level action methods that operate on internal coordinates/state, not
real screen pixels. Calling them directly is more reliable than OS-level synthetic
input (no window-focus, DPI-scaling, or animation-timing fragility) and was
confirmed against the actual source for every action category needed so far. See
`AGENT_DESIGN.md` for the verified call table. OS-level synthetic input remains a
fallback of last resort for anything that doesn't have a clean direct call.

## Status as of 2026-09-03

Pure research/design phase — **no agent code has been written yet**. Work so far has
been entirely source-diving this repo to de-risk the design before writing anything.

Verified (see `AGENT_DESIGN.md` for line references):
- Enemy ship state is fully reachable the same way the game's own code reads it
  (`world->playerShip->enemyShip`, `G_->GetShipManager(1)`).
- `LocationEvent` / `Choice` / `TextString` / `ChoiceReq` struct layouts, and how
  event/choice text resolves.
- `WorldManager::CreateChoiceBox` is a safe interception point — 5 existing mod
  files already hook it concurrently, proving ZHL hook-chaining works fine there.
- Direct engine calls exist for: selecting an event choice, firing a weapon at a
  target, moving a crew member to a room, and adjusting system power.

Not yet verified / next up:
- Aim-point computation for `WeaponControl::Fire`.
- Drone control, hacking system control, teleporter/boarding actions.
- Exact per-tick hook point to pump the socket from.
- Socket implementation (TCP loopback vs. Unix domain socket) and message framing.

## How to pick this up

1. Read `AGENT_DESIGN.md`.
2. Scaffold the hook layer (new `.cpp`/`.h` pair in this repo) that opens the local
   socket and pumps it once per tick.
3. Implement state serialization for the state that's already scoped.
4. Implement the action-dispatch table from `AGENT_DESIGN.md`.
5. Build the external Python agent as pure plumbing first (read state, write a
   no-op or random action back) — prove the round-trip before writing any actual
   game-playing logic.
6. Only after the plumbing works end-to-end, start on decision-making/policy.

## Constraints established so far

- Guillaume is on macOS; Hyperspace supports Mac (`FTLGameMacOSAMD64.*` in this
  repo), so the hook layer and any OS-level fallback should target macOS first.
- Prefer direct in-process engine calls over OS-level synthetic input wherever a
  clean call exists.
- This folder is Guillaume's real working checkout — treat it as authoritative,
  not something to reclone or duplicate elsewhere.
