import json
import os
import socket
import subprocess
import time

SOCKET_PATH = "/tmp/ftl_agent.sock"
DECISION_DELAY = 15  # seconds before acting — read the event and pause FTL if you want to intervene


def pick_choice(event: dict) -> int:
    text = event.get("text", "")
    choices = event.get("choices", [])

    if not choices:
        return 0

    # Print full event so you can read it in the terminal
    print()
    print("=" * 60)
    print(f"EVENT: {text}")
    print("CHOICES:")
    for c in choices:
        print(f"  {c['index']}: {c['text']}")
    print("=" * 60)

    # Visible countdown
    for remaining in range(DECISION_DELAY, 0, -1):
        print(f"\r[agent] Claude deciding in {remaining:2d}s... (pause FTL now if you want to take over)", end="", flush=True)
        time.sleep(1)
    print()

    choices_str = "\n".join(f"{c['index']}: {c['text']}" for c in choices)
    prompt = (
        "You are playing FTL: Faster Than Light. An event has occurred.\n\n"
        f"Event:\n{text}\n\n"
        f"Choices:\n{choices_str}\n\n"
        "Reply with only the index number of your chosen option. No other text."
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=30
        )
        raw = result.stdout.strip()
        print(f"[agent] Claude chose: {raw} → {choices[int(raw)]['text']}")
        return int(raw)
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[agent] Claude call failed ({e}), defaulting to 0")
        return 0


def serve():
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
                idx = pick_choice(event)
                try:
                    conn.sendall(f'{{"index":{idx}}}\n'.encode())
                except BrokenPipeError:
                    print("[agent] FTL disconnected mid-decision")
                    return
    finally:
        conn.close()
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


if __name__ == "__main__":
    serve()
