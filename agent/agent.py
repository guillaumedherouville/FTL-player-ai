import json
import os
import socket

SOCKET_PATH = "/tmp/ftl_agent.sock"


def pick_choice(event: dict) -> int:
    # Always pick the first choice — just testing the hook plumbing for now
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
