// SPDX-License-Identifier: AGPL-3.0-only
/* MBIM Basic Connect read-only telemetry. Never reads subscriber/device identifiers. */
#ifndef MAGICBAY_MODEM_CODEC_H
#define MAGICBAY_MODEM_CODEC_H
#include <CoreFoundation/CoreFoundation.h>
#include <stdint.h>
#include <string.h>
struct mb_modem_values {
    int sim_state, registration_state, packet_state, activation_state, rssi;
    uint32_t data_class;
    char provider_name[160], provider_id[32];
};
static const unsigned char mb_modem_uuid[16]={
    0xa2,0x89,0xcc,0x33,0xbc,0xbb,0x8b,0x4f,0xb6,0xb0,0x13,0x3e,0xc2,0xaa,0xe6,0xdf
};
static uint32_t mbm_u32(const unsigned char *p)
{ return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static int mbm_string(const unsigned char *info, size_t n, size_t pos, char *out, size_t capacity)
{
    if (pos>n || n-pos<8) return -1;
    uint32_t offset=mbm_u32(info+pos), length=mbm_u32(info+pos+4);
    if (!length) { out[0]=0; return 0; }
    if (offset<48 || offset>n || length>n-offset || length%2 || length>512) return -1;
    CFStringRef string=CFStringCreateWithBytes(NULL,info+offset,length,kCFStringEncodingUTF16LE,FALSE);
    if (!string) return -1;
    Boolean ok=CFStringGetCString(string,out,capacity,kCFStringEncodingUTF8);
    CFRelease(string);
    return ok ? 0 : -1;
}
/* Returns CID on a valid supported response/indication, zero otherwise.
 * All length/fragment checks precede access, and invalid fields never partially commit. */
static unsigned mbm_decode(const unsigned char *p, size_t n, struct mb_modem_values *values)
{
    if (n<44 || mbm_u32(p+4)>n || mbm_u32(p+4)<44 || mbm_u32(p+12)!=1 ||
        mbm_u32(p+16)!=0 || memcmp(p+20,mb_modem_uuid,16)) return 0;
    n=mbm_u32(p+4);
    uint32_t type=mbm_u32(p), cid=mbm_u32(p+36);
    unsigned header;
    if (type==0x80000003) {
        if (n<48 || mbm_u32(p+40)!=0) return 0;
        header=48;
    } else if (type==0x80000007) { header=44; }
    else return 0;
    uint32_t length=mbm_u32(p+header-4);
    if (length>n-header) return 0;
    const unsigned char *info=p+header;
    struct mb_modem_values next=*values;
    switch (cid) {
    case 2:
        if (length<4) return 0;
        next.sim_state=(int)mbm_u32(info);
        break;
    case 9:
        if (length<48) return 0;
        next.registration_state=(int)mbm_u32(info+4);
        if (mbm_string(info,length,20,next.provider_id,sizeof(next.provider_id)) ||
            mbm_string(info,length,28,next.provider_name,sizeof(next.provider_name))) return 0;
        break;
    case 10:
        if (length<12) return 0;
        next.packet_state=(int)mbm_u32(info+4);
        next.data_class=mbm_u32(info+8);
        break;
    case 11:
        if (length<4) return 0;
        next.rssi=(int)mbm_u32(info);
        if (!(next.rssi>=0 && next.rssi<=31) && next.rssi!=99) return 0;
        break;
    case 12:
        if (length<36 || mbm_u32(info)!=0) return 0;
        next.activation_state=(int)mbm_u32(info+4);
        break;
    default: return 0;
    }
    *values=next;
    return cid;
}
#endif
