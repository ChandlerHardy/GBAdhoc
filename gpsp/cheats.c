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

#include "common.h"
#ifdef GPSP_CHEATS
#include "cheat_format.h"
#endif

typedef struct
{
  u32 address;
  u32 value;
} cheat_rec;

#ifdef REWIND
/* Rewind (docs/REWIND.md): the cheat list is not in a snapshot, and a frame
 * re-run under a different list is a different frame.  Every change to what
 * runs bumps this; the frontend ends the history there. */
u32 gba_rewind_cheat_gen;
#define RW_CHEATS_CHANGED() (gba_rewind_cheat_gen++)
#else
#define RW_CHEATS_CHANGED() ((void)0)
#endif

typedef struct
{
  bool cheat_active;
#ifdef GPSP_CHEATS
  /* Records live in one shared pool (cheat_pool): a cheat is as long as it
   * needs to be, and sixty short ones cost what sixty short ones cost. */
  cheat_rec *codes;
  bool gs_format;              /* private normalized GS/AR record stream */
  unsigned work;            /* worst-case reads/writes per frame */
#else
  cheat_rec codes[MAX_CHEAT_CODES];
#endif
  unsigned cheat_count;
} cheat_type;

cheat_type cheats[MAX_CHEATS];
u32 max_cheat = 0;
u32 cheat_master_hook = 0xffffffff;

#ifndef GPSP_CHEATS
/* Upstream: codes go through the CPU's own memory handlers. */
#define CHEAT_W8(a, v)   write_memory8((a), (v))
#define CHEAT_W16(a, v)  write_memory16((a), (v))
#define CHEAT_W32(a, v)  write_memory32((a), (v))
#define CHEAT_R16(a)     read_memory16(a)
#define CHEAT_R32(a)     read_memory32(a)
#else
/* ---- GPSP_CHEATS: the RAM-only accessors (docs/CHEATS.md section 5) --------
 *
 * A cheat file is hostile input.  Whatever it says, a code can only ever
 * touch the two work-RAM arrays, through these five functions:
 *
 *   - EWRAM (0x02xxxxxx) and IWRAM (0x03xxxxxx) only.  The parser refuses a
 *     code whose fixed address lies anywhere else (ROM, I/O, VRAM, palette,
 *     OAM and -- above all -- the cartridge save at 0x0D/0x0E); a slide or
 *     super code that WALKS out of the region at run time has that write
 *     dropped and counted.  The offset is masked to the array's size, so no
 *     address can index outside the host buffer.
 *   - 16/32-bit accesses are forced to their alignment (as the GBA bus does).
 *   - A write that does not change the bytes is not made: same data, same
 *     translation.  So a code that rewrites translated code every frame costs
 *     ONE flush, not one per frame.
 *   - A changed byte under a nonzero code tag sets cheat_smc_pending; the
 *     flush itself happens once, after every code has run
 *     (cheats_apply_frame).  The guest's own stores are checked by the store
 *     stubs and DMA by dma_write_iwram/_ewram; a cheat is a third writer and
 *     needs the same check, or translated code it patched keeps running in
 *     its old form.
 * Reads are plain RAM reads: no I/O side effects, no ROM page faults. */
static cheat_rec cheat_pool[CHEAT_POOL_RECORDS];
static unsigned cheat_pool_used;
static unsigned cheat_work_used;
u32 cheats_active;
u32 cheats_suspended;
u32 cheat_ram_flushes;
u32 cheat_writes_changed;
u32 cheat_writes_dropped;
static u32 cheat_smc_pending;

static u8 *cheat_ram(u32 address, u8 **tag)
{
  switch ((address >> 24) & 0xF)
  {
    case 0x2:
      /* A cheat is a writer of EWRAM like any other (gba_memory.h, "THE
       * RULE").  Marked here, where the pointer is made, so no write below
       * can forget; a read marks too, which costs a compare and no more. */
      RW_MARK_EWRAM(address & 0x3FFFF, 4);
      *tag = ewram + 0x40000 + (address & 0x3FFFF);
      return ewram + (address & 0x3FFFF);
    case 0x3:
      *tag = iwram + (address & 0x7FFF);
      return iwram + 0x8000 + (address & 0x7FFF);
    default:
      return NULL;
  }
}

static void cheat_w8(u32 address, u8 value)
{
  u8 *tag, *p = cheat_ram(address, &tag);
  if (!p) { cheat_writes_dropped++; return; }
  if (*p == value)
    return;
  *p = value;
  cheat_writes_changed++;
  if (*tag)
    cheat_smc_pending = 1;
}

static void cheat_w16(u32 address, u16 value)
{
  u8 *tag, *p = cheat_ram(address & ~1U, &tag);
  if (!p) { cheat_writes_dropped++; return; }
  if (readaddress16(p, 0) == value)
    return;
  address16(p, 0) = eswap16(value);
  cheat_writes_changed++;
  if (address16(tag, 0))
    cheat_smc_pending = 1;
}

static void cheat_w32(u32 address, u32 value)
{
  u8 *tag, *p = cheat_ram(address & ~3U, &tag);
  if (!p) { cheat_writes_dropped++; return; }
  if (readaddress32(p, 0) == value)
    return;
  address32(p, 0) = eswap32(value);
  cheat_writes_changed++;
  if (address32(tag, 0))
    cheat_smc_pending = 1;
}

static u32 cheat_r16(u32 address)
{
  u8 *tag, *p = cheat_ram(address & ~1U, &tag);
  return p ? readaddress16(p, 0) : 0;
}

static u32 cheat_r32(u32 address)
{
  u8 *tag, *p = cheat_ram(address & ~3U, &tag);
  return p ? readaddress32(p, 0) : 0;
}

#define CHEAT_W8(a, v)   cheat_w8((a), (v))
#define CHEAT_W16(a, v)  cheat_w16((a), (v))
#define CHEAT_W32(a, v)  cheat_w32((a), (v))
#define CHEAT_R16(a)     cheat_r16(a)
#define CHEAT_R32(a)     cheat_r32(a)

static void cheats_recount(void)
{
  unsigned i;
  cheats_active = 0;
  for (i = 0; i < MAX_CHEATS; i++)
    if (cheats[i].cheat_active)
      cheats_active++;
}
#endif

/* Records one CodeBreaker code occupies.  Slide (4) and super (5) codes carry
 * payload records -- raw data whose top nibble means nothing -- so every walk
 * over a cheat must step over them, never treat them as opcodes of their own.
 * cheat_parse guarantees the payload is complete. */
static unsigned codebreaker_code_len(const cheat_type *cheat, unsigned i)
{
  u32 opcode = cheat->codes[i].address >> 28;
  if (opcode == 4)
    return 2;
  if (opcode == 5)
    return 1 + ((unsigned)(u16)cheat->codes[i].value * 2 + 5) / 6;
  return 1;
}

/* Records to skip when a conditional code at `i` skips "the next code": the
 * whole next code (as mGBA does), not just its first record -- skipping only
 * the header of a slide/super code ran its payload as independent writes. */
static unsigned codebreaker_next_len(const cheat_type *cheat, unsigned i)
{
  return i + 1 < cheat->cheat_count ? codebreaker_code_len(cheat, i + 1) : 1;
}

#ifndef GPSP_CHEATS
static bool has_encrypted_codebreaker(cheat_type *cheat)
{
  unsigned i;
  for(i = 0; i < cheat->cheat_count; i += codebreaker_code_len(cheat, i))
  {
     u32 code    = cheat->codes[i].address;
     u32 opcode  = code >> 28;
     if (opcode == 9)
        return true;
  }
  return false;
}

static void update_hook_codebreaker(cheat_type *cheat)
{
  unsigned i;
  for(i = 0; i < cheat->cheat_count; i += codebreaker_code_len(cheat, i))
  {
     u32 code    = cheat->codes[i].address;
     u32 address = code & 0xfffffff;
     u32 opcode  = code >> 28;

     if (opcode == 1)
     {
        u32 pcaddr = 0x08000000 | (address & 0x1ffffff);
        #ifdef HAVE_DYNAREC
        if (cheat_master_hook != pcaddr)
           flush_dynarec_caches();   /* Flush caches to install hook */
        #endif
        cheat_master_hook = pcaddr;
        return;   /* Only support for one hook */
     }
  }
}

#endif

static void process_cheat_codebreaker(cheat_type *cheat, u16 pad)
{
  unsigned i, j;
  for(i = 0; i < cheat->cheat_count; i++)
  {
    u32 code    = cheat->codes[i].address;
    u16 value   = cheat->codes[i].value;
    u32 address = code & 0xfffffff;
    u32 opcode  = code >> 28;

    switch (opcode) {
    case 0:   /* Game CRC, ignored for now */
      break;
    case 1:   /* Master code function */
      break;
    case 2:   /* 16 bit OR */
      CHEAT_W16(address, CHEAT_R16(address) | value);
      break;
    case 3:   /* 8 bit write */
      CHEAT_W8(address, value);
      break;
    case 4:   /* Slide code, writes a buffer with addr/value strides */
      if (i + 1 < cheat->cheat_count)
      {
        u16 count = cheat->codes[++i].address;
        u16 vincr = cheat->codes[  i].address >> 16;
        u16 aincr = cheat->codes[  i].value;
        for (j = 0; j < count; j++)
        {
          CHEAT_W16(address, value);
          address += aincr;
          value += vincr;
        }
      }
      break;
    case 5:   /* Super code: copies bytes to a buffer addr */
      /* Each following CodeBreaker record provides six payload bytes.  The
       * off==0 case advances i before reading, so checking only i<count in
       * the loop condition lets a truncated payload increment past the end. */
      if (((unsigned)value * 2 + 5) / 6 > cheat->cheat_count - i - 1)
      {
        i = cheat->cheat_count;
        break;
      }
      for (j = 0; j < (unsigned)value * 2; j++)
      {
        u8 bvalue, off = j % 6;
        switch (off) {
        case 0:
          bvalue = cheat->codes[++i].address >> 24;
          break;
        case 1 ... 3:
          bvalue = cheat->codes[i].address >> (24 - off*8);
          break;
        case 4 ... 5:
          bvalue = cheat->codes[i].value >> (40 - off*8);
          break;
        };
        CHEAT_W8(address, bvalue);
        address++;
      }
      break;
    case 6:   /* 16 bit AND */
      CHEAT_W16(address, CHEAT_R16(address) & value);
      break;
    case 7:   /* Compare mem value and execute next cheat */
      if (CHEAT_R16(address) != value)
        i += codebreaker_next_len(cheat, i);
      break;
    case 8:   /* 16 bit write */
      CHEAT_W16(address, value);
      break;
    case 10:   /* Compare mem value and skip next cheat */
      if (CHEAT_R16(address) == value)
        i += codebreaker_next_len(cheat, i);
      break;
    case 11:   /* Compare mem value and skip next cheat */
      if (CHEAT_R16(address) <= value)
        i += codebreaker_next_len(cheat, i);
      break;
    case 12:   /* Compare mem value and skip next cheat */
      if (CHEAT_R16(address) >= value)
        i += codebreaker_next_len(cheat, i);
      break;
    case 13:   /* Check button state and execute next cheat */
      switch ((address >> 4) & 0xf) {
      case 0:
        if (((~pad) & 0x3ff) == value)
          i += codebreaker_next_len(cheat, i);
        break;
      case 1:
        if ((pad & value) == value)
          i += codebreaker_next_len(cheat, i);
        break;
      case 2:
        if ((pad & value) == 0)
          i += codebreaker_next_len(cheat, i);
        break;
      };
      break;
    case 14:   /* Increase 16/32 bit memory value */
      if (address & 1)
      {
        u32 value32 = (u32)((s16)value);  /* Sign extend to 32 bit */
        address &= ~1U;
        CHEAT_W32(address, CHEAT_R32(address) + value32);
      }
      else
      {
        CHEAT_W16(address, CHEAT_R16(address) + value);
      }
      break;
    case 15:   /* Immediate and check and skip */
      if ((CHEAT_R16(address) & value) == 0)
        i += codebreaker_next_len(cheat, i);
      break;
    }
  }
}

#ifndef GPSP_CHEATS
void process_cheats(void)
{
   u32 i;

   for(i = 0; i <= max_cheat; i++)
   {
      if(!cheats[i].cheat_active)
         continue;

      process_cheat_codebreaker(&cheats[i], 0x3ff ^ read_ioreg(REG_P1));
   }
}
#else
/* Upstream's two entry points are both INSIDE emulation: update_gba at vcount
 * 228 (compiled out in main.c under GPSP_CHEATS) and the translator's
 * master-hook call (mips_cheat_hook), emitted only when cheat_master_hook
 * names a PC -- which GPSP_CHEATS never lets happen.  Neither may flush the
 * translation cache it is running from, so under GPSP_CHEATS this symbol
 * stays only because the stubs reference it, and does nothing. */
void process_cheats(void)
{
}

static void process_cheat_gs(const cheat_type *ch);

/* The one place codes run (libretro.c retro_run, before the CPU).  A pure
 * function of three things: the active codes, guest work RAM, and this
 * frame's KEYINPUT -- so the same emulated frame always gets the same patch
 * (docs/CHEATS.md section 8, rewind). */
void cheats_apply_frame(void)
{
   u32 i;
   u16 pad = 0x3ff ^ read_ioreg(REG_P1);

   if (cheats_suspended)
      return;
   cheat_smc_pending = 0;
   for (i = 0; i <= max_cheat && i < MAX_CHEATS; i++)
   {
      if (!cheats[i].cheat_active)
         continue;
      if (cheats[i].gs_format)
         process_cheat_gs(&cheats[i]);
      else
         process_cheat_codebreaker(&cheats[i], pad);
   }
#ifdef HAVE_DYNAREC
   /* A code changed bytes the dynarec has translated.  The same full RAM
    * flush as a DMA onto code (flush_translation_cache_ram_dma), but run
    * between frames: nothing is executing from the RAM cache, and the next
    * entry (execute_arm_translate) dispatches from reg[REG_PC] through
    * block_lookup_address_*, exactly as after a savestate load.  ROM
    * translations are untouched -- codes cannot reach ROM. */
   if (cheat_smc_pending && dynarec_enable)
   {
      flush_translation_cache_ram();
      cheat_ram_flushes++;
   }
#endif
   cheat_smc_pending = 0;
}

void cheats_set_suspended(int on)
{
   if (cheats_suspended != (u32)(on ? 1 : 0))
      RW_CHEATS_CHANGED();
   cheats_suspended = on ? 1 : 0;
}
#endif

void cheat_clear()
{
   int i;
   RW_CHEATS_CHANGED();
   for (i = 0; i < MAX_CHEATS; i++)
   {
      cheats[i].cheat_count = 0;
      cheats[i].cheat_active = false;
   }
   /* Reset the scan high-water-mark too: otherwise process_cheats keeps
    * iterating over inactive slots from the previous game's cheat set,
    * wasting cycles on every vblank. */
   max_cheat = 0;
   cheat_master_hook = 0xffffffff;
#ifdef GPSP_CHEATS
   cheats_active = 0;
   cheat_pool_used = 0;
   cheat_work_used = 0;
#endif
}

/* Soft-disable: keep the parsed code data in place so a future
 * cheat_parse() with the same index would not be strictly required
 * to re-enable, but flip cheat_active=false so process_cheats()
 * skips it.  Out-of-range indices are silently ignored.
 *
 * Note we do NOT clear cheat_master_hook here even if this cheat
 * was the one that installed it: process_cheats short-circuits on
 * !cheat_active so the stale hook is observationally harmless, and
 * recomputing it would require scanning the other cheats which is
 * unnecessary overhead for a libretro-frontend toggle path. */
void cheat_disable(unsigned index)
{
   if (index >= MAX_CHEATS)
      return;
   RW_CHEATS_CHANGED();
   cheats[index].cheat_active = false;
#ifdef GPSP_CHEATS
   cheats_recount();
#endif
}

#ifndef GPSP_CHEATS
cheat_error cheat_parse(unsigned index, const char *code)
{
   int pos = 0;
   int codelen = strlen(code);
   cheat_type *ch;
   char buf[1024];

   /* Bounds-check before constructing the cheat pointer. Forming
    * '&cheats[index]' with an out-of-range index is undefined behavior
    * per C even if the pointer is never dereferenced. */
   if (index >= MAX_CHEATS)
      return CheatErrorTooMany;
   RW_CHEATS_CHANGED();
   ch = &cheats[index];
   /* Init to a known good state so any rejected replacement disables the
    * previous cheat rather than leaving stale code running. */
   ch->cheat_count = 0;
   ch->cheat_active = false;
   if ((size_t)codelen >= sizeof(buf))
      return CheatErrorTooBig;

   memcpy(buf, code, codelen+1);

   if (index > max_cheat)
      max_cheat = index;

   /* Replace all the non-hex chars to spaces */
   for (pos = 0; pos < codelen; pos++)
      if (!((buf[pos] >= '0' && buf[pos] <= '9') ||
            (buf[pos] >= 'a' && buf[pos] <= 'f') ||
            (buf[pos] >= 'A' && buf[pos] <= 'F')))
         buf[pos] = ' ';

   /* Try to parse as Code Breaker */
   pos = 0;
   while (pos < codelen)
   {
      /* `u32` is `unsigned long` on this ABI, and %x names `unsigned int *`.
       * Same width on MIPS32, so this happened to work -- but it is undefined,
       * and on a 64-bit host build of the core sscanf would write four bytes
       * into an eight-byte object and leave half of it whatever it was.  Scan
       * into the types the conversions actually name, then assign. */
      unsigned int op1; unsigned short op2;
      if (2 != sscanf(&buf[pos], "%08x %04hx", &op1, &op2))
         break;
      ch->codes[ch->cheat_count].address = op1;
      ch->codes[ch->cheat_count++].value = op2;
      pos += 13;
      while (pos < codelen && buf[pos] == ' ')
         pos++;
      if (ch->cheat_count >= MAX_CHEAT_CODES)
         break;
   }
   
   if (pos >= codelen)
   {
      /* Validate variable-length CodeBreaker records before activating the
       * cheat.  Opcode 5 consumes ceil(value*2/6) following records; opcode 4
       * consumes one.  Reject an incomplete sequence rather than letting
       * payload records execute as independent opcodes. */
      unsigned i, len;
      for (i = 0; i < ch->cheat_count; i += len)
      {
         len = codebreaker_code_len(ch, i);
         if (len > ch->cheat_count - i)
            return CheatErrorNotSupported;
      }

      /* Check whether these cheats are readable */
      if (has_encrypted_codebreaker(ch))
         return CheatErrorEncrypted;
      /* All codes were parsed! Process hook here */
      ch->cheat_active = true;
      update_hook_codebreaker(ch);
      return CheatNoError;
   }

   /* TODO parse other types here */
   return CheatErrorNotSupported;
}
#endif

#ifdef GPSP_CHEATS
/* ---- GPSP_CHEATS: the strict parser (docs/CHEATS.md section 3) -------------
 *
 * Upstream's parser replaced every non-hex character with a space and then
 * scanned "%08x %04hx" at a fixed 13-character stride, so a GameShark/AR code
 * ("XXXXXXXX YYYYYYYY") was accepted and run as two garbage CodeBreaker
 * records. This one tokenises, with explicit tagged families in cheats_gs.h:
 *
 *   CodeBreaker   "AAAAAAAA VVVV"  (or the 12 digits run together)
 *   raw write     "AAAAAAAA:VV" / ":VVVV" / ":VVVVVVVV" -- 8, 16, 32 bits
 *   GS1:/AR3:     encrypted 8+8 pairs; GS1RAW:/AR3RAW: decrypted pairs
 *
 * Codes are separated by whitespace, '+', ',' or ';' (libretro .cht joins
 * lines with '+'). One cheat has one family. Colon-style raw writes are
 * compiled to CodeBreaker records (8-bit -> type 3, 16-bit -> type 8, 32-bit
 * -> two type 8). Tagged GS/AR uses private normalized records; both
 * interpreters share the same RAM-only accessors and per-frame work budget.
 *
 * Then every CodeBreaker opcode is checked against the GPSP_CHEATS rules:
 * fixed addresses in EWRAM/IWRAM, 16/32-bit accesses aligned, encrypted
 * (type 9) refused, master/hook (type 1) and game id (type 0) accepted and
 * ignored.  A cheat that fails any check is left inactive and takes nothing
 * from the record pool. */
const char *cheat_error_name(cheat_error e)
{
   switch (e)
   {
   case CheatNoError:           return "ok";
   case CheatErrorTooMany:      return "too many cheats on";
   case CheatErrorTooBig:       return "code too long";
   case CheatErrorEncrypted:    return "encrypted CodeBreaker";
   case CheatErrorNotSupported: return "incomplete code";
   case CheatErrorSyntax:       return "not a code";
   case CheatErrorGameShark:    return "choose GS1: or AR3:";
   case CheatErrorRegion:       return "not a RAM code";
   case CheatErrorAlign:        return "odd address";
   case CheatErrorMixed:        return "mixed formats";
   case CheatErrorUnsupported:  return "unsupported GS/AR code";
   case CheatErrorWork:         return "too much work per frame";
   }
   return "?";
}

static int cheat_is_sep(char c)
{
   return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '+' ||
          c == ',' || c == ';';
}

static int cheat_hex(const char *p, unsigned n, u32 *out)
{
   u32 v = 0;
   unsigned i;
   if (n == 0 || n > 8)
      return 0;
   for (i = 0; i < n; i++)
   {
      char c = p[i];
      v <<= 4;
      if (c >= '0' && c <= '9')      v |= (u32)(c - '0');
      else if (c >= 'a' && c <= 'f') v |= (u32)(c - 'a' + 10);
      else if (c >= 'A' && c <= 'F') v |= (u32)(c - 'A' + 10);
      else return 0;
   }
   *out = v;
   return 1;
}

static int cheat_all_hex(const char *p, unsigned n)
{
   u32 d;
   unsigned i;
   if (n == 0)
      return 0;
   for (i = 0; i < n; i += 8)
      if (!cheat_hex(p + i, n - i > 8 ? 8 : n - i, &d))
         return 0;
   return 1;
}

/* Next token: [*tok, *tok + *n).  Returns 0 at the end of the string. */
static int cheat_token(const char **s, const char **tok, unsigned *n)
{
   const char *p = *s;
   while (*p && cheat_is_sep(*p))
      p++;
   if (!*p)
   {
      *s = p;
      return 0;
   }
   *tok = p;
   while (*p && !cheat_is_sep(*p))
      p++;
   *n = (unsigned)(p - *tok);
   *s = p;
   return 1;
}

/* One record onto the cheat being built, from the shared pool. */
static int cheat_push(cheat_type *ch, u32 address, u32 value)
{
   if ((unsigned)(ch->codes - cheat_pool) + ch->cheat_count >=
       CHEAT_POOL_RECORDS)
      return 0;
   ch->codes[ch->cheat_count].address = address;
   ch->codes[ch->cheat_count++].value = value;
   return 1;
}

static int cheat_in_ram(u32 address)
{
   u32 r = (address >> 24) & 0xF;
   return r == 0x2 || r == 0x3;
}

#include "cheats_gs.h"

#define CHEAT_SLIDE_MAX 4096u
static cheat_error cheat_validate(cheat_type *ch)
{
   unsigned i, len;
   for (i = 0; i < ch->cheat_count; i += len)
   {
      u32 code = ch->codes[i].address;
      u32 address = code & 0xfffffff;
      u32 opcode = code >> 28;
      unsigned work = 1;
      len = codebreaker_code_len(ch, i);
      if (len > ch->cheat_count - i)
         return CheatErrorNotSupported;     /* truncated slide/super payload */
      switch (opcode)
      {
      case 0x0:   /* game id: ignored, as upstream */
      case 0x1:   /* master/hook: accepted, never installed (cheats.h) */
      case 0xD:   /* button test: no address */
         break;
      case 0x9:
         return CheatErrorEncrypted;
      case 0x3:   /* 8-bit write */
      case 0x5:   /* super code: byte copy */
         if (!cheat_in_ram(address))
            return CheatErrorRegion;
         break;
      case 0xE:   /* add: bit 0 set = 32-bit at address & ~1 */
         if (!cheat_in_ram(address))
            return CheatErrorRegion;
         if ((address & 1) && ((address & ~1U) & 3))
            return CheatErrorAlign;
         break;
      default:    /* 2 4 6 7 8 A B C F: 16-bit accesses */
         if (!cheat_in_ram(address))
            return CheatErrorRegion;
         if (address & 1)
            return CheatErrorAlign;
         /* A slide's count is a raw 16-bit value run EVERY frame with only
          * its first address checked: 65,535 writes a frame, striding
          * anywhere (review C10).  No real slide code needs more than a
          * screen of tiles; refuse beyond CHEAT_SLIDE_MAX. */
         if (opcode == 0x4 && len == 2 &&
             (ch->codes[i + 1].address & 0xFFFF) > CHEAT_SLIDE_MAX)
            return CheatErrorNotSupported;
         break;
      }
      switch (opcode)
      {
      case 0: case 1: case 13: work = 0; break;
      case 2: case 6: case 14: work = 2; break;
      case 4: work = ch->codes[i + 1].address & 0xFFFF; break;
      case 5: work = (unsigned)(u16)ch->codes[i].value * 2; break;
      }
      if (work > CHEAT_FRAME_MAX - cheat_work_used - ch->work)
         return CheatErrorWork;
      ch->work += work;
   }
   return CheatNoError;
}

/* Text -> records at ch->codes (which the caller pointed into the pool).
 * Nothing is activated and nothing is taken from the pool here. */
static cheat_error cheat_compile(cheat_type *ch, const char *code)
{
   const char *s = code, *t, *t2;
   unsigned n, n2;
   int kind = 0;   /* 1 CodeBreaker, 2 raw */

   ch->cheat_count = 0;
   ch->gs_format = false;
   ch->work = 0;
   if (!code)
      return CheatErrorSyntax;
   while (*s && cheat_is_sep(*s)) s++;
   {
      unsigned used, family = cheat_family_prefix(s, (unsigned)strlen(s), &used);
      if (family) return cheat_gs_compile(ch, s + used, family);
   }
   while (cheat_token(&s, &t, &n))
   {
      const char *colon = (const char *)memchr(t, ':', n);
      u32 a = 0, v = 0;
      if (colon)
      {
         unsigned an = (unsigned)(colon - t), vn = n - an - 1;
         if (kind == 1)
            return CheatErrorMixed;
         kind = 2;
         if (!cheat_hex(t, an, &a) || !cheat_hex(colon + 1, vn, &v) ||
             (vn != 2 && vn != 4 && vn != 8))
            return CheatErrorSyntax;
         if (a > 0x0FFFFFFF || !cheat_in_ram(a))
            return CheatErrorRegion;
         if ((vn == 4 && (a & 1)) || (vn == 8 && (a & 3)))
            return CheatErrorAlign;
         if (vn == 2)
         { if (!cheat_push(ch, 0x30000000 | a, v)) return CheatErrorTooBig; }
         else if (vn == 4)
         { if (!cheat_push(ch, 0x80000000 | a, v)) return CheatErrorTooBig; }
         else if (!cheat_push(ch, 0x80000000 | a, v & 0xFFFF) ||
                  !cheat_push(ch, 0x80000000 | (a + 2), v >> 16))
            return CheatErrorTooBig;
         continue;
      }
      if (!cheat_all_hex(t, n))
         return CheatErrorSyntax;
      if (n == 16)
         return CheatErrorGameShark;
      if (n == 12)
      {
         cheat_hex(t, 8, &a);
         cheat_hex(t + 8, 4, &v);
      }
      else if (n == 8)
      {
         if (!cheat_token(&s, &t2, &n2) || !cheat_all_hex(t2, n2))
            return CheatErrorSyntax;
         if (n2 == 8)
            return CheatErrorGameShark;
         if (n2 != 4)
            return CheatErrorSyntax;
         cheat_hex(t, 8, &a);
         cheat_hex(t2, 4, &v);
      }
      else
         return CheatErrorSyntax;
      if (kind == 2)
         return CheatErrorMixed;
      kind = 1;
      if (!cheat_push(ch, a, v))
         return CheatErrorTooBig;
   }
   if (ch->cheat_count == 0)
      return CheatErrorSyntax;
   return cheat_validate(ch);
}

/* Would cheat_parse accept this text?  Compiles into the free end of the
 * pool and gives it straight back: no slot, no state, callable any time
 * (the ROM browser asks before any game is loaded). */
cheat_error cheat_check(const char *code)
{
   cheat_type tmp;
   tmp.cheat_active = false;
   tmp.codes = cheat_pool + cheat_pool_used;
   tmp.cheat_count = 0;
   return cheat_compile(&tmp, code);
}

cheat_error cheat_parse(unsigned index, const char *code)
{
   cheat_type *ch;
   cheat_error err;

   if (index >= MAX_CHEATS)
      return CheatErrorTooMany;
   RW_CHEATS_CHANGED();
   ch = &cheats[index];
   /* A rejected replacement disables the previous cheat in this slot rather
    * than leaving stale code running.  (Its records stay in the pool until
    * cheat_clear: the frontend rebuilds every slot on each change.) */
   ch->cheat_count = 0;
   ch->cheat_active = false;
   ch->codes = cheat_pool + cheat_pool_used;
   cheats_recount();
   if (index > max_cheat)
      max_cheat = index;

   err = cheat_compile(ch, code);
   if (err != CheatNoError)
   {
      ch->cheat_count = 0;
      return err;
   }
   cheat_pool_used += ch->cheat_count;
   cheat_work_used += ch->work;
   ch->cheat_active = true;
   cheats_recount();
   return CheatNoError;
}

/* The frontend's view (frontend-common/fe_cheats.c): plain ints, so it needs
 * no core header. */
int cheats_fe_parse(unsigned slot, const char *code)
{
   return (int)cheat_parse(slot, code);
}

int cheats_fe_check(const char *code)
{
   return (int)cheat_check(code);
}

void cheats_fe_clear(void)
{
   cheat_clear();
}

unsigned cheats_fe_slots(void)
{
   return MAX_CHEATS;
}

void cheats_fe_suspend(int on)
{
   cheats_set_suspended(on);
}

unsigned cheats_fe_ram_flushes(void)
{
   return (unsigned)cheat_ram_flushes;
}

unsigned cheats_fe_writes(void)
{
   return (unsigned)cheat_writes_changed;
}

unsigned cheats_fe_dropped(void)
{
   return (unsigned)cheat_writes_dropped;
}

const char *cheats_fe_error_name(int err)
{
   return cheat_error_name((cheat_error)err);
}
#endif
