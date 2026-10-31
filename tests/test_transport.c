// SPDX-License-Identifier: AGPL-3.0-only
/* Offline only: mocked USB transfers and a local socketpair, never claims hardware. */
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <poll.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <libusb.h>
#include "../magicbay_ntb.h"
static volatile sig_atomic_t bridge_stop;
struct event { int result, count; const unsigned char *data; };
static struct event events[32];
static unsigned event_count, event_next, clears;
static int clear_result;
static int fake_bulk(libusb_device_handle *h, unsigned char ep, unsigned char *p,
                     int n, int *actual, unsigned int timeout)
{
    (void)h; (void)timeout;
    if (event_next==event_count) { bridge_stop=1; *actual=0; return LIBUSB_ERROR_TIMEOUT; }
    struct event e=events[event_next++];
    *actual=e.count;
    assert(e.count<=n);
    if ((ep&0x80) && e.data && e.count>0) memcpy(p,e.data,e.count);
    return e.result;
}
static int fake_clear(libusb_device_handle *h, unsigned char ep)
{ (void)h; assert(ep==0x81 || ep==0x01); clears++; return clear_result; }
static const char *fake_error(int r) { (void)r; return "mock USB error"; }
#define libusb_bulk_transfer fake_bulk
#define libusb_clear_halt fake_clear
#define libusb_error_name fake_error
#include "../magicbay_bridge.h"
static unsigned delivered;
static int count_packet(void *arg, const unsigned char *p, size_t n)
{ (void)arg; assert(mb_ipv4(p,n)); delivered++; return 0; }
static int reject_packet(void *arg, const unsigned char *p, size_t n)
{ (void)arg; (void)p; (void)n; return -1; }
static void reset(void)
{ event_count=event_next=clears=0; clear_result=0; bridge_stop=0; delivered=0; }
static void add(int r, int count, const unsigned char *data)
{ assert(event_count<32); events[event_count++]=(struct event){r,count,data}; }
int main(void)
{
    unsigned char parameters[28]={0};
    mb_p16(parameters,28); mb_p16(parameters+2,1); mb_p32(parameters+4,16384);
    mb_p32(parameters+16,4096); mb_p16(parameters+20,4); mb_p16(parameters+24,4);
    struct mb_limits limits;
    assert(mb_parameters(parameters,28,&limits)==0);
    assert(limits.rx_max==16384 && limits.tx_max==4096 && limits.ndp==12 && limits.payload==28);
    assert(mb_parameters(parameters,27,&limits)<0);
    mb_p16(parameters+22,4); assert(mb_parameters(parameters,28,&limits)<0);
    mb_p16(parameters+22,0); mb_p16(parameters+24,64); mb_p16(parameters+20,16); mb_p16(parameters+22,8);
    assert(mb_parameters(parameters,28,&limits)==0);
    assert(limits.ndp==64 && limits.payload%16==8);
    unsigned char boundary_ip[MB_IP_MAX]={0x45};
    unsigned boundary_len=512-limits.payload;
    boundary_ip[2]=boundary_len>>8; boundary_ip[3]=boundary_len;
    unsigned char boundary_ntb[MB_TX_MAX];
    assert(mb_encode(boundary_ntb,sizeof(boundary_ntb),&limits,0,boundary_ip,boundary_len)==513);
    assert(mb_u16(boundary_ntb+8)==513);
    assert(mb_decode(boundary_ntb,513,count_packet,NULL)==0);
    delivered=0;
    unsigned char ip[100]={0x45,0,0,100}, ntb[4096], changed[4096];
    int length=mb_encode(ntb,sizeof(ntb),&limits,7,ip,sizeof(ip));
    assert(length>0 && (unsigned)length<=limits.tx_max);
    assert(mb_encode(changed,20,&limits,0,ip,sizeof(ip))<0);
    assert(mb_decode(ntb,length,count_packet,NULL)==0 && delivered==1);
    assert(mb_decode(ntb,length,reject_packet,NULL)==-2);
    for (int split=1;split<length;split++) {
        struct mb_stream stream={0}; delivered=0;
        assert(mb_feed(&stream,ntb,split,MB_RX_MAX,count_packet,NULL)==0 && delivered==0);
        assert(mb_feed(&stream,ntb+split,length-split,MB_RX_MAX,count_packet,NULL)==0);
        assert(delivered==1 && stream.used==0);
    }
    unsigned char pair[8192]; memcpy(pair,ntb,length); memcpy(pair+length,ntb,length);
    struct mb_stream stream={0}; delivered=0;
    assert(mb_feed(&stream,pair,2*length,MB_RX_MAX,count_packet,NULL)==0 && delivered==2);
    memcpy(changed,ntb,length); mb_p16(changed+limits.ndp+6,limits.ndp);
    assert(mb_decode(changed,length,count_packet,NULL)<0); /* NDP cycle */
    memcpy(changed,ntb,length); mb_p16(changed+limits.ndp+8,limits.ndp);
    assert(mb_decode(changed,length,count_packet,NULL)<0); /* metadata overlap */
    memcpy(changed,ntb,length); mb_p16(changed+limits.ndp+12,length-1); mb_p16(changed+limits.ndp+14,20);
    delivered=0; assert(mb_decode(changed,length,count_packet,NULL)<0 && delivered==0);
    for (int n=0;n<length;n++) assert(mb_decode(ntb,n,count_packet,NULL)<0);
    uint32_t seed=42;
    for (unsigned i=0;i<100000;i++) {
        memcpy(changed,ntb,length);
        seed=seed*1664525+1013904223;
        changed[seed%(unsigned)length]^=(unsigned char)(seed>>24);
        struct mb_stream fuzz={0};
        mb_feed(&fuzz,changed,length,MB_RX_MAX,count_packet,NULL);
    }
    int sockets[2]; assert(socketpair(AF_UNIX,SOCK_DGRAM,0,sockets)==0);
    struct bridge_ctx ctx={.utun_fd=sockets[0],.limits=limits};
    reset(); add(LIBUSB_ERROR_IO,0,NULL); add(LIBUSB_ERROR_TIMEOUT,length/2,ntb);
    add(0,length-length/2,ntb+length/2);
    mbim_to_utun(&ctx);
    assert(ctx.rx_packets==1 && clears==0);
    unsigned char frame[4096]; assert(recv(sockets[1],frame,sizeof(frame),0)==104);
    reset(); add(LIBUSB_ERROR_PIPE,0,NULL); add(0,length,ntb);
    mbim_to_utun(&ctx); assert(clears==1 && ctx.rx_packets==2);
    assert(recv(sockets[1],frame,sizeof(frame),0)==104);
    reset(); clear_result=LIBUSB_ERROR_NO_DEVICE; add(LIBUSB_ERROR_PIPE,0,NULL);
    mbim_to_utun(&ctx); assert(bridge_stop && event_next==1 && clears==1);
    reset(); add(LIBUSB_ERROR_NO_DEVICE,0,NULL); mbim_to_utun(&ctx); assert(event_next==1);
    reset(); for (int i=0;i<8;i++) add(LIBUSB_ERROR_IO,0,NULL);
    mbim_to_utun(&ctx); assert(event_next==8 && bridge_stop && clears==0);
    reset(); add(LIBUSB_ERROR_OVERFLOW,length,ntb); mbim_to_utun(&ctx);
    assert(ctx.rx_packets==2); /* Never decode undefined overflow data. */
    reset(); add(LIBUSB_ERROR_TIMEOUT,10,NULL); /* TX partial: drop, no resend */
    uint32_t af=htonl(AF_INET); memcpy(frame,&af,4); memcpy(frame+4,ip,sizeof(ip));
    assert(send(sockets[1],frame,104,0)==104);
    /* The mock stops on the next transfer, so send a second frame to finish the loop. */
    assert(send(sockets[1],frame,104,0)==104);
    utun_to_mbim(&ctx);
    assert(event_next==1 && ctx.tx_packets==0 && ctx.tx_dropped==2);
    close(sockets[0]); close(sockets[1]);
    puts("PASS: NTB limits, alignment, IPv4, splits, chain bounds, 100000 mutations; mocked USB recovery/timeout/overflow/TX");
    return 0;
}
