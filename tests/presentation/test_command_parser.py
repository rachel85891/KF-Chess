from unittest.mock import Mock

from kungfu_chess.presentation.cli.command_parser import parse_command

CELL_SIZE = 100


def test_click_converts_pixels_to_row_col():
    command = parse_command("click 250 130", CELL_SIZE)
    engine = Mock()
    command(engine, Mock())
    engine.handle_click.assert_called_once_with(1, 2)  # row=y//100, col=x//100


def test_jump_converts_pixels_to_row_col():
    command = parse_command("jump 0 300", CELL_SIZE)
    engine = Mock()
    command(engine, Mock())
    engine.handle_jump.assert_called_once_with(3, 0)


def test_wait_passes_milliseconds_through():
    command = parse_command("wait 1500", CELL_SIZE)
    engine = Mock()
    command(engine, Mock())
    engine.handle_wait.assert_called_once_with(1500)


def test_print_board_settles_then_prints_encoded_board(capsys):
    command = parse_command("print board", CELL_SIZE)
    engine = Mock()
    codec = Mock()
    codec.encode.return_value = "wK"

    command(engine, codec)

    engine.settle_due_events.assert_called_once()
    codec.encode.assert_called_once_with(engine.board)
    assert capsys.readouterr().out == "wK\n"


def test_malformed_click_wrong_arg_count_is_ignored():
    assert parse_command("click 1", CELL_SIZE) is None


def test_unknown_command_is_ignored():
    assert parse_command("foobar", CELL_SIZE) is None


def test_empty_line_is_ignored():
    assert parse_command("", CELL_SIZE) is None


def test_print_board_requires_exact_whole_line_match():
    """Mirrors the original dispatcher's fragile whole-line equality
    check ('command == "print board"'), not a split-and-rejoin match."""
    assert parse_command("print   board", CELL_SIZE) is None
