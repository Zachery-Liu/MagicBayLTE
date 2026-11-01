// SPDX-License-Identifier: AGPL-3.0-only
/* Offline decoder and same-session polling tests. All USB functions are mocks. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <libusb.h>
#include "../magicbay_modem_codec.h"
static uint32_t le32(const unsigned char *p) { return mbm_u32(p); }
static void put32(unsigned char *p, uint32_t v) { for (int i=0;i<4;i++) p[i]=(v>>(i*8))&255; }
static unsigned make_reply(unsigned char *p, unsigned cid, uint32_t tid, unsigned type)
{
    memset(p,0,256);
    unsigned header=type==0x80000007 ? 44 : 48;
    unsigned size=cid==9 ? 80 : cid==12 ? 36 : cid==10 ? 28 : cid==11 ? 20 : 4;
    put32(p,type);put32(p+4,header+size);put32(p+8,tid);put32(p+12,1);
    memcpy(p+20,mb_modem_uuid,16);put32(p+36,cid);put32(p+header-4,size);
    unsigned char *info=p+header;
    if (cid==9) {
        put32(info+4,3);put32(info+20,48);put32(info+24,10);put32(info+28,60);put32(info+32,20);
        const char *id="46001", *name="CHN-UNICOM";
        for (int i=0;id[i];i++) info[48+i*2]=id[i];
        for (int i=0;name[i];i++) info[60+i*2]=name[i];
    } else if (cid==11) put32(info,27);
    else if (cid==2) put32(info,1);
    else if (cid==10) { put32(info+4,2);put32(info+8,32); }
    else if (cid==12) put32(info+4,1);
    return header+size;
}
static unsigned queries, last_cid, interrupts, signal_queries;
static int failure_stage;
static uint32_t last_tid;
static time_t fake_time=1000;
static int fake_clock(clockid_t clock, struct timespec *t)
{ (void)clock; t->tv_sec=fake_time;t->tv_nsec=0;return 0; }
static int fake_control(libusb_device_handle *h,uint8_t bm,uint8_t request,uint16_t value,
                       uint16_t index,unsigned char *data,uint16_t length,unsigned timeout)
{
    (void)h;assert(value==0 && index==0 && timeout<=500);
    if ((failure_stage==1 && bm==0x21) || (failure_stage==2 && bm==0xa1)) return LIBUSB_ERROR_NO_DEVICE;
    if (bm==0x21) {
        assert(request==0 && (length==48 || length==84));
        assert(le32(data)==3 && le32(data+40)==0); /* QUERY only, never SET/OPEN/CLOSE */
        last_cid=le32(data+36);last_tid=le32(data+8);queries++;
        if (last_cid==11) signal_queries++;
        assert(last_cid==2 || last_cid==9 || last_cid==10 || last_cid==11 || last_cid==12);
        return length;
    }
    assert(bm==0xa1 && request==1 && length>=256);
    return make_reply(data,last_cid,last_tid,0x80000003);
}
static int fake_interrupt(libusb_device_handle *h,unsigned char ep,unsigned char *data,
                          int length,int *actual,unsigned timeout)
{ (void)h;(void)data;(void)length;assert(ep==0x82 && timeout==1);interrupts++;*actual=0;return failure_stage==3 ? LIBUSB_ERROR_NO_DEVICE : LIBUSB_ERROR_TIMEOUT; }
static int bridge_stop;
static void mb_log(const char *format, ...) { (void)format; }
#define basic_uuid mb_modem_uuid
#define EP_INT 0x82
#define IF_CTRL 0
#define libusb_control_transfer fake_control
#define libusb_interrupt_transfer fake_interrupt
#define clock_gettime fake_clock
#include "../magicbay_modem.h"
int main(void)
{
    unsigned char response[256];
    struct mb_modem_values values={.rssi=-1};
    unsigned size=make_reply(response,9,7,0x80000003);
    assert(mbm_decode(response,size,&values)==9);
    assert(!strcmp(values.provider_id,"46001") && !strcmp(values.provider_name,"CHN-UNICOM"));
    put32(response+48+28,60);put32(response+48+32,8);
    const unsigned char chinese[]={0x2d,0x4e,0xfd,0x56,0x54,0x80,0x1a,0x90};
    memcpy(response+48+60,chinese,8);
    assert(mbm_decode(response,size,&values)==9 && !strcmp(values.provider_name,"中国联通"));
    put32(response+48+28,0xfffffff0);put32(response+48+32,32);
    assert(!mbm_decode(response,size,&values) && !strcmp(values.provider_name,"中国联通"));
    size=make_reply(response,11,0,0x80000007);
    assert(mbm_decode(response,size,&values)==11 && values.rssi==27);
    put32(response+44,99);assert(mbm_decode(response,size,&values)==11 && values.rssi==99);
    put32(response+44,32);assert(!mbm_decode(response,size,&values) && values.rssi==99);
    size=make_reply(response,12,8,0x80000003);
    put32(response+48,1);assert(!mbm_decode(response,size,&values)); /* only session 0 */
    for (unsigned n=0;n<size;n++) assert(!mbm_decode(response,n,&values));
    size=make_reply(response,9,8,0x80000003);
    uint32_t seed=18;
    for (unsigned i=0;i<100000;i++) {
        unsigned char changed[256];memcpy(changed,response,size);
        seed=seed*1664525+1013904223;changed[seed%size]^=(unsigned char)(seed>>24);
        mbm_decode(changed,size,&values);
    }
    char directory[]="/private/tmp/magicbay-modem-test-XXXXXX";assert(mkdtemp(directory));
    char path[256];snprintf(path,sizeof(path),"%s/state.json",directory);
    char request_path[256];snprintf(request_path,sizeof(request_path),"%s/request",directory);
    int request_fd=open(request_path,O_WRONLY|O_CREAT,0600);assert(request_fd>=0);close(request_fd);
    setenv("MAGICBAY_SIGNAL_REQUEST_PATH",request_path,1);
    setenv("MAGICBAY_TELEMETRY_PATH",path,1);
    for (int i=0;i<15;i++) { mb_modem_tick(NULL);fake_time++; }
    assert(interrupts<=queries);
    assert(signal_queries==1); /* No 10-second signal polling anymore. */
    struct timespec changed[2]={{2000000,0},{2000000,0}};
    assert(utimensat(AT_FDCWD,request_path,changed,0)==0);
    mb_modem_tick(NULL);fake_time++;
    assert(signal_queries==2); /* Manual request before the 30-second deadline. */
    mb_modem_tick(NULL);
    changed[0].tv_sec++;changed[1].tv_sec++;
    assert(utimensat(AT_FDCWD,request_path,changed,0)==0);
    mb_modem_tick(NULL);
    assert(signal_queries==2); /* Rapid repeated requests are bounded. */
    assert(queries>=5 && mb_modem.values.sim_state==1 && mb_modem.values.activation_state==1);
    assert(mb_modem.values.packet_state==2 && mb_modem.values.data_class==32);
    assert(!strcmp(mb_modem.values.provider_name,"CHN-UNICOM") && mb_modem.signal_at[0]);
    FILE *f=fopen(path,"r");assert(f);char json[2048]={0};assert(fread(json,1,sizeof(json)-1,f)>0);fclose(f);
    assert(strstr(json,"\"provider_name\":\"CHN-UNICOM\"") && strstr(json,"\"rssi\":27"));
    /* A removed device must terminate the stale handle on every USB path. */
    for (failure_stage=1;failure_stage<=3;failure_stage++) {
        bridge_stop=0;mb_modem.pending_tid=failure_stage==1 ? 0 : 123;
        mb_modem.sent_at=fake_time-1;mb_modem.due[0]=0;
        mb_modem_tick(NULL);assert(bridge_stop);
    }
    failure_stage=0;bridge_stop=0;
    mb_modem.started_at=fake_time;mb_modem.last_response=fake_time;
    fake_time+=74;assert(!mbm_monitor_stalled());
    fake_time++;assert(mbm_monitor_stalled());
    /* Valid replies, including a still-searching registration, keep it alive. */
    mb_modem.pending_tid=123;last_tid=123;last_cid=9;mb_modem.sent_at=fake_time-1;
    mb_modem_tick(NULL);assert(!bridge_stop && !mbm_monitor_stalled());
    unlink(path);unlink(request_path);rmdir(directory);
    puts("PASS: provider UTF-16, malformed/session bounds, 100000 mutations, bounded queries, unplug on send/read/interrupt and control-session liveness");
    return 0;
}
