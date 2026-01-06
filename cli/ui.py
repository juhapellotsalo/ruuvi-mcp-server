"""UI utilities for the CLI."""

import atexit
import os
import threading
import time

# ANSI escape codes
DIM = "\033[2m"
RESET = "\033[0m"
ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
CURSOR_HOME = "\033[H"
CLEAR_SCREEN = "\033[J"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

_in_fullscreen = False


def enter_fullscreen():
    """Switch to alternate screen buffer and clear."""
    global _in_fullscreen
    print(ALT_SCREEN_ON, end="", flush=True)
    print(CURSOR_HOME + CLEAR_SCREEN, end="", flush=True)
    _in_fullscreen = True
    atexit.register(exit_fullscreen)


def exit_fullscreen():
    """Restore main screen buffer."""
    global _in_fullscreen
    if _in_fullscreen:
        print(SHOW_CURSOR + ALT_SCREEN_OFF, end="", flush=True)
        _in_fullscreen = False


def separator_line() -> str:
    """Return a dim grey horizontal line spanning terminal width."""
    try:
        width = os.get_terminal_size().columns
    except OSError:
        width = 80
    return f"{DIM}{'─' * width}{RESET}"


def draw_header():
    """Draw the application header at the top of the screen."""
    print(CURSOR_HOME + CLEAR_SCREEN, end="", flush=True)
    print("Ruuvi Data Advisor")
    print(f"{DIM}Type help for commands, exit to quit{RESET}")
    print()


class Spinner:
    """Animated spinner for visual feedback."""

    def __init__(self, message: str = "Loading"):
        self.message = message
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.running = False
        self.thread = None

    def _spin(self):
        i = 0
        while self.running:
            frame = self.frames[i % len(self.frames)]
            print(f"\r{frame} {self.message}...", end="", flush=True)
            time.sleep(0.1)
            i += 1

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._spin)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        print("\r" + " " * (len(self.message) + 10) + "\r", end="", flush=True)
