/* gameplaySP
 *
 * Copyright (C) 2006 Exophase <exophase@gmail.com>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation; either version 2 of
 * the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#ifndef __GPSP_CHEATS_H__
#define __GPSP_CHEATS_H__

#ifdef GPSP_CHEATS
/* Cheats that can be ON at once, and the records they share (8 bytes each:
 * one CodeBreaker line is one record, a raw 32-bit write is two).  A cheat
 * has no length limit of its own; the pool is the limit, and running out is
 * reported per cheat (CheatErrorTooBig / CheatErrorTooMany), never silent. */
#define MAX_CHEATS          64
#define CHEAT_POOL_RECORDS  1024
#else
#define MAX_CHEATS       20
#endif
#define MAX_CHEAT_CODES  64

typedef enum {
   CheatNoError = 0,
   CheatErrorTooMany,
   CheatErrorTooBig,
   CheatErrorEncrypted,
   CheatErrorNotSupported
#ifdef GPSP_CHEATS
   /* GPSP_CHEATS only (docs/CHEATS.md section 3): the strict parser names
    * WHY a code was refused, so the menu can say it. */
   ,CheatErrorSyntax,        /* not CodeBreaker, not raw, not GS/AR either */
   CheatErrorGameShark,      /* 8+8 digits: GameShark v1/v2 or AR v3      */
   CheatErrorRegion,         /* writes or reads outside EWRAM/IWRAM       */
   CheatErrorAlign,          /* a 16/32-bit access at an odd address      */
   CheatErrorMixed           /* raw and CodeBreaker lines in one cheat    */
#endif
} cheat_error;

void process_cheats(void);
cheat_error cheat_parse(unsigned index, const char *code);
void cheat_clear(void);
void cheat_disable(unsigned index);

extern u32 cheat_master_hook;

#ifdef GPSP_CHEATS
/* GBAdhoc cheats (docs/CHEATS.md).  Compiled in with CHEATS=1 on the ROOT
 * make (the PSP platform's default); CHEATS=0 removes this whole block and
 * every change it implies in cheats.c / main.c / libretro.c, and the core is
 * upstream's again.
 *
 * The contract, in one place:
 *  - Codes run ONCE PER EMULATED FRAME at one fixed point: the top of
 *    retro_run, after input is latched and before the CPU runs.  That is the
 *    same guest instant upstream used (vcount 228, the end of the previous
 *    frame), but OUTSIDE the dynarec, so a translation flush there is the
 *    operation a savestate load performs: the next entry looks the PC up
 *    afresh.  The patch is a pure function of (active codes, work RAM, this
 *    frame's KEYINPUT): the same frame always gets the same patch.
 *  - Codes may read and write EWRAM and IWRAM only.  Anything else is refused
 *    by the parser (ROM patches, I/O, VRAM, OAM, palette, save memory) and
 *    cannot be reached at run time either (cheat_ram).
 *  - A write that does not change the byte(s) is skipped.  A write that
 *    changes bytes the dynarec has translated (the RAM code tag is nonzero)
 *    schedules one full RAM translation flush, done after all codes have run.
 *  - Master/hook codes (CodeBreaker type 1) are accepted and IGNORED: the
 *    translator never emits a cheat call (cheat_master_hook stays ~0), so
 *    switching a cheat on or off never changes or flushes translated code.
 *  - With no active cheat, or while suspended (a link session),
 *    cheats_apply_frame() is not called at all: the frame path pays one load
 *    and one branch.  Nothing here is in a savestate. */
extern u32 cheats_active;          /* active slots; 0 = the frame hook is off */
extern u32 cheats_suspended;       /* 1 = codes do not run (link sessions)    */
extern u32 cheat_ram_flushes;      /* RAM translation flushes cheats caused   */
extern u32 cheat_writes_changed;   /* writes that changed RAM                 */
extern u32 cheat_writes_dropped;   /* runtime out-of-region writes (slide/super) */
void cheats_apply_frame(void);
void cheats_set_suspended(int on);
cheat_error cheat_check(const char *code);
const char *cheat_error_name(cheat_error e);
#endif

#endif

