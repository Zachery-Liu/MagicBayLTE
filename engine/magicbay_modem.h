// SPDX-License-Identifier: AGPL-3.0-only
/* Included only by the managed engine. Uses its EXISTING MBIM session/handle.
 * One bounded transaction at a time; no OPEN/CLOSE, USB claim, SET, reset or route changes. */
#include "magicbay_modem_codec.h"
#ifndef MBM_TRANSFER_RX
#define MBM_TRANSFER_RX() 0ULL
#define MBM_TRANSFER_TX() 0ULL
#endif
static struct {
    struct mb_modem_values values;
    double due[5], sent_at;
    uint32_t sequence, pending_tid;
    unsigned pending_cid;
    char signal_at[40], registration_at[40], sim_at[40], packet_at[40], activation_at[40];
    struct timespec request_mtime;
    double last_request;
    int request_seen;
    double last_export, started_at, last_response;
} mb_modem={.values={.sim_state=-1,.registration_state=-1,.packet_state=-1,.activation_state=-1,.rssi=-1},.sequence=4000000};

static double mbm_now(void)
{ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9; }
static void mbm_stamp(char *out, size_t size)
{
    struct timespec t; clock_gettime(CLOCK_REALTIME,&t);
    struct tm tm; gmtime_r(&t.tv_sec,&tm);
    char prefix[30];strftime(prefix,sizeof(prefix),"%Y-%m-%dT%H:%M:%S",&tm);
    snprintf(out,size,"%s.%03ldZ",prefix,t.tv_nsec/1000000);
}
static void mbm_json_string(FILE *f, const char *text)
{
    fputc('"',f);
    for (const unsigned char *p=(const unsigned char *)text;*p;p++) {
        if (*p=='"' || *p=='\\') { fputc('\\',f); fputc(*p,f); }
        else if (*p<32) fprintf(f,"\\u%04x",*p);
        else fputc(*p,f);
    }
    fputc('"',f);
}
static void mbm_export(unsigned cid)
{
    const char *path=getenv("MAGICBAY_TELEMETRY_PATH");
    if (!path || !*path || strlen(path)>900) return;
    char stamp[40];mbm_stamp(stamp,sizeof(stamp));
    if (cid==11) snprintf(mb_modem.signal_at,sizeof(mb_modem.signal_at),"%s",stamp);
    if (cid==9) snprintf(mb_modem.registration_at,sizeof(mb_modem.registration_at),"%s",stamp);
    if (cid==2) snprintf(mb_modem.sim_at,sizeof(mb_modem.sim_at),"%s",stamp);
    if (cid==10) snprintf(mb_modem.packet_at,sizeof(mb_modem.packet_at),"%s",stamp);
    if (cid==12) snprintf(mb_modem.activation_at,sizeof(mb_modem.activation_at),"%s",stamp);
    char temporary[1024];snprintf(temporary,sizeof(temporary),"%s.new",path);
    FILE *f=fopen(temporary,"w");
    if (!f) return;
    struct mb_modem_values *v=&mb_modem.values;
    fprintf(f,"{\"engine_pid\":%d,\"sim_state\":%d,\"registration_state\":%d,\"packet_state\":%d,\"activation_state\":%d,\"data_class\":%u,\"rssi\":%d,\"updated_utc\":",
        getpid(),v->sim_state,v->registration_state,v->packet_state,v->activation_state,v->data_class,v->rssi);
    mbm_json_string(f,stamp);
    fputs(",\"provider_name\":",f);mbm_json_string(f,v->provider_name);
    fputs(",\"provider_id\":",f);mbm_json_string(f,v->provider_id);
    fputs(",\"signal_updated_utc\":",f);mbm_json_string(f,mb_modem.signal_at);
    fputs(",\"registration_updated_utc\":",f);mbm_json_string(f,mb_modem.registration_at);
    fputs(",\"sim_updated_utc\":",f);mbm_json_string(f,mb_modem.sim_at);
    fputs(",\"packet_updated_utc\":",f);mbm_json_string(f,mb_modem.packet_at);
    fputs(",\"activation_updated_utc\":",f);mbm_json_string(f,mb_modem.activation_at);
    fprintf(f,",\"transfer_received\":%llu,\"transfer_sent\":%llu",MBM_TRANSFER_RX(),MBM_TRANSFER_TX());
    fputs("}\n",f);
    int bad=ferror(f);
    if (fclose(f)) bad=1;
    if (!bad) { chmod(temporary,0644);rename(temporary,path); }
}
static int mbm_disconnected(int result)
{
    if (result!=LIBUSB_ERROR_NO_DEVICE) return 0;
    mb_log("modem USB disconnected; stop stale handle and await re-enumeration");
    bridge_stop=1;
    return 1;
}
static int mbm_monitor_stalled(void)
{
    double last=mb_modem.last_response>0 ? mb_modem.last_response : mb_modem.started_at;
    return mb_modem.started_at>0 && mbm_now()-last>=75;
}
static void mb_modem_tick(libusb_device_handle *h)
{
    if (!getenv("MAGICBAY_TELEMETRY_PATH") || bridge_stop) return;
    double now=mbm_now();
    if (!mb_modem.started_at) mb_modem.started_at=now;
    if (now-mb_modem.last_export>=1) { mbm_export(0);mb_modem.last_export=now; }
    const char *request_path=getenv("MAGICBAY_SIGNAL_REQUEST_PATH");
    struct stat request;
    if (request_path && stat(request_path,&request)==0 && S_ISREG(request.st_mode)) {
        if (mb_modem.request_seen &&
            (request.st_mtimespec.tv_sec!=mb_modem.request_mtime.tv_sec ||
             request.st_mtimespec.tv_nsec!=mb_modem.request_mtime.tv_nsec) &&
            now-mb_modem.last_request>=2) {
            /* The file has no command payload; touching it requests CID11 only. */
            mb_modem.due[0]=0;
            mb_modem.last_request=now;
        }
        mb_modem.request_mtime=request.st_mtimespec;
        mb_modem.request_seen=1;
    }
    unsigned char notice[64],response[4096];int actual=0;
    /* Do not submit/cancel idle interrupt reads every second. Drain available
     * notifications when a query is pending; indication payloads are handled too. */
    int nr=LIBUSB_ERROR_TIMEOUT;
    if (mb_modem.pending_tid)
        nr=libusb_interrupt_transfer(h,EP_INT,notice,sizeof(notice),&actual,1);
    if (mbm_disconnected(nr)) return;
    /* Firmware occasionally omits notifications. A pending query gets a bounded fallback read. */
    if (nr==0 || (mb_modem.pending_tid && now-mb_modem.sent_at>=0.1)) {
        int n=libusb_control_transfer(h,0xa1,0x01,0,IF_CTRL,response,sizeof(response),250);
        if (mbm_disconnected(n)) return;
        if (n>=12) {
            uint32_t type=le32(response),tid=le32(response+8);
            int matched=mb_modem.pending_tid && tid==mb_modem.pending_tid;
            if (matched || type==0x80000007) {
                unsigned cid=mbm_decode(response,(size_t)n,&mb_modem.values);
                if (cid) { mb_modem.last_response=now;mbm_export(cid); }
                if (matched && (type==0x80000003 || type==0x80000004)) mb_modem.pending_tid=0;
            }
        }
    }
    if (mb_modem.pending_tid && now-mb_modem.sent_at>=3) {
        mb_log("modem query CID=%u timed out; data bridge unchanged",mb_modem.pending_cid);
        mb_modem.pending_tid=0;
    }
    if (mb_modem.pending_tid || bridge_stop) return;
    static const unsigned cids[]={11,9,2,10,12};
    for (unsigned i=0;i<5;i++) {
        if (now<mb_modem.due[i]) continue;
        unsigned char query[84]={0};
        unsigned size=cids[i]==12 ? 84 : 48;
        uint32_t tid=++mb_modem.sequence;
        put32(query,3);put32(query+4,size);put32(query+8,tid);put32(query+12,1);
        memcpy(query+20,basic_uuid,16);put32(query+36,cids[i]);put32(query+40,0);
        put32(query+44,size-48); // CONNECT query's SessionId=0 and other fields stay zero.
        int sent=libusb_control_transfer(h,0x21,0,0,IF_CTRL,query,size,500);
        if (mbm_disconnected(sent)) return;
        mb_modem.due[i]=now+30;
        if (sent==(int)size) {
            mb_modem.pending_tid=tid;mb_modem.pending_cid=cids[i];mb_modem.sent_at=now;
        } else {
            mb_log("modem query CID=%u send failed: %d; data bridge unchanged",cids[i],sent);
        }
        break;
    }
}
