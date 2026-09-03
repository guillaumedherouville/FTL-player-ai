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
