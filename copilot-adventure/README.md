# The Last Light

A Python 3 choose-your-own-adventure about a fogbound coast, a missing
lighthouse keeper, and the choices that can bring the harbor home.

## Play

From this directory, start the game with:

```sh
python adventure.py
```

Choose a numbered option at each scene. Some options require an item; their
requirements are shown beside them, and unavailable choices cannot be taken.
Items are collected through story choices and shown with `inventory`.

At any prompt, use `help` for the command list:

- `save [file]` saves the current scene and inventory as JSON.
- `load [file]` restores a saved game.
- `inventory` lists carried items.
- `help` displays commands.
- `quit` exits.

Without a filename, save and load use `adventure-save.json` in the current
directory. A different default save path can be set at launch:

```sh
python adventure.py --save-file my-progress.json
```

Colored headings are enabled automatically in terminal output. Use
`python adventure.py --no-color` or set `NO_COLOR` to disable them.

## Run tests

Run the standard-library unit tests from this directory:

```sh
python -m unittest discover -s tests -v
```
