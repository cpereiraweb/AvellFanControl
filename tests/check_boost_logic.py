"""Execute actual driver's boost functions with mocked EC transport, never hardware."""
from pathlib import Path
import subprocess
import tempfile
import sys
src = Path(sys.argv[1]).read_text()
name = src[src.index('static const char *profile_name'):src.index('static int write_ec_internal')]
logic = src[src.index('static int stop_boost_locked'):src.index('static struct kobj_attribute fan_boost_attr')]
preamble = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#include <sys/types.h>
typedef uint8_t u8;
struct work_struct {int unused;};
struct kobject {int unused;};
struct kobj_attribute {int unused;};
static int snapshot_lock, system_wq, ticks, writes, fail_read, fail_write, mismatch;
static bool boost_active, manual_dirty;
static u8 mode=0x20, flags;
#define HZ 100
#define DECLARE_DELAYED_WORK(name, fn) int name
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define pr_err_ratelimited(...) ((void)0)
#define sysfs_emit(buf, ...) sprintf(buf, __VA_ARGS__)
static int sysfs_streq(const char *a,const char *b) { return !strcmp(a,b); }
static void schedule_delayed_work(int *w,int t) { ticks=t; }
static void mod_delayed_work(int q,int *w,int t) { ticks=t; }
static int read_ec(int addr,u8 *out) {
 if(fail_read) return -EIO;
 *out=addr==0x0751?mode:flags; return 0;
}
static int write_profile(u8 v) {
 writes++;
 if(fail_write) return -EIO;
 if(!mismatch) mode=v;
 return 0;
}
'''
checks = r'''
int main(void) {
 assert(fan_boost_store(0,0,"invalid",7)==-EINVAL && writes==0);
 mode=0x60;
 assert(fan_boost_store(0,0,"test",4)==-EOPNOTSUPP && writes==0);
 mode=0x20; flags=4;
 assert(fan_boost_store(0,0,"test",4)==-EBUSY && writes==0);
 flags=0; fail_read=1;
 assert(fan_boost_store(0,0,"test",4)==-EIO && writes==0);
 fail_read=0;
 assert(fan_boost_store(0,0,"test",4)==4);
 assert(mode==0x60 && boost_active && ticks==15*HZ);
 assert(fan_boost_store(0,0,"test",4)==-EBUSY);
 mode=0x70; /* Physical profile changed during test. */
 boost_timeout(0);
 assert(mode==0x30 && !boost_active);
 assert(fan_boost_store(0,0,"test",4)==4);
 fail_read=1;
 boost_timeout(0);
 assert(boost_active && ticks==HZ);
 fail_read=0;
 boost_timeout(0);
 assert(mode==0x30 && !boost_active);
 mismatch=1;
 assert(fan_boost_store(0,0,"test",4)==-EIO && !boost_active);
 mismatch=0; fail_write=1;
 assert(fan_boost_store(0,0,"test",4)==-EIO && !boost_active);
 fail_write=0;
 assert(fan_boost_store(0,0,"test",4)==4);
 assert(fan_boost_store(0,0,"auto",4)==4 && mode==0x30 && !boost_active);
 puts("PASS: invalid states, timer, concurrent profile, read/write errors, restore retry, manual cancel");
}
'''
with tempfile.TemporaryDirectory() as d:
    c = Path(d)/'test.c'; binary=Path(d)/'test'
    c.write_text(preamble+name+logic+checks)
    subprocess.run(['gcc', '-std=gnu11', str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)],check=True)
