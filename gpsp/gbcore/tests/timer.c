#include "gbcore/gbcore.h"
#include "gbcore/tgbdual/gb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static byte rom[32768];
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s DIV=%u TIMA=%u\n",__LINE__,#x,cpu_read(0xff04),cpu_read(0xff05)); exit(1); } } while (0)
static gbcore_t *boot(int mode) {
  byte sum=0;gbcore_callbacks_t cb={0};memset(rom,0,sizeof rom);
  rom[0x143]=mode?0x80:0;rom[0x146]=3;rom[0x14b]=0x33;
  for(unsigned i=0x134;i<=0x14c;i++)sum=(byte)(sum-rom[i]-1);
  rom[0x14d]=sum;
  gbcore_t *c=gbcore_create(NULL,rom,sizeof rom,mode?FE_CONSOLE_GBC:FE_CONSOLE_GB,32768,&cb);CHECK(c);
  if(mode==2){int dat[8];cpu_save_state(dat);dat[2]=1;cpu_restore_state(dat);}
  return c;
}
static void reset(void) {
  int dat[4]={0};cpu_restore_state_ex(dat);c_regs_PC=0x150;
  cpu_write(0xff07,0);cpu_write(0xff04,0);cpu_write(0xff05,0);cpu_write(0xff0f,0);
}
static void ticks(unsigned cpu_clocks,int mode) {cpu_exec((unsigned short)(cpu_clocks/(mode==2?2:1)));}
int main(int argc,char **argv) {
  const char *which=argc>1?argv[1]:"all";
  for(int mode=0;mode<3;mode++) {
    gbcore_t *c=boot(mode);
    reset();ticks(256,mode);CHECK(cpu_read(0xff05)==0); /* disabled timer */
    if(!strcmp(which,"all")||!strcmp(which,"div")) {
      reset();ticks(252,mode);CHECK(cpu_read(0xff04)==0);
      ticks(4,mode);CHECK(cpu_read(0xff04)==1);
      for(unsigned i=2;i<=300;i++){ticks(256,mode);CHECK(cpu_read(0xff04)==(byte)i);c_regs_PC=0x150;}
      cpu_write(0xff04,0xab);CHECK(cpu_read(0xff04)==0);ticks(256,mode);CHECK(cpu_read(0xff04)==1);
    }
    if(!strcmp(which,"all")||!strcmp(which,"boundary")) {
      const unsigned periods[]={1024,16,64,256};
      for(int sel=0;sel<4;sel++) {
        reset();cpu_write(0xff07,(byte)(4|sel));ticks(periods[sel]-4,mode);CHECK(cpu_read(0xff05)==0);
        ticks(4,mode);CHECK(cpu_read(0xff05)==1);
        ticks(periods[sel],mode);CHECK(cpu_read(0xff05)==2);
        cpu_write(0xff05,0x40);ticks(periods[sel],mode);CHECK(cpu_read(0xff05)==0x41);
      }
    }
    if(!strcmp(which,"all")||!strcmp(which,"multi")) {
      reset();cpu_write(0xff07,5);cpu_write(0xff05,0xfe);cpu_write(0xff06,0xfc);
      ticks(12,mode);CHECK(cpu_read(0xff05)==0xfe);
      /* A real 24-T-clock CALL crosses two 16-T-clock timer boundaries. */
      byte *r=get_rom();r[c_regs_PC]=0xcd;r[c_regs_PC+1]=0;r[c_regs_PC+2]=2;
      ticks(24,mode);CHECK(cpu_read(0xff05)==0xfc);CHECK(cpu_read(0xff0f)&4);
      cpu_write(0xff0f,0);ticks(64,mode);CHECK(cpu_read(0xff05)==0xfc);CHECK(cpu_read(0xff0f)&4);
    }
    gbcore_shutdown(c);printf("PASS timer %s mode=%d\n",which,mode);
  }
  return 0;
}
