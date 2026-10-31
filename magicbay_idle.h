// SPDX-License-Identifier: AGPL-3.0-only
/* Managed control-only standby: no data activation, utun, DNS or IP bridge. */
#ifndef MB_IDLE_READY
#define MB_IDLE_READY() puts("MB_AUTO_MONITOR_READY {\"mode\":\"monitor\",\"activation_state\":3}")
#endif
static int mb_idle_session_state(libusb_device_handle *h,uint32_t tid)
{
    unsigned char query[84]={0},response[4096];
    put32(query,3);put32(query+4,sizeof(query));put32(query+8,mb_wire_tid(tid));put32(query+12,1);
    memcpy(query+20,basic_uuid,16);put32(query+36,12);put32(query+44,36);
    int r=libusb_control_transfer(h,0x21,0,0,IF_CTRL,query,sizeof(query),500);
    if (r!=(int)sizeof(query)) return -1;
    r=wait_for(h,0x80000003,tid,response,sizeof(response));
    if (r<0 || mbm_decode(response,(size_t)r,&mb_modem.values)!=12) return -1;
    mbm_export(12);
    return mb_modem.values.activation_state;
}
static int mb_idle_monitor(libusb_device_handle *h)
{
    const char *text=getenv("MAGICBAY_CONTROL_FD");char *end=NULL;
    long fd=text ? strtol(text,&end,10) : -1;struct stat st;
    if (!text || !end || *end || fd<3 || fd>1024 || fstat((int)fd,&st) ||
        !S_ISFIFO(st.st_mode) || fcntl((int)fd,F_SETFL,O_NONBLOCK)<0) return -1;
    int inactive=0;
    for (unsigned attempt=0;attempt<2 && !bridge_stop;attempt++) {
        if (mb_idle_session_state(h,1700+attempt*3)==3) { inactive=1;break; }
        unsigned char response[4096];
        mbim_deactivate_session0_quiet(h,1701+attempt*3,response,sizeof(response));
        if (mb_idle_session_state(h,1702+attempt*3)==3) { inactive=1;break; }
    }
    if (!inactive) { mb_log("cannot confirm inactive LTE data session; no standby-ready claim");return -1; }
    MB_IDLE_READY();
    while (!bridge_stop) {
        char command;ssize_t n;
        while ((n=read((int)fd,&command,1))==1) if (command=='Q') return 0;
        if (n==0) return 0;
        if (n<0 && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR) return -1;
        mb_modem_tick(h);
        if (mb_modem.values.activation_state>0 && mb_modem.values.activation_state!=3) {
            mb_log("data session unexpectedly active in control-only standby; closing session");return -1;
        }
        usleep(100000);
    }
    return 0;
}
