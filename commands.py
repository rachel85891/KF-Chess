"""
Parsing and dispatching of text commands (click / wait / jump / print
board) onto a GameState instance.
"""


def run_commands(state, command_lines):
    for command in command_lines:
        parts = command.split()
        if not parts:
            continue

        if parts[0] == "click" and len(parts) == 3:
            x, y = int(parts[1]), int(parts[2])
            state.handle_click(x, y)

        elif parts[0] == "jump" and len(parts) == 3:
            x, y = int(parts[1]), int(parts[2])
            state.handle_jump(x, y)

        elif parts[0] == "wait" and len(parts) == 2:
            ms = int(parts[1])
            state.handle_wait(ms)

        elif command == "print board":
            state.print_board()

        # Unknown commands are silently ignored for now.