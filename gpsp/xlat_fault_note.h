/* xlat_fault_note.h -- what the core keeps about failed translations and the
 * resets BADJUMP_SAFE makes of them, for the frontend's log/runtime.log.
 *
 * A core switch of the runtimelog profile only: XLAT_FAULT_NOTE=1 (root
 * Makefile; docs/BUILD-SWITCHES.md).  Without it the core has no such object
 * and the code that fills it is not compiled -- a release's core is the one
 * built without this file.  The frontend reads it through a WEAK reference
 * (main_psp.c, GPSP_RUNTIME_LOG), as it reads badjump_recoveries: NULL when
 * the core was built without the switch.
 *
 * Plain stores on the emulation thread, only in cold paths (cpu_threaded.c:
 * badjump_recover, vram_or_badjump_*, the start of a lazy try); nothing in the
 * pinned hot order changes.  The frontend reads the words between frames on
 * the same thread. */
#ifndef XLAT_FAULT_NOTE_H
#define XLAT_FAULT_NOTE_H

#include <stdint.h>

/* Why badjump_recover was reached. */
enum
{
   XFN_WHY_OTHER      = 0,   /* (not used for a reset of the lookups) */
   XFN_WHY_UNMAPPABLE = 1,   /* no code can be at that pc: the sentinel, on
                                the first try (BIOS_BOUND_FIX: region 0
                                above the BIOS; the unhandled regions) */
   XFN_WHY_EXHAUSTED  = 2,   /* four tries failed (the 4th the lazy one) */
   XFN_WHY_VRAM       = 3    /* a region-6 pc: the VRAM retries failed */
};

typedef struct xlat_fault_note
{
   /* Monotonic counts. */
   uint32_t lazy;             /* lazy 4th tries begun (XLAT_LAST_TRY_LAZY) */
   uint32_t lazy_failed;      /* ...that still ended in a reset (exhausted) */
   uint32_t resets;           /* badjump_recover calls */
   /* The last lazy try, as it began (three tries had failed). */
   uint32_t lazy_pc, lazy_thumb;
   uint32_t lazy_ram_fill, lazy_rom_fill;        /* translation-cache bytes */
   /* Set by vram_or_badjump_* for the reset that follows; cleared by it.
    * arm_thumb: 0 ARM, 1 Thumb, 2 not known. */
   uint32_t arm_why, arm_thumb;
   /* The last reset, as badjump_recover found it (before the reset itself
    * flushed anything). */
   uint32_t reset_pc, reset_why, reset_tries, reset_thumb;
   uint32_t reset_ram_fill, reset_rom_fill, reset_page_loads;
} xlat_fault_note;

#endif
