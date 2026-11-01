// SPDX-License-Identifier: AGPL-3.0-only
/* Included by the generated engine; maintains the Lenovo USB data path. */
struct bridge_ctx {
    libusb_device_handle *h;
    int utun_fd;
    struct mb_limits limits;
    uint16_t sequence;
    unsigned long long tx_packets, rx_packets, tx_dropped, rx_invalid;
};
static unsigned long long mb_transfer_rx,mb_transfer_tx;
#define MBM_TRANSFER_RX() __atomic_load_n(&mb_transfer_rx,__ATOMIC_RELAXED)
#define MBM_TRANSFER_TX() __atomic_load_n(&mb_transfer_tx,__ATOMIC_RELAXED)

static void mb_log(const char *fmt, ...)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME,&ts);
    struct tm tm;
    gmtime_r(&ts.tv_sec,&tm);
    char stamp[32];
    strftime(stamp,sizeof(stamp),"%Y-%m-%dT%H:%M:%S",&tm);
    flockfile(stderr);
    fprintf(stderr,"[%s.%03ldZ] ",stamp,ts.tv_nsec/1000000);
    va_list ap;
    va_start(ap,fmt); vfprintf(stderr,fmt,ap); va_end(ap);
    fputc('\n',stderr);
    funlockfile(stderr);
}
static void LIBUSB_CALL mb_usb_log(libusb_context *ctx, enum libusb_log_level level, const char *str)
{
    (void)ctx; (void)level;
    /* Darwin logs every normal idle timeout at warning level. */
    if (strstr(str,"transfer error: timed out")) return;
    /* A bounded notification read times out by cancelling IF0/interrupt pipe 1.
     * Keep actual transfer errors and all IF1/bulk diagnostics. */
    if (strstr(str,"darwin_abort_transfers") && strstr(str,"interface 0 pipe 1")) return;
    mb_log("libusb native: %s",str);
}
static int mb_recover(struct bridge_ctx *ctx, const char *dir, unsigned char ep,
                      int r, int actual, int requested, unsigned *errors)
{
    if (bridge_stop) return 0;
    mb_log("USB %s error %u/8: %s (%d), ep=0x%02x actual=%d requested=%d",
           dir,++*errors,libusb_error_name(r),r,ep,actual,requested);
    if (*errors>=8 || !(r==LIBUSB_ERROR_IO || r==LIBUSB_ERROR_PIPE ||
                        r==LIBUSB_ERROR_OVERFLOW || r==LIBUSB_ERROR_TIMEOUT)) {
        bridge_stop=1; return 0;
    }
    /* A generic IO error does not establish that the endpoint is stalled. */
    if (r==LIBUSB_ERROR_PIPE) {
        int clear=libusb_clear_halt(ctx->h,ep);
        mb_log("USB %s clear_halt ep=0x%02x: %s (%d)",dir,ep,libusb_error_name(clear),clear);
        if (clear) { bridge_stop=1; return 0; }
    }
    usleep(150000);
    return 1;
}
static void *utun_to_mbim(void *arg)
{
    struct bridge_ctx *ctx=arg;
    unsigned errors=0;
    while (!bridge_stop) {
        struct pollfd pfd={.fd=ctx->utun_fd,.events=POLLIN};
        int pr=poll(&pfd,1,500);
        if (pr<0 && errno==EINTR) continue;
        if (pr<0 || (pr>0 && (pfd.revents&(POLLERR|POLLHUP|POLLNVAL)))) {
            mb_log("utun poll failed: result=%d revents=0x%x errno=%d",pr,pfd.revents,errno);
            bridge_stop=1; break;
        }
        if (!pr || !(pfd.revents&POLLIN)) continue;
        unsigned char frame[4096], ntb[MB_TX_MAX];
        ssize_t n=read(ctx->utun_fd,frame,sizeof(frame));
        if (n<0 && errno==EINTR) continue;
        if (n<0) { mb_log("utun read failed: errno=%d",errno); bridge_stop=1; break; }
        if (n<=4) continue;
        uint32_t af;
        memcpy(&af,frame,4);
        if (ntohl(af)!=AF_INET) continue;
        int length=mb_encode(ntb,sizeof(ntb),&ctx->limits,ctx->sequence++,frame+4,(size_t)n-4);
        if (length<0) { ctx->tx_dropped++; continue; }
        int sent=0;
        int r=libusb_bulk_transfer(ctx->h,0x01,ntb,length,&sent,5000);
        if (r || sent!=length) {
            ctx->tx_dropped++;
            if (!mb_recover(ctx,"TX",0x01,r ? r : LIBUSB_ERROR_IO,sent,length,&errors)) break;
            /* Never resend an NTB that might already be partially on the wire. */
            continue;
        }
        if (errors) mb_log("USB TX recovered after %u errors",errors);
        errors=0;
        ctx->tx_packets++;
        __atomic_fetch_add(&mb_transfer_tx,(unsigned long long)n-4,__ATOMIC_RELAXED);
    }
    return NULL;
}
static int mb_to_utun(void *arg, const unsigned char *ip, size_t len)
{
    struct bridge_ctx *ctx=arg;
    unsigned char packet[MB_IP_MAX+4];
    uint32_t af=htonl(AF_INET);
    memcpy(packet,&af,4); memcpy(packet+4,ip,len);
    ssize_t wr;
    do { wr=write(ctx->utun_fd,packet,len+4); } while (wr<0 && errno==EINTR && !bridge_stop);
    if (wr!=(ssize_t)len+4) {
        mb_log("utun write failed: actual=%zd requested=%zu errno=%d",wr,len+4,errno);
        bridge_stop=1; return -1;
    }
    ctx->rx_packets++;
    __atomic_fetch_add(&mb_transfer_rx,(unsigned long long)len,__ATOMIC_RELAXED);
    return 0;
}
static void *mbim_to_utun(void *arg)
{
    struct bridge_ctx *ctx=arg;
    struct mb_stream stream={0};
    unsigned errors=0;
    while (!bridge_stop) {
        unsigned char rx[MB_RX_MAX];
        int got=0;
        int r=libusb_bulk_transfer(ctx->h,0x81,rx,ctx->limits.rx_max,&got,1000);
        if (bridge_stop) break;
        if (r && r!=LIBUSB_ERROR_TIMEOUT) {
            stream.used=0;
            if (!mb_recover(ctx,"RX",0x81,r,got,ctx->limits.rx_max,&errors)) break;
            continue;
        }
        if (got<0 || (unsigned)got>ctx->limits.rx_max) {
            mb_log("USB RX invalid actual=%d",got); bridge_stop=1; break;
        }
        /* An empty idle timeout is neither a recovery nor another IO error. */
        if (!got) continue;
        if (errors) mb_log("USB RX received data after %u errors",errors);
        errors=0;
        int decoded=mb_feed(&stream,rx,(size_t)got,ctx->limits.rx_max,mb_to_utun,ctx);
        if (decoded==-2) break;
        if (decoded) {
            ctx->rx_invalid++;
            if (ctx->rx_invalid<=5 || !(ctx->rx_invalid%100))
                mb_log("USB RX rejected malformed NTB: actual=%d timeout=%d rejected=%llu",
                       got,r==LIBUSB_ERROR_TIMEOUT,ctx->rx_invalid);
        }
    }
    return NULL;
}
