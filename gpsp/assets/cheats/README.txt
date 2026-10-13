# GBAdhoc cheat files -- how to write one, and an example.
#
# WHERE.  One text file per game, in this folder (cheats/, next to EBOOT.PBP),
# named exactly like the ROM with .cht instead of .gba / .gb / .gbc:
#
#     roms/Pokemon - Sapphire Version (USA, Europe).gba
#     cheats/Pokemon - Sapphire Version (USA, Europe).cht
#
# (.txt works too, for editors that insist on it.)  Open the list with RIGHT
# on a game in the game list, or with Cheats in the in-game menu.  Every
# cheat starts OFF; the ones you switch on are remembered per game in a
# little <name>.on file that the menu writes beside your list.  Your own file
# is only ever read.
#
# FORMAT.  A name on one line, its codes on the lines under it.  Blank lines
# and lines starting with # or // are ignored.  Put a name in [brackets] if
# it could be mistaken for a code.  libretro / RetroArch .cht files
# (cheat0_desc = ..., cheat0_code = ...) are read as they are.
#
# GAME BOY ADVANCE: CodeBreaker codes, 8 + 4 digits ...
#
#     Infinite money
#     82025BC4 423F
#     82025BC6 000F
#
# ... or a plain write, ADDRESS:VALUE with a 2, 4 or 8 digit value:
#
#     Money: exactly 5000
#     02025BC4:00001388
#
# Only codes that write the game's RAM (addresses 02...... and 03......) can
# be used.  GameShark / Action Replay codes (8 + 8 digits), encrypted
# CodeBreaker codes and ROM patches are listed but cannot be switched on.
#
# GAME BOY / GAME BOY COLOR: GameShark codes, 8 digits starting with 01:
#
#     Infinite money
#     019947D3
#     019948D3
#     019949D3
#
# Game Genie codes (ABC-DEF-GHI) patch the ROM and cannot be used.
#
# CHEATS ARE OFF DURING LINK PLAY (trades, battles, Mystery Gift) and come
# back by themselves afterwards.  A cheat changes the game's memory, and the
# game will happily save what it finds there: keep a backup of a save you
# care about before experimenting.
#
# This file is not a cheat list for any game (no game is called README), but
# it is a valid one -- the two cheats below are the Pokemon Ruby / Sapphire
# (USA) examples from above, ready to be copied into a file of your own.

Infinite money
82025BC4 423F
82025BC6 000F

Money: exactly 5000
02025BC4:00001388
