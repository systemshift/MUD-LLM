"""Grid geometry. Positions are always (row, col); row 0 is the top."""

Pos = tuple[int, int]

DIRECTIONS: dict[str, Pos] = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}


def step(pos: Pos, direction: str) -> Pos:
    dr, dc = DIRECTIONS[direction]
    return (pos[0] + dr, pos[1] + dc)


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
