"""Command-line engine for The Last Light adventure."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from story import START_SCENE, STORY

DEFAULT_SAVE_FILE = Path("adventure-save.json")


@dataclass
class GameState:
    scene: str = START_SCENE
    inventory: list[str] = field(default_factory=list)


class Adventure:
    """Owns a story run and provides testable choice and persistence operations."""

    SAVE_VERSION = 1

    def __init__(self, story: dict = STORY, state: GameState | None = None):
        if START_SCENE not in story:
            raise ValueError(f"Story is missing its start scene: {START_SCENE}")
        self.story = story
        self.state = state or GameState()
        self._items = {
            item
            for scene in story.values()
            for choice in scene.get("choices", [])
            for item in choice.get("gain", [])
        }
        if self.state.scene not in story:
            raise ValueError(f"Unknown scene: {self.state.scene}")

    @property
    def current_scene(self) -> dict:
        return self.story[self.state.scene]

    def missing_items(self, choice: dict) -> list[str]:
        return [item for item in choice.get("requires", []) if item not in self.state.inventory]

    def choose(self, number: int) -> bool:
        """Apply a one-based choice. Return False when it is unavailable."""
        choices = self.current_scene.get("choices", [])
        if number < 1 or number > len(choices):
            return False
        choice = choices[number - 1]
        if self.missing_items(choice):
            return False
        for item in choice.get("gain", []):
            if item not in self.state.inventory:
                self.state.inventory.append(item)
        self.state.scene = choice["target"]
        return True

    def save(self, path: str | Path = DEFAULT_SAVE_FILE) -> None:
        data = {
            "version": self.SAVE_VERSION,
            "scene": self.state.scene,
            "inventory": self.state.inventory,
        }
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def load(self, path: str | Path = DEFAULT_SAVE_FILE) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != self.SAVE_VERSION:
            raise ValueError("Unsupported or invalid save file.")
        scene = data.get("scene")
        inventory = data.get("inventory")
        if not isinstance(scene, str) or scene not in self.story:
            raise ValueError("Save file refers to an unknown scene.")
        if (
            not isinstance(inventory, list)
            or any(not isinstance(item, str) or item not in self._items for item in inventory)
            or len(inventory) != len(set(inventory))
        ):
            raise ValueError("Save file contains an invalid inventory.")
        self.state = GameState(scene=scene, inventory=inventory)


class Colors:
    """ANSI styling that can be disabled for terminals and redirected output."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text


HELP_TEXT = """Choose an option by entering its number. At any prompt, you can also use:
  save [file]      Save your progress (default: adventure-save.json)
  load [file]      Restore progress from a save file
  inventory        Show the items you are carrying
  help             Show these commands
  quit             Leave the adventure"""


def _show_scene(game: Adventure, output: TextIO, colors: Colors) -> None:
    scene = game.current_scene
    print(f"\n{colors.paint(scene['title'], '1;36')}\n", file=output)
    print(scene["text"], file=output)
    for index, choice in enumerate(scene.get("choices", []), start=1):
        missing = game.missing_items(choice)
        requirement = (
            colors.paint(f" [requires: {', '.join(missing)}]", "33") if missing else ""
        )
        print(f"  {index}. {choice['text']}{requirement}", file=output)
    if scene.get("ending"):
        print(
            colors.paint(f"\n[{scene['ending'].upper()} ENDING]", "1;32"),
            file=output,
        )


def run_game(
    game: Adventure,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    colors: Colors | None = None,
    default_save: Path = DEFAULT_SAVE_FILE,
) -> None:
    colors = colors or Colors(False)
    while True:
        _show_scene(game, output_stream, colors)
        if game.current_scene.get("ending"):
            print("\nThe story is complete. Start again by running python adventure.py.", file=output_stream)
            return
        try:
            raw = input_stream.readline()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.", file=output_stream)
            return
        if not raw:
            print("\nGoodbye.", file=output_stream)
            return
        command_line = raw.strip()
        if not command_line:
            continue
        try:
            parts = shlex.split(command_line)
        except ValueError as error:
            print(f"Could not read command: {error}", file=output_stream)
            continue
        command, *arguments = parts
        command = command.lower()
        if command == "help" and not arguments:
            print(HELP_TEXT, file=output_stream)
        elif command == "inventory" and not arguments:
            items = game.state.inventory
            print("Inventory: " + (", ".join(items) if items else "(empty)"), file=output_stream)
        elif command in {"save", "load"} and len(arguments) <= 1:
            path = Path(arguments[0]) if arguments else default_save
            try:
                if command == "save":
                    game.save(path)
                    print(f"Game saved to {path}.", file=output_stream)
                else:
                    game.load(path)
                    print(f"Game loaded from {path}.", file=output_stream)
            except (OSError, json.JSONDecodeError, ValueError) as error:
                print(f"Could not {command} game: {error}", file=output_stream)
        elif command == "quit" and not arguments:
            print("Goodbye.", file=output_stream)
            return
        elif command.isdecimal() and not arguments:
            if not game.choose(int(command)):
                print("That choice is unavailable. Check its requirements or choose another option.", file=output_stream)
        else:
            print("Unknown command or invalid arguments. Type 'help' for instructions.", file=output_stream)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play The Last Light, a coastal choose-your-own-adventure.")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument(
        "--save-file",
        type=Path,
        default=DEFAULT_SAVE_FILE,
        help="default path used by the in-game save and load commands",
    )
    args = parser.parse_args()
    color_enabled = (
        not args.no_color
        and sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
    )
    run_game(Adventure(), colors=Colors(color_enabled), default_save=args.save_file)


if __name__ == "__main__":
    main()
