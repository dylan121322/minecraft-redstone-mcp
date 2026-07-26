#!/usr/bin/env python3
"""
Redstone Display Simulator — frame buffer + lamp grid rendering.

For the long-term goal: output real computer video on a redstone lamp matrix.

Architecture layers:
  1. Frame Buffer: N×M grid of 0/1 values (lamp on/off)
  2. Address Decoder: selects which column/row to write
  3. Shift Register: serial→parallel video data
  4. Display Matrix: N×M redstone lamps
  5. CPU interface: address bus + data bus → display controller
"""

from dataclasses import dataclass, field
from typing import List, Tuple

# ============================================================
# Display Matrix
# ============================================================

class LampMatrix:
    """N×M grid of redstone lamps forming a display."""

    def __init__(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols
        self.pixels = [[0] * cols for _ in range(rows)]

    def set_pixel(self, row: int, col: int, state: int):
        self.pixels[row][col] = 1 if state else 0

    def clear(self):
        self.pixels = [[0] * self.cols for _ in range(self.rows)]

    def render(self) -> str:
        """Render as ASCII art for simulation."""
        lines = []
        lines.append('┌' + '─' * (self.cols * 2 + 1) + '┐')
        for row in self.pixels:
            line = '│ '
            for p in row:
                line += '██' if p else '  '
            line += '│'
            lines.append(line)
        lines.append('└' + '─' * (self.cols * 2 + 1) + '┘')
        return '\n'.join(lines)

    def get_stats(self) -> dict:
        lit = sum(sum(row) for row in self.pixels)
        total = self.rows * self.cols
        return {'lit': lit, 'total': total, 'pct': lit/total*100 if total else 0}


# ============================================================
# Frame Buffer
# ============================================================

@dataclass
class FrameBuffer:
    """Stores a complete frame of video data."""
    width: int
    height: int
    data: List[List[int]] = field(default_factory=list)

    def __post_init__(self):
        self.data = [[0] * self.width for _ in range(self.height)]

    def write_pixel(self, x: int, y: int, value: int):
        self.data[y][x] = 1 if value else 0

    def get_row(self, y: int) -> List[int]:
        return self.data[y]

    def get_column(self, x: int) -> List[int]:
        return [self.data[y][x] for y in range(self.height)]

    @classmethod
    def from_text(cls, text: str, width: int = 16, height: int = 16):
        """Create frame from ASCII art (space=off, non-space=on)."""
        fb = cls(width, height)
        lines = text.strip().split('\n')
        for y, line in enumerate(lines[:height]):
            for x, ch in enumerate(line[:width]):
                fb.write_pixel(x, y, 1 if ch != ' ' else 0)
        return fb

    @classmethod
    def from_function(cls, width: int, height: int, fn):
        """Create frame from a function f(x,y) -> 0|1."""
        fb = cls(width, height)
        for y in range(height):
            for x in range(width):
                fb.write_pixel(x, y, fn(x, y))
        return fb


# ============================================================
# Display Controller
# ============================================================

class DisplayController:
    """
    Redstone display controller — interfaces between CPU and lamp matrix.

    CPU connection:
      - 4-bit address bus (selects which of 16 rows/columns)
      - 4-bit data bus (pixel value for selected position)
      - Control signals: WRITE_ROW, WRITE_COL, CLEAR

    In a real Minecraft build, this would be:
      - 16 redstone wires for address decoding
      - Comparators for address matching
      - Locked repeaters for pixel storage
    """

    def __init__(self, rows: int = 16, cols: int = 16):
        self.matrix = LampMatrix(rows, cols)
        self.current_row = 0
        self.current_col = 0
        self.busy = False  # set during refresh

    def write(self, addr: int, data: int, mode: str = 'row'):
        """Write one row (16 pixels) of data at address."""
        if mode == 'row':
            for x in range(self.matrix.cols):
                self.matrix.set_pixel(addr, x, (data >> (self.matrix.cols - 1 - x)) & 1)
        elif mode == 'col':
            for y in range(self.matrix.rows):
                self.matrix.set_pixel(y, addr, (data >> (self.matrix.rows - 1 - y)) & 1)

    def render(self) -> str:
        return self.matrix.render()

    def get_stats(self) -> dict:
        return self.matrix.get_stats()


# ============================================================
# Test: Simple pattern display
# ============================================================

def test_display():
    """Generate and display test patterns."""
    print("=" * 60)
    print("  Display Controller — Pattern Tests")
    print("=" * 60)

    # Test 1: Checkerboard pattern
    print("\n[1] Checkerboard (16×16):")
    ctrl = DisplayController(16, 16)
    for y in range(16):
        row_data = 0
        for x in range(16):
            if (x + y) % 2 == 0:
                row_data |= 1 << (15 - x)
        ctrl.write(y, row_data, 'row')
    print(ctrl.render())

    # Test 2: Rectangle
    print("\n[2] Filled Rectangle (8×8 display):")
    ctrl2 = DisplayController(8, 8)
    for y in range(2, 6):
        row_data = 0
        for x in range(2, 6):
            row_data |= 1 << (7 - x)
        ctrl2.write(y, row_data, 'row')
    print(ctrl2.render())

    # Test 3: Letter pattern
    print("\n[3] Letter 'A' on 8×8:")
    letter_a = [
        "  ####  ",
        " #    # ",
        " #    # ",
        " ###### ",
        " #    # ",
        " #    # ",
        " #    # ",
        "        ",
    ]
    ctrl3 = DisplayController(8, 8)
    for y, line in enumerate(letter_a):
        row_data = 0
        for x, ch in enumerate(line):
            if ch == '#':
                row_data |= 1 << (7 - x)
        ctrl3.write(y, row_data, 'row')
    print(ctrl3.render())

    # Test 4: Scale — video-frame-sized
    print(f"\n[4] Scale test: 32×24 display")
    ctrl4 = DisplayController(32, 24)
    # Draw a sine wave approximation
    import math
    for x in range(32):
        y = int(12 + 8 * math.sin(x / 32 * 4 * math.pi))
        if 0 <= y < 24:
            ctrl4.matrix.set_pixel(y, x, 1)
    stats = ctrl4.get_stats()
    print(f"  Size: 32×24 = {stats['total']} lamps, {stats['lit']} lit ({stats['pct']:.1f}%)")
    print(f"  For Minecraft: {stats['total']} lamps ≈ ~{stats['total'] * 3} blocks total (with wiring)")

    return True


if __name__ == '__main__':
    test_display()
