# Cheats: a per-game list, from the browser or in game

Branch `claude/cheats-menu`, from `claude/beta-candidate` (a0658e4). 2026-10-10.

Every game can have its own list of cheats. The list opens from the in-game
menu (a **Cheats** row) and from the ROM browser (**RIGHT** on a game, before
launching it). Each cheat is switched on and off on its own, and the choice is
remembered per game. Cheats are off in every link or wireless session.

| Where | What |
|---|---|
| `cheats.c`, `cheats.h` | The core half (`GPSP_CHEATS`): the strict code parser, the RAM-only accessors, the one-per-frame apply point, the translated-code flush. |
| `libretro/libretro.c`, `main.c` | The apply point moves from vcount 228 (inside the dynarec) to the top of `retro_run`. |
| `frontend-common/fe_cheats.c/.h` | The model: cheat files (both formats), the entry list, the `.on` state, the link lock, Game Boy codes. Pure C, no SDK, no heap, host-tested. |
| `frontend-common/fe_host.c` | The Game Boy apply point, before `gbcore_run_frame`. |
| `psp/ui_psp.c` | The Cheats page (`SCR_CHEATS`, `screen_cheats`), the menu row, RIGHT in the browser, the file I/O (`sceIo`). |
| `psp/main_psp.c` | Load at boot, the link lock poll. |
| `tools/test_fe_cheats.c` | Host test, in the `cheat_codebreaker_bounds` suite (the runner caps suites at 30). |
| `assets/cheats/README.txt` | The documented example file. |

Build switch: `CHEATS` (default 1 in both makefiles; `CHEATS=0 tools/build.sh
...` removes the feature from core and frontend and is the kill switch).

---

## 1. For the player

1. Make a text file named like the ROM, with `.cht` (or `.txt`) instead of the
   ROM's extension, in `cheats/` next to `EBOOT.PBP`:

   ```
   PSP/GAME/GBADHOC/roms/Pokemon - Sapphire Version (USA, Europe).gba
   PSP/GAME/GBADHOC/cheats/Pokemon - Sapphire Version (USA, Europe).cht
   ```

2. Write a name on one line and its codes on the lines under it:

   ```
   # Pokemon Ruby / Sapphire (USA)
   Infinite money
   82025BC4 423F
   82025BC6 000F

   Money: exactly 5000
   02025BC4:00001388
   ```

3. In the game list press **RIGHT** on the game, or in game open the menu and
   pick **Cheats**. **X** switches the highlighted cheat on or off, **SQUARE**
   switches all of them off (it asks first), **L/R** page, **O** goes back.

A game with no file shows where the file goes, with that game's own file name
on screen. `assets/cheats/README.txt` is the same explanation as a file.

## 2. The files

| File | Who writes it | What |
|---|---|---|
| `cheats/<rom name minus extension>.cht` | the player | The list. Only ever **read**. `.txt` is tried second. |
| `cheats/<same name>.on` | the menu | Which cheats are on: one `HHHHHHHH name` line each. Rewritten on every change (a few hundred bytes, like `favourites.txt`). |

The name is the ROM's file name, as for box art, so the folder layout under
`roms/` does not matter.

**The plain list.** A line that reads entirely as codes is a code line; any
other line is the name of the next cheat. Blank lines and lines starting `#`
or `//` are ignored (also between two code lines). `[Name]` or `"Name"` gives
a cheat a name that would itself read as a code. Codes before any name become
"Unnamed cheat"; a name with no codes under it (a heading) is dropped. CRLF,
a UTF-8 byte order mark and stray NUL bytes are accepted. Names are shown in
printable ASCII (anything else becomes one `?`), because the UI font's high
bytes are button glyphs.

**libretro `.cht`.** `cheatN_desc` / `cheatN_code` keys are read as they are,
in file-number order; `+` joins the lines of a code. `cheats = N` is not
trusted and RetroArch's own keys are ignored. **`cheatN_enable` is not read**:
a downloaded file does not get to switch a cheat on.

**The `.on` file** identifies a cheat by a 32-bit hash of its name and its
code's digits (case and spacing ignored), so re-ordering or re-wrapping the
list keeps the choice and editing a code drops it. Two entries with the same
name and the same code are the same cheat. The name after the hash is for
people; delete the file to switch everything off.

## 3. Which codes

### Game Boy Advance

| Shape | Example | Status |
|---|---|---|
| CodeBreaker, 8 + 4 digits (or the 12 run together) | `82025BC4 423F` | **Supported.** Types below. |
| Raw write `ADDRESS:VALUE`, value 2 / 4 / 8 digits | `02025BC4:000F423F` | **Supported.** Compiled to CodeBreaker 8-bit / 16-bit writes. |
| GameShark / Action Replay v1-v3, 8 + 8 digits | `D8BAE4D9 4864DCE5` | **Not supported**, listed greyed with the reason. They are encrypted, most need a master-code hook and many are ROM patches. |
| Encrypted CodeBreaker (a type 9 seed line) | `9E6AC862 823C` | **Not supported**, greyed. |
| Anything that touches ROM, I/O, VRAM, palette, OAM or save memory | `88000000 1234` | **Refused**, greyed ("not a RAM code"). |

CodeBreaker types, all through the RAM-only accessors of section 5:

| Type | Meaning | |
|---|---|---|
| 0, 1 | game id, master/hook | accepted and ignored: nothing is hooked into translated code |
| 2, 6 | 16-bit OR, AND | |
| 3 | 8-bit write | |
| 4 | slide (count, address step, value step) | two lines |
| 5 | super code (byte block) | 1 + n lines |
| 7, A, B, C, F | compare: run or skip the next code | the whole next code is skipped, including a slide's or super code's payload |
| 8 | 16-bit write | |
| D | button test | reads this frame's KEYINPUT |
| E | 16 / 32-bit add | |

A multi-line code is simply consecutive code lines under one name; separators
inside a line may be spaces, `+`, `,` or `;`. One cheat is all CodeBreaker or
all raw writes.

Verified by execution, not assumed: every type in the table and the raw
writes in the host test; type 8 and the raw write end to end in PPSSPP
(section 10). The semantics are upstream gpSP's, which follow the published
CodeBreaker types; they were not compared against a real CodeBreaker.

### Game Boy / Game Boy Color

| Shape | Example | Status |
|---|---|---|
| GameShark, 8 digits `01VVLLHH` | `019947D3` | **Supported**: write `VV` to `HHLL` once per frame, in work RAM (C000-DFFF) or high RAM (FF80-FFFE). |
| GameShark with another first byte (banked `9x`, etc.) | `910147D3` | Not supported, greyed. |
| GameShark into cartridge RAM (A000-BFFF) | `0101A0A0` | **Refused**: on a Game Boy that *is* the save file. |
| Game Genie | `00A-17B-C49` | Not supported: a ROM patch. TGB's own cheat map (a lookup on every emulated write) stays compiled out. |

## 4. The page

The Overlay's language (docs/UI-OVERLAY.md), over the game frame in game and
over the highlighted game's art from the browser, in both themes. Rows are
Settings rows: the cursor band, the name clipped with an ellipsis exactly as
the browser clips titles, the state on the right.

- **What is on, at a glance**: a filled square in the console colour and `ON`
  for a cheat that is on, an outline and `off` for one that is off, no marker
  and the reason for one that cannot be used. The header's second line counts
  them ("3 of 12 on"); the menu row carries the same count.
- **Long lists** scroll ten rows at a time behind the 2 px scrollbar; L/R page.
- **A cheat that cannot be used** says why on the plate when X is pressed.
- **SQUARE** asks "switch all N off?" on the plate; only X confirms.
- **No file**: where to put one, with this game's exact file name.
- **A cut list says so** as the page opens: "Showing 256 of N cheats", or that
  the file is over 32 KB.
- **During a session** every row is grey, X does nothing and the plate reads
  "Cheats are off during link play. They come back when it ends."

In-game menu: `Cheats` sits between Settings and Quit to game list (rows 0-3
keep their positions; `quit_demo_script` takes one more DOWN). Browser: RIGHT
opens the page (LEFT is the save-state shelf); the footer's `L/R page` hint
gave its place to `Right: cheats` because the row was full.

## 5. Safety: a cheat file is hostile input

- **Guest RAM only, by construction.** Every read and write a code can make
  goes through five functions in `cheats.c` (`cheat_ram` and the `cheat_w*` /
  `cheat_r*` accessors). They reach EWRAM and IWRAM and nothing else, and the
  offset is masked to the array's size, so no address can index outside the
  host buffer. The parser refuses fixed addresses outside RAM; a slide or
  super code that walks out at run time has that write dropped (and counted).
  The CPU's `write_memory*` handlers, which can reach I/O, flash, EEPROM and
  the RTC, are never called.
- **Nothing in a file switches a cheat on.** A list always loads all off.
- **Bounded everywhere.** The file is read into a 32 KB static buffer; 256
  entries are listed; 64 cheats can be on at once, sharing a pool of 1024
  code records; 256 Game Boy writes. Every limit that is hit is reported on
  screen for that cheat or that file. Nothing allocates: there is no heap
  after a ROM has loaded.
- **Translated code.** A write that changes bytes the dynarec has translated
  (the RAM code tag is nonzero) triggers one full RAM translation flush after
  all codes have run, between frames, where it is the operation a savestate
  load already performs. A write of the value already there is skipped, so a
  code that re-patches code every frame costs one flush, not one per frame.
- **No hook.** Switching a cheat never changes or flushes translated code:
  `cheat_master_hook` stays unset, so the translator never emits a cheat call.

What it cannot protect against: a valid code that writes nonsense into RAM
can still crash the *game*, and the game can still save what it finds.

## 6. Link and wireless sessions

Cheats do not run while any session is up: an adapter or cable session,
a cable host that is only waiting (the link starts from the live game the
moment the other PSP arrives), a GB/GBC link, the GBA mirror, Mystery Gift.
`cheats_link_poll()` in `main_psp.c` evaluates that once per main-loop
iteration and again immediately before the frame runs, rather than hooking
each of the dozen ways a session starts or ends.

When a session starts, enabled cheats are **suspended, not switched off**: a
toast says "Cheats off for link play", the menu row reads "paused for link
play", the page is read-only, and when the session ends they run again
("Cheats back on"). What a cheat already wrote into the game before the
session stays in the game, as it would in a save file.

## 7. Saves and save states

- A code cannot address save memory (GBA 0x0D/0x0E, GB A000-BFFF), the RTC or
  any I/O register: it can only change what the game itself later decides to
  save.
- Codes run at one point only, the top of an emulated frame. Saving or
  loading a state runs no code and applies no cheat; nothing about cheats is
  stored in a state. A state saved with cheats on holds the RAM as the cheats
  left it, exactly like the in-game save would.
- The `.on` file is the only thing written, and never while a frame runs.

## 8. Rewind

The apply point is deterministic per emulated frame: the patch is a pure
function of the active code list, work RAM and that frame's KEYINPUT (which
`update_input` has just latched from the frame's input). Re-running a frame
from the same state with the same input and the same list reproduces it
exactly, including the RAM flush decision.

What rewind needs: the **list is the one input that is not in the state or
the input log**. A change to it (a toggle in the menu, the link lock) must
either be recorded as an event at its frame number, or simply end the
rewindable history at that frame; `fe_cheats_enabled_count()` and the hashes
in `fe_cheats_get()` identify the list. Re-runs must go through `retro_run`
(or call `cheats_apply_frame()` at its top the same way). Game Boy: the same
contract at `fe_cheats_gb_frame()`.

## 9. Performance

- **No cheat on** (or no file): `retro_run` pays one load and one untaken
  branch (`cheats_active`), the main loop one more compare for the link
  lock, and the old per-frame `process_cheats()` call at vcount 228 is gone.
  State hashes are identical to the build without the feature (section 10).
- **Cheats on**: each code record is a handful of instructions (decode, one
  or two RAM accesses, a compare). Not measured on hardware; a typical list
  is tens of records per frame. The exception is the RAM translation flush
  when a code changes translated bytes: once per change, not per frame.
  Under PPSSPP's own (deterministic) clock the mean `retro_run` over 2311
  frames of a Sapphire battle is 5174.62 us without the feature, 5174.98 us
  with it and nothing on, 5175.37 us with one two-line cheat on. That clock
  is not a PSP's; it says "far below a microsecond a frame", not more.
- **Memory**: 80 KiB (32 KB file buffer, 12 KB state buffer, the entry
  table, and an 8 KB record pool in each of the two core instances). (Halved 2026-10-10: a PSP-1000 in a two-GBA session is short of ROM residency by tens of KB.) Release
  profile, GBA_LINK=1: image 13,416,816 B, heap at boot 10,679,736 B on a
  PSP-1000 and 38,991,288 B on a Go; the same tree's base (a0658e4,
  `builds/beta-out/release-egates`) is 13,285,744 / 10,810,808 / 39,122,360.

## 10. Verification

Host (`tools/test_fe_cheats.c`, ASan + UBSan, `-Werror`): every accepted and
refused code shape with its reason; the accessors at the last word of each
region and through mirrors; the flush trigger at 8/16/32 bits; pool and slot
limits; suspension; both file formats with CRLF, BOM, NUL and high bytes,
headings, comments, duplicate names, 400 entries, a 4 MB file and a
one-line 68 KB file; the `.on` round trip, including a re-ordered and
re-wrapped list; Game Boy codes; the shipped example; and 150,000 rounds of
random and well-formed-random input through every entry point. Eight
hand-made mutants of `cheats.c` (wrong mask, no region check, no alignment
check, no same-value skip, no tag check, no suspend, pool overrun) all fail
it.

PPSSPP end to end (harness build with GBA_LINK=1; stages, logs and
screenshots in `builds/cheats-out/`), Pokemon Sapphire (USA, Rev 2) with the
public CodeBreaker code `82025BC4 423F` / `82025BC6 000F`:

| Run | What | Result |
|---|---|---|
| t1 | in game: menu, Cheats, X on the first cheat, resume | money in RAM 3000 -> 999999; the trainer card shows 999999 |
| t2 | relaunch with the `.on` file t1 wrote | toast "1 cheat on"; 999999 with no menu touched |
| t3 | browser: RIGHT on a game with no file, RIGHT on Sapphire, X, launch; then in game a second cheat on and off again | empty state; 999999 at boot; 5000 with the raw write on; 999999 again with it off |
| t4 | the same `.on`, hosting a wireless room from boot, then disconnect | money stays 3000 while hosting; page and menu say why; 999999 after the disconnect |
| t5 | Pokemon Blue, GameShark `019947D3` `019948D3` `019949D3` | D347-D349 `002175` -> `999999` (memory only; no screenshot of the effect) |
| t6 | light theme: list, scrolled, the all-off question | pictures |

Identity (`shash = 1`, from a save state, 2311 frames, every state hash: CPU
registers, PC, IWRAM, EWRAM, I/O, palette, OAM, VRAM, audio): the build with
`CHEATS=0`, the build with cheats and no file, and the build with a file and
nothing on are identical; the build with one cheat on differs from the first
frame (the negative control). `builds/cheats-out/logs/identity-shash.txt`.
The base here is the same tree built with `CHEATS=0`, not a separate
checkout of a0658e4. Frames before the state load differ between two runs of
the *same* EBOOT (IWRAM hash, PPSSPP, also with `CHEATS=0`), so they are not
compared.

Not verified: anything on hardware; a real two-console session (the lock was
exercised by hosting alone); the GBA mirror and GB link sessions specifically
(same predicate, not run); any CodeBreaker type other than 8 against a real
game.

## 11. Not built: adding a code on the console

Designed, not implemented. A row "Add a code..." at the end of the list opens
a hex pad drawn by our own UI (a 4 x 4 grid of 0-F plus space, newline,
delete; X types, START finishes): the firmware's on-screen keyboard is a
utility module that wants memory we do not have once a game is loaded. Each
line is checked live with `cheat_check()` and the entry cannot be finished
until it is acceptable. The cheat is named "Custom 1", "Custom 2", ... (no
text entry) and **appended** to the game's `.cht`, the only time that file
would be written. Deleting a custom entry would need a rewrite of the file,
which is why it is a second step.
