// SPDX-License-Identifier: AGPL-3.0-only
/* Bounded NTB16/session-0 IPv4 codec. No USB or network operations. */
#ifndef MAGICBAY_NTB_H
#define MAGICBAY_NTB_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define MB_RX_MAX 16384u
#define MB_TX_MAX 4096u
#define MB_IP_MAX 2000u
static uint16_t mb_u16(const unsigned char *p) { return p[0] | (uint16_t)p[1] << 8; }
static uint32_t mb_u32(const unsigned char *p) { return mb_u16(p) | (uint32_t)mb_u16(p+2) << 16; }
static void mb_p16(unsigned char *p, unsigned v) { p[0]=v; p[1]=v>>8; }
static void mb_p32(unsigned char *p, uint32_t v) { mb_p16(p,v); mb_p16(p+2,v>>16); }
struct mb_limits {
    unsigned rx_max, tx_max, ndp, payload, formats;
};
static unsigned mb_align(unsigned n, unsigned divisor, unsigned remainder)
{
    return n + (remainder + divisor - n % divisor) % divisor;
}
static int mb_parameters(const unsigned char *p, size_t n, struct mb_limits *l)
{
    if (n < 28 || mb_u16(p) < 28 || mb_u16(p) > n || !(mb_u16(p+2)&1)) return -1;
    unsigned in=mb_u32(p+4), out=mb_u32(p+16);
    unsigned div=mb_u16(p+20), rem=mb_u16(p+22), align=mb_u16(p+24);
    if (in < 2048 || out < 2048 || div < 4 || (div&(div-1)) ||
        align < 4 || (align&(align-1)) || rem >= div || div >= out || align >= out) return -1;
    l->formats=mb_u16(p+2);
    /* IN buffer must be a multiple of the observed bulk max packet (512). */
    l->rx_max=(in < MB_RX_MAX ? in : MB_RX_MAX) / 512 * 512;
    l->tx_max=out < MB_TX_MAX ? out : MB_TX_MAX;
    l->ndp=mb_align(12,align,0);
    l->payload=mb_align(l->ndp+16,div,rem);
    return l->payload+20 <= l->tx_max ? 0 : -1;
}
static int mb_ipv4(const unsigned char *p, size_t n)
{
    return n >= 20 && n <= MB_IP_MAX && (p[0]>>4)==4 &&
        (p[0]&15)>=5 && (unsigned)(p[0]&15)*4 <= n &&
        ((unsigned)p[2]*256+p[3])==n;
}
static int mb_encode(unsigned char *out, size_t capacity, const struct mb_limits *l,
                     uint16_t sequence, const unsigned char *ip, size_t n)
{
    size_t total=l->payload+n;
    /* Force a short USB packet below the advertised NTB max, as CDC-NCM does. */
    if (total%512==0 && total<l->tx_max) total++;
    if (!mb_ipv4(ip,n) || total > capacity || total > l->tx_max || total > 65535) return -1;
    memset(out,0,total);
    mb_p32(out,0x484d434e); mb_p16(out+4,12); mb_p16(out+6,sequence);
    mb_p16(out+8,(unsigned)total); mb_p16(out+10,l->ndp);
    mb_p32(out+l->ndp,0x00535049); mb_p16(out+l->ndp+4,16);
    mb_p16(out+l->ndp+8,l->payload); mb_p16(out+l->ndp+10,(unsigned)n);
    memcpy(out+l->payload,ip,n);
    return (int)total;
}
typedef int (*mb_deliver)(void *, const unsigned char *, size_t);
/* Validate the entire chain before delivering any datagram. */
static int mb_decode(const unsigned char *p, size_t n, mb_deliver deliver, void *arg)
{
    unsigned offsets[64], lengths[64], count=0;
    if (n<12 || mb_u32(p)!=0x484d434e || mb_u16(p+4)!=12 || mb_u16(p+8)!=n) return -1;
    unsigned ndp=mb_u16(p+10);
    while (ndp) {
        if (count==64 || ndp<12 || ndp>n || n-ndp<16) return -1;
        for (unsigned i=0;i<count;i++) if (offsets[i]==ndp) return -1;
        unsigned len=mb_u16(p+ndp+4);
        if (len<16 || len%4 || len>n-ndp) return -1;
        for (unsigned i=0;i<count;i++)
            if (ndp<offsets[i]+lengths[i] && offsets[i]<ndp+len) return -1;
        offsets[count]=ndp; lengths[count++]=len;
        ndp=mb_u16(p+ndp+6);
    }
    for (unsigned i=0;i<count;i++) {
        unsigned start=offsets[i], end=start+lengths[i];
        int terminated=0;
        for (unsigned pos=start+8;pos+4<=end;pos+=4) {
            unsigned off=mb_u16(p+pos), len=mb_u16(p+pos+2);
            if (!off && !len) { terminated=1; break; }
            if (off<12 || !len || off>n || len>n-off) return -1;
            for (unsigned j=0;j<count;j++)
                if (off<offsets[j]+lengths[j] && offsets[j]<off+len) return -1;
            if (mb_u32(p+start)==0x00535049 && !mb_ipv4(p+off,len)) return -1;
        }
        if (!terminated) return -1;
    }
    for (unsigned i=0;i<count;i++) {
        unsigned start=offsets[i], end=start+lengths[i];
        if (mb_u32(p+start)!=0x00535049) continue;
        for (unsigned pos=start+8;pos+4<=end;pos+=4) {
            unsigned off=mb_u16(p+pos), len=mb_u16(p+pos+2);
            if (!off && !len) break;
            if (deliver(arg,p+off,len)) return -2;
        }
    }
    return 0;
}
struct mb_stream { unsigned char data[MB_RX_MAX]; size_t used; };
/* Preserve timeout partial data, but never trust bytes from IO/OVERFLOW errors. */
static int mb_feed(struct mb_stream *s, const unsigned char *p, size_t n,
                   unsigned limit, mb_deliver deliver, void *arg)
{
    while (n) {
        size_t target=s->used<12 ? 12 : mb_u16(s->data+8);
        if (target<12 || target>limit || target>sizeof(s->data) || s->used>target) goto bad;
        size_t take=target-s->used;
        if (take>n) take=n;
        memcpy(s->data+s->used,p,take); s->used+=take; p+=take; n-=take;
        if (s->used<12) continue;
        if (mb_u32(s->data)!=0x484d434e || mb_u16(s->data+4)!=12) goto bad;
        target=mb_u16(s->data+8);
        if (target<12 || target>limit || target>sizeof(s->data)) goto bad;
        if (s->used==target) {
            int result=mb_decode(s->data,s->used,deliver,arg);
            s->used=0;
            if (result) return result;
        }
    }
    return 0;
bad:
    s->used=0;
    return -1;
}
#endif
