"""Straight/diagonal line geometry, independent of any piece rule."""

Cell = tuple[int, int]


def path_cells(from_row: int, from_col: int, to_row: int, to_col: int) -> list[Cell]:
    """Cells strictly between origin and destination (both exclusive),
    assuming a straight or diagonal line between them."""
    dr = to_row - from_row
    dc = to_col - from_col

    step_r = (dr > 0) - (dr < 0)
    step_c = (dc > 0) - (dc < 0)

    cells: list[Cell] = []
    row, col = from_row + step_r, from_col + step_c
    while (row, col) != (to_row, to_col):
        cells.append((row, col))
        row += step_r
        col += step_c
    return cells
