"""Main CLI application using cmd module."""

import cmd
import readline
import os

from .ui import (
    DIM,
    RESET,
    draw_header,
    enter_fullscreen,
    exit_fullscreen,
    separator_line,
)
from .commands.gateway import handle_gateway
from .commands.cloud import handle_cloud
from .commands.mqtt import handle_mqtt
from .commands.ble import handle_ble
from .commands.devices import handle_devices
from .commands.status import do_status
from .commands.storage import do_storage


# History file for readline
HISTORY_FILE = os.path.expanduser("~/.ruuvi_cli_history")


class RuuviCLI(cmd.Cmd):
    """Interactive CLI for Ruuvi Data Advisor."""

    intro = ""
    prompt = "> "
    use_rawinput = True
    interactive = True  # Set to False for single command execution

    def preloop(self):
        """Set up the CLI before starting."""
        if not self.interactive:
            return

        # Load command history
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)

        # Enter fullscreen mode
        enter_fullscreen()
        draw_header()

    def postloop(self):
        """Clean up after exiting."""
        if not self.interactive:
            return

        # Save command history
        readline.write_history_file(HISTORY_FILE)
        exit_fullscreen()

    def precmd(self, line: str) -> str:
        """Pre-process command line."""
        if self.interactive:
            print(separator_line())
        # Strip leading slash if present (for /command style)
        if line.startswith("/"):
            line = line[1:]
        # Convert hyphens to underscores for command names (e.g., gateway-test -> gateway_test)
        parts = line.split(None, 1)
        if parts:
            parts[0] = parts[0].replace("-", "_")
            line = " ".join(parts)
        return line

    def postcmd(self, stop: bool, line: str) -> bool:
        """Post-process after command execution."""
        if self.interactive:
            print(separator_line())
        return stop

    def emptyline(self):
        """Do nothing on empty input."""
        pass

    def default(self, line: str):
        """Handle unknown commands."""
        print(f"Unknown command: {line}")
        print("Type 'help' for available commands.")

    # --- Commands ---

    def do_gateway(self, arg: str):
        """Gateway commands. Usage: gateway [config|test|poll]"""
        handle_gateway(arg)

    def do_cloud(self, arg: str):
        """Cloud commands. Usage: cloud [auth|sensors|history|sync]"""
        handle_cloud(arg)

    def do_mqtt(self, arg: str):
        """MQTT commands. Usage: mqtt [config|listen|monitor]"""
        handle_mqtt(arg)

    def do_ble(self, arg: str):
        """BLE commands. Usage: ble [scan|sync|history]"""
        handle_ble(arg)

    def do_storage(self, arg: str):
        """Configure storage settings."""
        do_storage(arg)

    def do_devices(self, arg: str):
        """Device commands. Usage: devices"""
        handle_devices(arg)

    def do_status(self, arg: str):
        """Show configuration status."""
        do_status(arg)

    def do_exit(self, arg: str):
        """Exit the CLI."""
        return True

    def do_quit(self, arg: str):
        """Exit the CLI."""
        return True

    def do_EOF(self, arg: str):
        """Handle Ctrl+D."""
        print()
        return True

    def do_help(self, arg: str):
        """Show available commands."""
        if arg:
            # Show help for specific command
            super().do_help(arg)
        else:
            print("""Available commands:

  gateway                Show gateway status and subcommands
    gateway config       Configure gateway connection
    gateway test         Test gateway connection
    gateway poll         Poll and display readings (no storage)
    gateway poll raw     Fetch raw JSON payload

  cloud                  Show cloud status and subcommands
    cloud auth           Authenticate with Ruuvi Cloud
    cloud sensors        List sensors
    cloud sensors raw    List sensors (raw JSON)
    cloud history [dev]  Fetch sensor history (prompts if omitted)
    cloud sync [dev] [n] Sync to local database (one device or all)

  mqtt                   Show MQTT status and subcommands
    mqtt config          Configure MQTT broker
    mqtt listen          Subscribe and store readings
    mqtt monitor         Subscribe and display only (no storage)

  ble                    Show BLE status and subcommands
    ble scan             Scan for Ruuvi devices
    ble listen           Listen to broadcasts and store
    ble monitor          Listen to broadcasts (no storage)
    ble sync [dev] [period]  Sync history to database
    ble history [dev] [period] Display history (no storage)

  devices                List configured devices
    devices add          Add a new device

  storage                Configure storage settings
  status                 Show all configuration status
  help [command]         Show help
  exit                   Exit the CLI
""")


def main():
    """Run the interactive CLI or execute a single command."""
    import sys

    if len(sys.argv) > 1:
        # Execute command directly without interactive mode
        command = " ".join(sys.argv[1:])
        cli = RuuviCLI()
        cli.interactive = False
        cli.onecmd(cli.precmd(command))
    else:
        # Interactive mode
        try:
            RuuviCLI().cmdloop()
        except KeyboardInterrupt:
            exit_fullscreen()
            print()
