# releasy.py

Easy way to interactively generate a release commit for a Python module.

## Usage

`releasy.py` is a self-contained [uv](https://docs.astral.sh/uv/) script: its
dependencies are declared inline, so [uv](https://docs.astral.sh/uv/) fetches
them on first run. No install step needed.

Drop it into a directory on your `PATH` (e.g. `~/.local/bin/`) and run it from
anywhere:

```bash
curl -o ~/.local/bin/releasy.py https://raw.githubusercontent.com/slint/releasy.py/master/releasy.py
chmod +x ~/.local/bin/releasy.py
releasy.py
```

The `#!/usr/bin/env -S uv run` shebang hands execution to uv, which resolves the
inline dependencies on first run.

Or run it straight from GitHub without downloading:

```bash
uv run https://raw.githubusercontent.com/slint/releasy.py/master/releasy.py
```
