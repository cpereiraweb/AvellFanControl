"""Actual C state machine with simulated EC, not a duplicate implementation."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
logic = (root/'driver/profiles/fan_manual.h').read_text()
logic = logic[:logic.index('static struct kobj_attribute fan_control_attr')]
preamble = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#include <sys/types.h>
typedef uint8_t u8;
typedef uint16_t u16;
struct work_struct {int unused;};
struct kobject {int unused;};
struct kobj_attribute {int unused;};
static int snapshot_lock, system_wq, ticks, writes, fail_address=-1, fail_disable;
static bool manual_dirty, boost_active;
static unsigned long jiffies;
static u8 ram[65536];
static int module_refs;
#define THIS_MODULE 0
static bool try_module_get(int m) { module_refs++; return true; }
static void module_put(int m) { module_refs--; assert(module_refs>=0); }
#define HZ 100
#define DECLARE_DELAYED_WORK(name, fn) int name
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define pr_err_ratelimited(...) ((void)0)
#define sysfs_emit(buf, ...) sprintf(buf, __VA_ARGS__)
#define time_after_eq(a,b) ((long)((a)-(b))>=0)
#define time_before(a,b) ((long)((a)-(b))<0)
static int sysfs_streq(const char *a,const char *b) { return !strcmp(a,b); }
static int kstrtouint(const char *s,int base,unsigned int *out) {
 char *end; unsigned long v=strtoul(s,&end,base);
 if(*end || !*s || v>100000) return -EINVAL;
 *out=v; return 0;
}
static void schedule_delayed_work(int *w,int t) { ticks=t; }
static void mod_delayed_work(int q,int *w,int t) { ticks=t; }
static int read_ec(int addr,u8 *out) { *out=ram[addr]; return 0; }
static int write_ec_internal(int addr,u8 value) {
 writes++;
 if(addr==fail_address || (fail_disable && addr==0x07c6 && !(value&4))) return -EIO;
 ram[addr]=value; return 0;
}
static int write_profile(u8 value) { return write_ec_internal(0x0751,value); }
static const char *profile_name(u8 v) { return v==0x20 || v==0xa0 || v==0x30 ? "known" : NULL; }
static int stop_boost_locked(void) { boost_active=false; return 0; }
'''
checks = r'''
static void reset(void) {
 assert(module_refs==0);
 memset(ram,0,sizeof(ram));
 ram[0x0741]=4; ram[0x0751]=0xa0; ram[0x078e]=0xec; ram[0x043e]=65; ram[0x044f]=45;
 writes=0; fail_address=-1; fail_disable=0; boost_active=false;
 manual_dirty=false; manual_running=false; manual_emergency=false; jiffies=0;
}
int main(void) {
 int i;
 reset();
 assert(start_manual_locked(45)==-EINVAL && writes==0);
 assert(start_manual_locked(61)==-EINVAL && writes==0);
 ram[0x043e]=85;
 assert(start_manual_locked(70)==-ERANGE && writes==0);
 reset(); ram[0x07c6]=4;
 assert(start_manual_locked(70)==-EOPNOTSUPP && writes==0);
 reset();
 assert(start_manual_locked(70)==0);
 assert(manual_running && manual_dirty && manual_percent==70 && module_refs==1);
 assert(ram[0x0741]==5);
 assert(ram[0x0f20]==140 && ram[0x0f50]==140 && ram[0x1804]==140);
 assert(ram[0x0f00]==85 && ram[0x0f30]==80 && ram[0x0f21]==200);
 assert(ram[0x07c5]==128 && ram[0x07c6]==4);
 assert(start_manual_locked(80)==-EBUSY);
 jiffies=30*HZ;
 manual_watchdog(0);
 assert(!manual_dirty && !manual_running && ram[0x07c6]==0 && ram[0x07c5]==0 && ram[0x0741]==4);
 for(i=0;i<96;i++) assert(ram[0x0f00+i]==0);
 reset(); fail_address=0x0f05;
 assert(start_manual_locked(70)==-EIO);
 assert(!manual_running && !(ram[0x07c6]&4));
 fail_address=-1;
 manual_watchdog(0);
 assert(!manual_dirty);
 for(i=0;i<96;i++) assert(ram[0x0f00+i]==0);
 reset(); assert(start_manual_locked(75)==0);
 ram[0x0751]=0x30;
 manual_watchdog(0);
 assert(!manual_dirty && ram[0x0751]==0x30);
 reset(); assert(start_manual_locked(75)==0);
 ram[0x044f]=80;
 manual_watchdog(0);
 assert(!manual_dirty && !manual_running);
 reset(); assert(start_manual_locked(75)==0);
 fail_disable=1;
 assert(stop_manual_locked()==-EIO && manual_dirty && manual_emergency);
 assert(ram[0x0751]&0x40);
 fail_disable=0;
 manual_watchdog(0);
 assert(!manual_dirty && !manual_emergency && ram[0x0751]==0xa0);
 reset();
 for(i=0;i<96;i++) ram[0x0f00+i]=i;
 assert(start_manual_locked(100)==0);
 assert(stop_manual_locked()==0);
 for(i=0;i<96;i++) assert(ram[0x0f00+i]==i);
 reset(); ram[0x0741]=5;
 assert(start_manual_locked(70)==-EOPNOTSUPP && writes==0);
 reset(); fail_address=0x0741;
 assert(start_manual_locked(70)==-EIO);
 assert(ram[0x0741]==4 && !manual_dirty && ram[0x07c6]==0);
 reset(); assert(start_manual_locked(70)==0);
 ram[0x1804]=100; jiffies=6*HZ;
 manual_watchdog(0);
 assert(!manual_dirty && !strcmp(manual_reason,"firmware_override") && ram[0x0741]==4);
 reset(); assert(start_manual_locked(70)==0);
 ram[0x0741]=4;
 manual_watchdog(0);
 assert(!manual_dirty && !strcmp(manual_reason,"firmware_override"));
 reset(); assert(start_manual_locked(70)==0);
 ram[0x0741]|=8; /* Preserve an unrelated firmware bit on restore. */
 assert(stop_manual_locked()==0 && ram[0x0741]==12);
 reset(); ram[0x0741]=0;
 assert(start_manual_locked(50)==0 && ram[0x0741]==1);
 assert(stop_manual_locked()==0 && ram[0x0741]==0);
 assert(start_manual_locked(100)==0 && ram[0x1804]==200);
 assert(stop_manual_locked()==0 && ram[0x0741]==0);
 reset(); ram[0x0741]=2;
 assert(start_manual_locked(70)==-EOPNOTSUPP && writes==0);
 reset(); assert(start_manual_locked(70)==0);
 { char command[64]; unsigned int old_id=manual_id;
 jiffies=20*HZ;
 sprintf(command,"renew %u",manual_id);
 assert(fan_control_store(0,0,command,strlen(command))>0);
 jiffies=35*HZ; manual_watchdog(0);
 assert(manual_running && manual_dirty);
 sprintf(command,"auto %u",manual_id);
 assert(fan_control_store(0,0,command,strlen(command))>0 && !manual_dirty);
 assert(start_manual_locked(70)==0 && manual_id!=old_id);
 sprintf(command,"auto %u",old_id);
 assert(fan_control_store(0,0,command,strlen(command))==-ESTALE && manual_running);
 sprintf(command,"renew %u",old_id);
 assert(fan_control_store(0,0,command,strlen(command))==-ESTALE);
 assert(stop_manual_locked()==0);
 }
 reset(); assert(start_manual_locked(70)==0);
 jiffies=6*HZ; ram[0x1804]=90;
 { char command[64]; sprintf(command,"renew %u",manual_id);
 assert(fan_control_store(0,0,command,strlen(command))==-EREMOTEIO && !manual_dirty); }
 assert(module_refs==0);
 puts("PASS: ranges, hot start, ownership, table, timeout, partial failure, physical profile, thermal guard, emergency retry, exact restoration");
}
'''
with tempfile.TemporaryDirectory() as d:
    c=Path(d)/'test.c'; binary=Path(d)/'test'
    c.write_text(preamble+logic+checks)
    subprocess.run(['gcc','-std=gnu11',str(c),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
