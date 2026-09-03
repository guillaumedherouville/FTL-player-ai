# FTL Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bare-minimum agent that controls the player's ship in FTL: auto-fires weapons via FTL's own engine and picks event choices via Claude (Haiku).

**Architecture:** A Hyperspace hook on `CommandGui::OnLoop` (C++) runs inside FTL's process each frame. It enables auto-fire during combat and pushes event state as newline-delimited JSON over a Unix domain socket. A Python process listens on that socket, calls the Claude API for each event, and sends back a choice index. The C++ hook reads that index non-blockingly and dispatches a `ChoiceBox::MouseClick`.

**Tech Stack:** C++17 (Hyperspace/ZHL hook macros), Python 3.10+, Anthropic Python SDK (`anthropic`), Unix domain socket (macOS).

**Spec:** `AGENT_VISION.md` and `AGENT_DESIGN.md` in repo root.

## Global Constraints

- Target platform: macOS (the `FTLGameMacOSAMD64.*` build path). All socket code must be POSIX — no Win32.
- No new CMakeLists.txt edits required: `file(GLOB ROOT_SOURCES *.cpp *.h)` picks up any file placed in the repo root automatically.
- No external JSON library: the state schema is tiny — hand-roll JSON strings.
- Do not call `SetAutoFire` every tick if it's already set — check first or rely on idempotency (see Task 4).
- ZHL hook convention: include `LOG_HOOK(...)` as the first line inside every `HOOK_METHOD` body (see `MoreInfoButton.cpp:9` for the pattern). Call `super()` before your post-processing code; call it after your pre-processing code. Tasks below specify which applies.
- Python agent is the **socket server** (binds + listens). C++ hook is the **socket client** (connects). Start Python agent before launching FTL.
- Socket path: `/tmp/ftl_agent.sock`.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `AgentHook.h` | Create (repo root) | Declarations for socket helpers and the serializer |
| `AgentHook.cpp` | Create (repo root) | `CommandGui::OnInit` hook (socket connect) + `CommandGui::OnLoop` hook (auto-fire, event send/recv, choice dispatch) |
| `agent/agent.py` | Create | Python server: socket accept, Claude API call, send choice index |
| `agent/requirements.txt` | Create | `anthropic` dependency |

---

### Task 1: Socket infrastructure (C++)

**Files:**
- Create: `AgentHook.h`
- Create: `AgentHook.cpp` (socket helpers + `OnInit` hook only)

**Interfaces:**
- Produces:
  - `AgentSocket_Init()` — opens and connects the Unix socket; called once from the `OnInit` hook
  - `AgentSocket_Send(const std::string &json) -> bool` — non-blocking send of one newline-terminated JSON line; returns false if disconnected
  - `AgentSocket_Recv() -> std::string` — non-blocking recv of one newline-delimited line; returns `""` if nothing available

- [ ] **Step 1: Create `AgentHook.h`**

```cpp
#pragma once
#include <string>

void AgentSocket_Init();
bool AgentSocket_Send(const std::string &json);
std::string AgentSocket_Recv();
```

- [ ] **Step 2: Create `AgentHook.cpp` with socket helpers**

```cpp
#include "AgentHook.h"
#include "Global.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>

static const char *SOCKET_PATH = "/tmp/ftl_agent.sock";
static int g_sockfd = -1;
static std::string g_recvBuf;

void AgentSocket_Init()
{
    g_sockfd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_sockfd < 0) return;

    fcntl(g_sockfd, F_SETFL, O_NONBLOCK);

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    if (connect(g_sockfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(g_sockfd);
        g_sockfd = -1;
    }
}

bool AgentSocket_Send(const std::string &json)
{
    if (g_sockfd < 0) return false;
    std::string msg = json + "\n";
    ssize_t sent = send(g_sockfd, msg.c_str(), msg.size(), MSG_DONTWAIT);
    return sent == (ssize_t)msg.size();
}

std::string AgentSocket_Recv()
{
    if (g_sockfd < 0) return "";

    char buf[4096];
    ssize_t n = recv(g_sockfd, buf, sizeof(buf) - 1, MSG_DONTWAIT);
    if (n > 0) {
        buf[n] = '\0';
        g_recvBuf += buf;
    }

    auto pos = g_recvBuf.find('\n');
    if (pos == std::string::npos) return "";

    std::string line = g_recvBuf.substr(0, pos);
    g_recvBuf.erase(0, pos + 1);
    return line;
}
```

- [ ] **Step 3: Add the `OnInit` hook at the bottom of `AgentHook.cpp`**

```cpp
HOOK_METHOD(CommandGui, OnInit, () -> void)
{
    LOG_HOOK("HOOK_METHOD -> CommandGui::OnInit -> Begin (AgentHook.cpp)\n")
    super();
    AgentSocket_Init();
}
```

Note: `super()` is called first (matching the pattern in `MoreInfoButton.cpp`) so FTL's own init runs before we open the socket.

- [ ] **Step 4: Build to verify it compiles**

From the repo's build directory (however you normally build Hyperspace — cmake + make or the devcontainer):
```bash
cmake --build . 2>&1 | grep -E "error:|AgentHook"
```
Expected: no errors, `AgentHook.cpp` appears in the build output.

- [ ] **Step 5: Smoke-test the socket connect**

In one terminal, start a netcat listener:
```bash
nc -lU /tmp/ftl_agent.sock
```
Launch FTL with Hyperspace loaded. The `nc` process should accept the connection (no output, but no error either). Kill FTL, verify `nc` exits cleanly.

- [ ] **Step 6: Commit**

```bash
git add AgentHook.h AgentHook.cpp
git commit -m "feat: add AgentHook socket infrastructure and OnInit connect"
```

---

### Task 2: Event serialization + send

**Files:**
- Modify: `AgentHook.cpp` — add `SerializeEvent()` helper and the `OnLoop` hook skeleton with event-send logic

**Interfaces:**
- Consumes: `AgentSocket_Send()` from Task 1; `CommandGui`, `ChoiceBox`, `ChoiceText` from `FTLGameWin32.h`
- Produces: `OnLoop` hook that, when `choiceBox.bOpen` is true and the event is new, sends one JSON line of the form:
  ```json
  {"event":{"text":"...","choices":[{"index":0,"text":"..."},{"index":1,"text":"..."}]}}
  ```

Key struct facts (verified in `FTLGameWin32.h`):
- `CommandGui::choiceBox` — `ChoiceBox` value (not pointer), directly accessible as `this->choiceBox`
- `ChoiceBox::bOpen` — `bool`, inherited from `FocusWindow` (line 3305)
- `ChoiceBox::mainText` — `std::string` (line 3398)
- `ChoiceBox::choices` — `std::vector<ChoiceText>` (line 3399)
- `ChoiceText::text` — plain `std::string` (line 3363) — already resolved, no `.GetText()` needed

- [ ] **Step 1: Add `QuoteJson` and `SerializeEvent` helpers above the hook in `AgentHook.cpp`**

```cpp
static std::string QuoteJson(const std::string &s)
{
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"')       out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c < 0x20)  out += ' '; // drop other control chars
        else                out += c;
    }
    out += "\"";
    return out;
}

static std::string SerializeEvent(const ChoiceBox &box)
{
    std::string json = "{\"event\":{\"text\":";
    json += QuoteJson(box.mainText);
    json += ",\"choices\":[";
    for (int i = 0; i < (int)box.choices.size(); i++) {
        if (i > 0) json += ",";
        json += "{\"index\":" + std::to_string(i) + ",\"text\":";
        json += QuoteJson(box.choices[i].text);
        json += "}";
    }
    json += "]}}";
    return json;
}
```

- [ ] **Step 2: Add the `OnLoop` hook with event-send logic**

Add after the `OnInit` hook. The static `lastEventText` tracks the last sent event so we don't spam the socket every tick while waiting for a response.

```cpp
static std::string lastEventText;
static bool waitingForAction = false;

HOOK_METHOD(CommandGui, OnLoop, () -> void)
{
    LOG_HOOK("HOOK_METHOD -> CommandGui::OnLoop -> Begin (AgentHook.cpp)\n")

    // Send event to agent when a new choice box appears
    if (this->choiceBox.bOpen && !this->choiceBox.choices.empty()) {
        if (!waitingForAction && this->choiceBox.mainText != lastEventText) {
            std::string json = SerializeEvent(this->choiceBox);
            if (AgentSocket_Send(json)) {
                lastEventText = this->choiceBox.mainText;
                waitingForAction = true;
            }
        }
    } else {
        // Choice box closed — reset state
        lastEventText.clear();
        waitingForAction = false;
    }

    super();
}
```

- [ ] **Step 3: Build**

```bash
cmake --build . 2>&1 | grep "error:"
```
Expected: no errors.

- [ ] **Step 4: Test — observe JSON on the wire**

Start a listener that prints what it receives:
```bash
nc -lU /tmp/ftl_agent.sock
```
Launch FTL, trigger an event (e.g. land on a beacon). Verify JSON like the following appears in the terminal:
```json
{"event":{"text":"You find a distress beacon...","choices":[{"index":0,"text":"Investigate"},{"index":1,"text":"Ignore"}]}}
```

- [ ] **Step 5: Commit**

```bash
git add AgentHook.cpp
git commit -m "feat: serialize choice box to JSON and push to agent socket"
```

---

### Task 3: Action recv + ChoiceBox click dispatch

**Files:**
- Modify: `AgentHook.cpp` — add recv + dispatch logic inside the `OnLoop` hook

**Interfaces:**
- Consumes: `AgentSocket_Recv()` from Task 1; `ChoiceBox::choiceBoxes` (`vector<Globals::Rect>`), `ChoiceBox::MouseClick(int, int)`
- Expected incoming JSON: `{"index":N}` where N is 0-based choice index
- `Globals::Rect` fields: `int x, y, w, h` (line 942 in `FTLGameWin32.h`)

- [ ] **Step 1: Add `ParseChoiceIndex` helper above the `OnLoop` hook**

```cpp
// Returns -1 on parse failure.
static int ParseChoiceIndex(const std::string &json)
{
    auto pos = json.find("\"index\"");
    if (pos == std::string::npos) return -1;
    pos = json.find(':', pos);
    if (pos == std::string::npos) return -1;
    try {
        return std::stoi(json.substr(pos + 1));
    } catch (...) {
        return -1;
    }
}
```

- [ ] **Step 2: Add the recv + dispatch block inside `OnLoop`, before `super()`**

Replace the existing `OnLoop` hook body with the updated version:

```cpp
static std::string lastEventText;
static bool waitingForAction = false;

HOOK_METHOD(CommandGui, OnLoop, () -> void)
{
    LOG_HOOK("HOOK_METHOD -> CommandGui::OnLoop -> Begin (AgentHook.cpp)\n")

    if (this->choiceBox.bOpen && !this->choiceBox.choices.empty()) {
        // Send new event if we haven't yet
        if (!waitingForAction && this->choiceBox.mainText != lastEventText) {
            std::string json = SerializeEvent(this->choiceBox);
            if (AgentSocket_Send(json)) {
                lastEventText = this->choiceBox.mainText;
                waitingForAction = true;
            }
        }

        // Poll for a response
        if (waitingForAction) {
            std::string action = AgentSocket_Recv();
            if (!action.empty()) {
                int idx = ParseChoiceIndex(action);
                auto &boxes = this->choiceBox.choiceBoxes;
                if (idx >= 0 && idx < (int)boxes.size()) {
                    int cx = boxes[idx].x + boxes[idx].w / 2;
                    int cy = boxes[idx].y + boxes[idx].h / 2;
                    this->choiceBox.MouseClick(cx, cy);
                }
                waitingForAction = false;
            }
        }
    } else {
        lastEventText.clear();
        waitingForAction = false;
    }

    super();
}
```

- [ ] **Step 3: Build**

```bash
cmake --build . 2>&1 | grep "error:"
```

- [ ] **Step 4: Test — manually send a choice**

Start netcat in two-way mode:
```bash
nc -lU /tmp/ftl_agent.sock
```
Launch FTL, trigger an event. Observe the JSON. Then type the following into the netcat terminal and press Enter:
```
{"index":0}
```
Expected: FTL picks the first choice and the event resolves.

- [ ] **Step 5: Commit**

```bash
git add AgentHook.cpp
git commit -m "feat: recv choice index from agent socket and dispatch ChoiceBox click"
```

---

### Task 4: Auto-fire during combat

**Files:**
- Modify: `AgentHook.cpp` — add auto-fire toggle inside the `OnLoop` hook

**Interfaces:**
- Consumes: `CommandGui::combatControl` (`CombatControl` value, line 4802), `CombatControl::open` (`bool`, line 4209), `CombatControl::weapControl` (`WeaponControl` value, line 4189), `WeaponControl::SetAutoFire(bool)` (line 6780)

- [ ] **Step 1: Add auto-fire call at the top of the `OnLoop` hook body (before the choice-box block)**

```cpp
    // Enable auto-fire whenever combat is active
    if (this->combatControl.open && !this->combatControl.weapControl.autoFire) {
        this->combatControl.weapControl.SetAutoFire(true);
    }
```

To find the field name for the auto-fire bool, grep first:
```bash
grep -n "autoFire\b" FTLGameWin32.h
```
Expected result: `bool autoFire;` inside `WeaponControl`. Use that field name in the guard above. If the field name differs, adjust accordingly.

- [ ] **Step 2: Build**

```bash
cmake --build . 2>&1 | grep "error:"
```

- [ ] **Step 3: Test — ship fires on its own in combat**

Launch FTL, pick a ship and start a run. Enter the first combat encounter. Verify that the player ship's weapons fire automatically without any keyboard/mouse input.

- [ ] **Step 4: Commit**

```bash
git add AgentHook.cpp
git commit -m "feat: enable auto-fire on player weapons during combat"
```

---

### Task 5: Python agent

**Files:**
- Create: `agent/agent.py`
- Create: `agent/requirements.txt`

**Interfaces:**
- Consumes: socket on `/tmp/ftl_agent.sock` (server side — binds and listens)
- Receives: newline-delimited JSON `{"event":{"text":"...","choices":[{"index":N,"text":"..."},...]}}`
- Sends back: `{"index":N}\n`
- Claude model to use: `claude-haiku-4-5-20251001` (fast, cheap, sufficient for text choice)

- [ ] **Step 1: Create `agent/requirements.txt`**

```
anthropic
```

- [ ] **Step 2: Install dependencies**

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 3: Create `agent/agent.py`**

```python
import json
import os
import socket

import anthropic

SOCKET_PATH = "/tmp/ftl_agent.sock"
MODEL = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def pick_choice(event: dict) -> int:
    text = event.get("text", "")
    choices = event.get("choices", [])

    if not choices:
        return 0

    choices_str = "\n".join(f"{c['index']}: {c['text']}" for c in choices)
    prompt = (
        "You are playing FTL: Faster Than Light. An event has occurred.\n\n"
        f"Event:\n{text}\n\n"
        f"Choices:\n{choices_str}\n\n"
        "Reply with only the index number of your chosen option. No other text."
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=8,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        return int(message.content[0].text.strip())
    except (ValueError, IndexError, AttributeError):
        print(f"[agent] Bad response from Claude, defaulting to 0")
        return 0


def serve():
    # Remove stale socket file if present
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(1)
    print(f"[agent] Listening on {SOCKET_PATH} — launch FTL now")

    conn, _ = server.accept()
    print("[agent] FTL connected")

    buf = ""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                print("[agent] FTL disconnected")
                break
            buf += data.decode("utf-8", errors="replace")

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    state = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[agent] JSON parse error: {e} — line: {line!r}")
                    continue

                event = state.get("event", {})
                print(f"[agent] Event: {event.get('text', '')[:80]}")
                idx = pick_choice(event)
                print(f"[agent] Chose index {idx}")
                conn.sendall(f'{{"index":{idx}}}\n'.encode())
    finally:
        conn.close()
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == "__main__":
    serve()
```

- [ ] **Step 4: Test — mock socket round-trip without FTL**

In one terminal, run the agent:
```bash
cd agent && source .venv/bin/activate
ANTHROPIC_API_KEY=sk-... python agent.py
```

In a second terminal, act as FTL:
```bash
nc -U /tmp/ftl_agent.sock
```
Then paste:
```
{"event":{"text":"A nearby ship hails you. They claim to be merchants.","choices":[{"index":0,"text":"Trade with them"},{"index":1,"text":"Ignore and move on"},{"index":2,"text":"Attack!"}]}}
```
Expected: the agent prints the event text, calls Claude, and you see `{"index":N}` printed back in the nc terminal within a few seconds.

- [ ] **Step 5: Full end-to-end test**

```bash
# Terminal 1 — agent
cd agent && source .venv/bin/activate
ANTHROPIC_API_KEY=sk-... python agent.py

# Terminal 2 — launch FTL with Hyperspace
```
Play until the first event choice appears. Verify:
1. The agent terminal prints the event text.
2. Claude's choice index appears in the agent terminal.
3. FTL automatically clicks that choice.

- [ ] **Step 6: Commit**

```bash
git add agent/
git commit -m "feat: add Python agent that calls Claude for event choices"
```

---

## Self-Review

**Spec coverage:**
- AGENT_VISION.md §"How to pick this up" steps 2–5: scaffold hook ✓, state serialization ✓, action dispatch ✓, Python plumbing ✓
- AGENT_DESIGN.md action table — "Select event choice i" via `ChoiceBox::MouseClick` ✓
- AGENT_DESIGN.md — per-tick hook point (`CommandGui::OnLoop`) ✓
- Auto-fire (enablement of `SetAutoFire`) ✓
- macOS target (Unix domain socket, POSIX APIs) ✓

**Open items acknowledged but out of scope for this MVP:**
- Aim-point computation for `WeaponControl::Fire` (auto-fire handles this)
- Drone/hacking/teleporter control
- Ship/combat state serialization (not needed for event-choice MVP)
- RL training loop and in-process game reset

**Placeholder scan:** None found.

**Type consistency:** `ChoiceText::text` is `std::string` throughout (verified line 3363). `Globals::Rect` fields `x, y, w, h` are `int` throughout (verified line 947). `AgentSocket_Send`/`AgentSocket_Recv` signatures match between header and usage in hook.
