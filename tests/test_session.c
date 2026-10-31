// SPDX-License-Identifier: AGPL-3.0-only
/* No hardware: delayed OPEN, transient control stall, cancellation, validation. */
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <libusb.h>
static volatile sig_atomic_t bridge_stop;
static int mb_shutting_down;
static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static void put32(unsigned char *p,uint32_t v) {
    p[0]=v;p[1]=v>>8;p[2]=v>>16;p[3]=v>>24;
}
struct response { int result;uint32_t type,tid,length,status; };
static struct response events[8];static unsigned count,next;
static int receive_one(libusb_device_handle *h,unsigned char *p,int max) {
    (void)h;assert(max>=48);assert(next<count);
    struct response e=events[next++];memset(p,0,(size_t)max);
    put32(p,e.type);put32(p+4,e.length);put32(p+8,e.tid);put32(p+12,e.status);
    return e.result;
}
static int fake_usleep(useconds_t n) { (void)n;return 0; }
#define usleep fake_usleep
#include "../magicbay_session.h"
#undef usleep
static void reset(void) { next=count=0;bridge_stop=mb_shutting_down=0;mb_session_base=0x10000000; }
static void push(int result,uint32_t type,uint32_t tid,uint32_t length) {
    events[count++]=(struct response){result,type,tid,length,0};
}
int main(void) {
    unsigned char p[64];
    reset();push(16,0x80000001,500,16);push(16,0x80000001,mb_wire_tid(500),16);
    assert(wait_for(NULL,0x80000001,500,p,sizeof(p))==16 && next==2);
    reset();push(LIBUSB_ERROR_PIPE,0,0,0);push(16,0x80000001,mb_wire_tid(500),16);
    assert(wait_for(NULL,0x80000001,500,p,sizeof(p))==16 && next==2);
    reset();for(int i=0;i<4;i++) push(LIBUSB_ERROR_PIPE,0,0,0);
    assert(wait_for(NULL,0x80000001,500,p,sizeof(p))==LIBUSB_ERROR_PIPE && next==4);
    reset();push(LIBUSB_ERROR_NO_DEVICE,0,0,0);
    assert(wait_for(NULL,0x80000001,500,p,sizeof(p))==LIBUSB_ERROR_NO_DEVICE);
    reset();bridge_stop=1;assert(wait_for(NULL,0x80000001,500,p,sizeof(p))==LIBUSB_ERROR_INTERRUPTED && next==0);
    reset();push(16,0x80000001,mb_wire_tid(500),1000);push(16,0x80000001,mb_wire_tid(500),16);
    assert(wait_for(NULL,0x80000001,500,p,sizeof(p))==16 && next==2);
    reset();push(16,0x80000004,mb_wire_tid(501),16);
    assert(wait_for(NULL,0x80000003,501,p,sizeof(p))==-100);
    reset();push(LIBUSB_ERROR_PIPE,0,0,0);
    assert(wait_for(NULL,0x80000003,501,p,sizeof(p))==LIBUSB_ERROR_PIPE && next==1);
    puts("PASS: fresh startup transaction IDs, delayed responses, bounded OPEN read retries and cancellation");
}
