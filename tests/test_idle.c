// SPDX-License-Identifier: AGPL-3.0-only
/* Control-only standby: simulated MBIM, real local parent pipe, no USB/network. */
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <errno.h>
#include <signal.h>
#include <libusb.h>
#include "../magicbay_modem_codec.h"
static volatile sig_atomic_t bridge_stop;
static struct {struct mb_modem_values values;} mb_modem;
static const unsigned char basic_uuid[16]={0xa2,0x89,0xcc,0x33,0xbc,0xbb,0x8b,0x4f,0xb6,0xb0,0x13,0x3e,0xc2,0xaa,0xe6,0xdf};
static int device_state,fail_deactivation,deactivations,queries,ready_count,ticks;
static int stalled;
static uint32_t le32(const unsigned char *p) {return mbm_u32(p);}
static void put32(unsigned char *p,uint32_t v) {p[0]=v;p[1]=v>>8;p[2]=v>>16;p[3]=v>>24;}
static uint32_t mb_wire_tid(uint32_t v) {return v+0x10000000;}
static void mb_log(const char *text) {(void)text;}
static void mbm_export(unsigned cid) {assert(cid==12);}
static void mb_modem_tick(libusb_device_handle *h) {(void)h;ticks++;bridge_stop=1;}
static int mbm_monitor_stalled(void) {return stalled;}
static int fake_transfer(libusb_device_handle *h,uint8_t type,uint8_t request,uint16_t value,uint16_t index,unsigned char *p,uint16_t size,unsigned timeout) {
 (void)h;(void)value;(void)index;(void)timeout;
 assert(type==0x21 && request==0 && size==84 && le32(p+36)==12 && le32(p+40)==0);
 queries++;return size;
}
static int wait_for(libusb_device_handle *h,uint32_t type,uint32_t tid,unsigned char *p,int size) {
 (void)h;assert(type==0x80000003 && size>=84);memset(p,0,84);
 put32(p,type);put32(p+4,84);put32(p+8,mb_wire_tid(tid));put32(p+12,1);
 memcpy(p+20,basic_uuid,16);put32(p+36,12);put32(p+44,36);put32(p+52,(uint32_t)device_state);return 84;
}
static void mbim_deactivate_session0_quiet(libusb_device_handle *h,uint32_t tid,unsigned char *p,size_t size) {
 (void)h;(void)tid;(void)p;(void)size;deactivations++;if(!fail_deactivation) device_state=3;
}
#define IF_CTRL 0
#define libusb_control_transfer fake_transfer
#define MB_IDLE_READY() do {assert(mb_modem.values.activation_state==3);ready_count++;} while(0)
#include "../magicbay_idle.h"
static void reset(int state) {device_state=state;stalled=fail_deactivation=deactivations=queries=ready_count=ticks=0;bridge_stop=0;}
int main(void) {
 int fds[2];assert(!pipe(fds));char value[20];snprintf(value,sizeof(value),"%d",fds[0]);setenv("MAGICBAY_CONTROL_FD",value,1);
 reset(3);assert(mb_idle_monitor(NULL)==0);assert(ready_count==1 && deactivations==0 && ticks==1);
 reset(1);assert(mb_idle_monitor(NULL)==0);assert(ready_count==1 && deactivations==1 && queries==2);
 reset(1);fail_deactivation=1;assert(mb_idle_monitor(NULL)==-1);assert(ready_count==0 && ticks==0 && deactivations==2);
 reset(3);stalled=1;assert(mb_idle_monitor(NULL)==-1);assert(ready_count==1 && ticks==1);
 reset(3);close(fds[1]);assert(mb_idle_monitor(NULL)==0);assert(ready_count==1 && ticks==0);close(fds[0]);
 puts("PASS: standby requires confirmed deactivated session, clears old bearer, no activation or IP bridge, parent EOF");
}
