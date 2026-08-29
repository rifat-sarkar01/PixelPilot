# PixelPilot fix loop — run until both goals are verifiably true

You have direct access to this machine (filesystem, ability to launch GIMP/Krita,
read logs). Use that. Don't propose a fix you haven't actually verified against
real evidence gathered from THIS machine — pattern-matched guesses from
documentation have already failed several times on this exact problem.

Repository: `D:\PixelPilot`
Krita install: `D:\Krita\Krita (x64)\bin\krita.exe`
GIMP install: `D:\GIMP 2\bin\gimp-2.10.exe`
Config: `%APPDATA%\pixelpilot\config.yaml`

## Two goals — keep looping until BOTH are true

**Goal A:** Running `pixelpilot --editor krita` (or `/connect`) successfully
connects to a live Krita bridge on `localhost:10020` within the configured
timeout.

**Goal B:** `pixelpilot --editor gimp`, given a request that causes the code
model to write an error handler (`except Exception as e: ...`), produces a
script that actually compiles and runs inside GIMP's Python 2.7 interpreter —
no `SyntaxError` at execution time.

Do not declare either goal done until you've watched it succeed live, once,
end to end. Don't stop after just editing a file.

---

## Goal A: Krita plugin never appears in Settings > Configure Krita > Python
## Plugin Manager

### What's already been tried (don't repeat these blind)
- Added `X-KDE-Library=pixelpilot_krita` to
  `plugins/krita/pixelpilot_krita/pixelpilot.desktop` — necessary but insufficient.
- Removed `X-Krita-Version=28` (confirmed stale via a KDE bug report; absent
  from working example plugins) — still insufficient.
- `enable_krita_plugin()` in `src/pixelpilot/bridge/launcher.py` writes
  `enable_pixelpilot_krita=true` under `[python]` in `kritarc` — **the exact
  key format was never verified against Krita's actual source, treat this as
  unconfirmed, not fixed.**
- `launch_krita_and_wait()` now refuses to relaunch into an already-running
  Krita process (Krita is single-instance; relaunching just opens a new
  window in the existing process without rescanning plugins).
- User has confirmed: `pixelpilot_krita/` folder and `pixelpilot_krita.desktop`
  ARE physically present, correctly placed, directly inside
  `%APPDATA%\krita\pykrita\`. Krita was fully closed and reopened. Plugin
  **still does not appear in the list at all.**

### Diagnose in this order — each step either finds the real cause or rules
### out a hypothesis. Don't skip to editing files again until you have a
### concrete "because X" from one of these.

1. **Confirm Python scripting exists in this Krita build at all.** Open
   Krita, check Settings > Configure Krita > Python Plugin Manager for
   Krita's OWN bundled plugins (e.g. "Ten Scripts", "Comics Project
   Management Tools", "Krita Script Starter Feature"). If NONE of Krita's own
   default plugins are listed either, this was never a PixelPilot-specific
   bug — this Krita build/install doesn't have Python scripting enabled or
   available, and the fix is entirely different (reinstall Krita with
   scripting support, or check for a missing Python DLL/runtime dependency).
   **Do this check first — it changes everything downstream.**

2. **Confirm which resource folder this specific Krita.exe actually reads
   from.** Non-standard install locations (this one is on `D:\`, not
   `Program Files`) can end up in portable mode, which stores its resource
   folder relative to the install directory instead of `%APPDATA%`. In
   Krita: Settings > Manage Resources > Open Resource Folder. Compare that
   path, byte for byte, to `%APPDATA%\krita`. If they don't match, that's the
   entire bug — PixelPilot has been deploying to a folder this Krita install
   never reads, and every fix so far was irrelevant. Fix: update
   `krita_plugin_dir()` in `launcher.py` to resolve the real path (Krita can
   report it via `--` flags or by checking for a portable-mode marker file
   next to the exe) instead of hardcoding `%APPDATA%\krita\pykrita`.

3. **Launch Krita from a terminal, not a double-click, and capture output.**
   Run `"D:\Krita\Krita (x64)\bin\krita.exe"` from `cmd.exe` or PowerShell
   directly (don't detach it) and watch stdout/stderr during startup. Krita's
   plugin loader typically prints a line per plugin it finds, skips, or fails
   to import. This will show the literal reason (bad desktop file field,
   import error in `plugin.py` itself, version mismatch, wrong directory) —
   read whatever it says and act on that specific message, don't
   re-guess.

4. **Byte-check the deployed `.desktop` file, not the source copy.** Open
   `%APPDATA%\krita\pykrita\pixelpilot_krita.desktop` in a hex-aware editor
   or `Format-Hex` in PowerShell. Confirm: UTF-8 encoding, no BOM, no CRLF
   corruption, actually matches the current repo source (rule out a stale
   deploy — check the file's last-modified timestamp against when you last
   ran `/connect`).

5. **Check `plugin.py` itself imports cleanly under Krita's bundled Python.**
   A plugin with a valid `.desktop` file but a Python import error in its
   `__init__.py`/`plugin.py` will fail SILENTLY in some Krita versions rather
   than showing an error icon. Manually run
   `"D:\Krita\Krita (x64)\bin\python" -c "import pixelpilot_krita"` (or
   whatever Python Krita bundles — check `D:\Krita\Krita (x64)\python\`) from
   inside the pykrita directory to check for import-time errors independent
   of Krita's own loader.

6. **Only after 1-5 give you a concrete cause**, fix it, redeploy
   (`deploy_krita_plugin()` or just `/connect`), fully quit and relaunch
   Krita, and check the Plugin Manager list again. If it now appears but is
   unchecked, that confirms step's fix worked for *discovery* but
   `enable_krita_plugin()`'s kritarc key is still wrong — check the box
   manually once, note the exact key it produces in `kritarc` afterward
   (`type kritarc | findstr pixelpilot` from cmd), and update
   `enable_krita_plugin()` in `launcher.py` to write that exact confirmed key
   instead of the guessed one.

---

## Goal B: GIMP script crashes with `SyntaxError: invalid syntax` on an
## f-string

### Root cause (already confirmed, don't re-diagnose this part)
GIMP 2.10's Python-Fu console runs **Python 2.7**, not Python 3. The code
model generated:
```python
except Exception as e:
    pdb.gimp_message(f"Error: {str(e)}")
```
`f"..."` is Python 3.6+ only syntax. Python 2.7's parser doesn't recognize it
at all — `compile(code, ..., "exec")` fails before a single line executes.
This will happen again on ANY generated script that uses an f-string,
`match` statements, walrus `:=`, or other Python-3-only syntax, not just this
one — the fix needs to prevent the whole class, not just this instance.

### Fix (two layers — do both, don't stop at the first one)

1. **Prompt layer** — add an explicit rule to
   `src/pixelpilot/prompts/gimp.py` (`GOTCHAS`, follow the existing numbered
   rule format) stating: GIMP's Python-Fu is Python 2.7, so f-strings and
   other Python 3-only syntax are forbidden. Show the correct Python
   2/3-compatible alternative for string formatting:
   ```python
   # WRONG (Python 3 only, hard SyntaxError under GIMP's Python 2.7):
   pdb.gimp_message(f"Error: {str(e)}")
   # RIGHT:
   pdb.gimp_message("Error: %s" % str(e))
   ```

2. **Validator layer** — this must be a hard, blocking ERROR in
   `src/pixelpilot/codegen/validator.py`, not just a prompt suggestion,
   because an f-string is a **guaranteed** crash, not a maybe. Detect it
   before execution: either regex-match for the `f"`/`f'`/`F"`/`F'` string
   prefix pattern, or — better and more general, since it'll also catch
   *any* other Python-3-only construct — actually try `compile(code, ...,
   "exec")` against Python 2.7 grammar rules specifically (not just "is this
   valid Python 3 syntax", which is what a plain `ast.parse` in this
   Python 3-based tool would check and pass incorrectly). If a true Python
   2.7 compile check isn't practical, at minimum regex-detect the f-string
   prefix pattern and add it as a `report.errors` entry (blocks execution,
   distinct from `report.warnings`).

3. While in `validator.py`, also add `gimp_message` to
   `src/pixelpilot/knowledge/gimp_pdb.json` — it's a real, standard GIMP
   procedure (used for exactly this error-reporting pattern) but isn't in
   the curated list yet, so it's currently flagged as a false-positive
   "possible hallucination" warning every time it's used correctly. Same
   fix pattern as the earlier `gimp_image_select_polygon` addition — match
   that entry's schema.

### Verify, don't assume
After the fix, deliberately provoke a `try/except` that reports an error
(e.g. force a script to reference an undefined variable so the except block
fires) and confirm: (a) the validator now either blocks any f-string with a
clear error BEFORE execution, or the code model no longer produces one at
all, and (b) a script with a normal `except Exception as e: pdb.gimp_message
("..." % str(e))` runs cleanly inside real GIMP.

---

## Stop condition

Both goals demonstrated working live, in this session, against the real
GIMP/Krita installs on this machine — not "should work now" from reading the
code. Run the full test suite (`pytest -q` from the repo root) before
declaring done, and add regression tests for whatever the actual root causes
turn out to be, following the existing test style in `tests/unit/`.
