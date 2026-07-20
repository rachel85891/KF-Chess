"""network_main.py: Stage B6's runnable entry point for the networked
GUI client - opens a real cv2 window, connects to a real running
server (server/main.py), and lets a human actually play a real
networked game.

WHY A NEW REPO-ROOT FILE, NOT A FLAG ON main.py/app.py: main.py and
app.py are both already-established, dedicated entry points with a
specific, external contract (docs/README.md: "the filename the
bootcamp grading platform actually invokes" / "the entry point
docs/spec.md §4 names explicitly") - both read a board+commands DSL
from stdin and print canonical text to stdout, with NO GUI/network
involvement at all. Bolting a `--network` flag onto either would mean
one entry point serving two completely unrelated calling conventions
(stdin/stdout text harness vs. a real cv2 window + WebSocket
connection) - muddying an existing, externally-depended-on contract
for a use case that has nothing to do with it. A genuinely new, real,
human-run production entry point (this is the actual deliverable of
the whole server track, not a demo/manual-only script) belongs at the
repo root, the same level as main.py/app.py, rather than under
scripts/ (which this project already reserves for demo/manual-only
scripts explicitly excluded from the automated suite - see
scripts/demo_stage10_play.py's own docstring for that established
precedent, which this file deliberately does NOT follow, since this
IS a real production entry point, not a demo).

Usage:
    python network_main.py [server_uri]

    server_uri defaults to ws://localhost:8765 (server/main.py's own
    DEFAULT_HOST/DEFAULT_PORT) if omitted - matching
    NetworkGameClient.connect's own "never hardcode a URI, always take
    it as a parameter" convention, just given a sensible default here
    at the one real place a human actually invokes this.
"""

from __future__ import annotations

import sys

from kungfu_chess.client.loop.network_game_loop_runner import ConnectionRejectedError, NetworkGameLoopRunner

DEFAULT_URI = "ws://localhost:8765"


def main() -> None:
    """Connect to a real server and run a real networked game until
    the window closes, 'q' is pressed, or the connection is rejected.

    Returns:
        None.
    """

    uri = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URI

    print(f"Connecting to {uri} ...")
    try:
        runner = NetworkGameLoopRunner(uri)
    except ConnectionRejectedError as exc:
        print(f"Could not join: {exc}")
        return

    print(f"Connected. You are playing as: {runner.assigned_color.name}")
    print("Left-click your own piece, then left-click a destination to move it.")
    print("Press 'q' or close the window to quit.")

    try:
        runner.run()
    finally:
        runner.close()

    print("Game loop ended.")


if __name__ == "__main__":
    main()
