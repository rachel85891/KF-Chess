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

STAGE C1 ("Home Screen v1") - WHY THE SHELL LOGIN STEP WAS ADDED HERE,
NOT AS A NEW, SEPARATE REPO-ROOT ENTRY POINT: unlike the "new repo-root
file" reasoning above (a genuinely different CALLING CONVENTION - GUI+
network vs. stdin/stdout DSL - justified giving network_main.py its
own file instead of extending main.py/app.py), a shell username prompt
in front of the SAME GUI+network flow does not introduce a new calling
convention at all - a human still runs `python network_main.py
[server_uri]` and ends up playing the same real networked game, just
after one added text prompt. Splitting that into a THIRD, parallel
entry point would duplicate this file's own argv-parsing/DEFAULT_URI
convention for no genuine reason. This file's own `main()` therefore
stays the single, thin composition root (mirrors docs/README.md's own
established "thin entry point, real logic in an importable module"
pattern - main.py/app.py's own one-line delegation to
app_extra.run_extra) - it only resolves `uri` from argv (its own,
pre-existing job) and delegates every actual login/connect/launch
decision to kungfu_chess.client.home_screen.run_shell_login_and_launch
(see that module's own docstring for the full reasoning behind the
prompt/connect/welcome/launch sequence, and for why the username
collected there is cosmetic-only at this stage). NetworkGameLoopRunner
itself is untouched by this stage - run_shell_login_and_launch's own
default connect_fn/launch_gui_fn reproduce this file's own previous
connect/run/close sequence verbatim.

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

from kungfu_chess.client.home_screen import run_shell_login_and_launch

DEFAULT_URI = "ws://localhost:8765"


def main() -> None:
    """Resolve the server URI from argv, then run the real Stage C1
    shell login flow - which prompts for a username, connects, shows
    the welcome (or server_full) message, and launches the real GUI -
    see kungfu_chess.client.home_screen's own module docstring for the
    full reasoning.

    Returns:
        None.
    """

    uri = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URI
    run_shell_login_and_launch(uri)


if __name__ == "__main__":
    main()
