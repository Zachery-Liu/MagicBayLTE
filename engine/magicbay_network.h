// SPDX-License-Identifier: AGPL-3.0-only
/* Managed engine only. Temporary SC state; no /1 routes or persistent preferences. */
#include <fcntl.h>
#include <sys/stat.h>
#include <spawn.h>
#include <sys/wait.h>
#ifndef MB_AUTO_MARK_EXPENSIVE
static int mb_auto_mark_expensive(const char *ifname)
{
    if (!ifname || strncmp(ifname,"utun",4) || !ifname[4]) return -1;
    for (const char *p=ifname+4;*p;p++) if (*p<'0' || *p>'9') return -1;
    /* Native per-interface cost flag. Never touches Wi-Fi, Clash or the routes. */
    char *args[]={"/sbin/ifconfig",(char *)ifname,"expensive",NULL};
    char *environment[]={"PATH=/usr/bin:/bin:/usr/sbin:/sbin",NULL};
    posix_spawnattr_t attr;
    if (posix_spawnattr_init(&attr)) return -1;
    posix_spawnattr_setflags(&attr,POSIX_SPAWN_CLOEXEC_DEFAULT);
    pid_t pid;
    int r=posix_spawn(&pid,args[0],NULL,&attr,args,environment);
    posix_spawnattr_destroy(&attr);
    if (r) return -1;
    int status;
    while (waitpid(pid,&status,0)<0) if (errno!=EINTR) return -1;
    return WIFEXITED(status) && WEXITSTATUS(status)==0 ? 0 : -1;
}
#define MB_AUTO_MARK_EXPENSIVE mb_auto_mark_expensive
#endif
static struct {
    SCDynamicStoreRef store;
    CFStringRef options_key, proxies_key;
    int fd, active;
} mb_auto = { .fd = -1 };

static int mb_auto_rank(int active)
{
    CFStringRef rank = active ? CFSTR("First") : CFSTR("Scoped");
    const void *keys[] = {CFSTR("PrimaryRank"), CFSTR("UserDefinedName")};
    const void *values[] = {rank, CFSTR("Magic Bay LTE")};
    CFDictionaryRef options = CFDictionaryCreate(NULL, keys, values, 2,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    Boolean ok = SCDynamicStoreSetValue(mb_auto.store, mb_auto.options_key, options);
    CFRelease(options);
    if (!ok) { mb_log("automatic LTE rank update failed: %s", SCErrorString(SCError())); return -1; }
    mb_auto.active = active;
    mb_log("MB_AUTO_STATE %s", active ? "active" : "standby");
    return 0;
}
static int mb_auto_copy_proxies(void)
{
    /* A lost preferred network may remove Global/Proxies before failover.
     * Keep the last observed settings instead of replacing them with nothing. */
    CFPropertyListRef primary = SCDynamicStoreCopyValue(mb_auto.store, CFSTR("State:/Network/Global/IPv4"));
    if (!primary) return 0;
    CFRelease(primary);
    CFPropertyListRef value = SCDynamicStoreCopyValue(mb_auto.store, CFSTR("State:/Network/Global/Proxies"));
    if (!value) return 0;
    if (CFGetTypeID(value) != CFDictionaryGetTypeID()) { CFRelease(value); return -1; }
    CFMutableDictionaryRef proxies = CFDictionaryCreateMutableCopy(NULL, 0, value);
    CFRelease(value);
    /* Global per-interface/resolver expansions do not belong in a service. */
    CFDictionaryRemoveValue(proxies, CFSTR("__SCOPED__"));
    CFDictionaryRemoveValue(proxies, CFSTR("__SERVICES__"));
    CFDictionaryRemoveValue(proxies, CFSTR("__SUPPLEMENTAL__"));
    CFPropertyListRef previous = SCDynamicStoreCopyValue(mb_auto.store, mb_auto.proxies_key);
    Boolean ok = previous && CFEqual(previous, proxies);
    if (!ok) ok = SCDynamicStoreSetValue(mb_auto.store, mb_auto.proxies_key, proxies);
    if (previous) CFRelease(previous);
    CFRelease(proxies);
    return ok ? 0 : -1;
}
static SCDynamicStoreRef mb_auto_publish(const char *ifname, const char *ip,
                                       const char *gateway, const char *dns1, const char *dns2)
{
    const char *fd_text = getenv("MAGICBAY_CONTROL_FD");
    char *end = NULL;
    long fd = fd_text ? strtol(fd_text, &end, 10) : -1;
    struct stat st;
    if (!fd_text || !end || *end || fd < 3 || fd > 1024 ||
        fstat((int)fd, &st) || !S_ISFIFO(st.st_mode) ||
        fcntl((int)fd, F_SETFL, O_NONBLOCK) < 0) {
        mb_log("managed engine requires its supervisor control pipe");
        return NULL;
    }
    mb_auto.fd = (int)fd;
    if (MB_AUTO_MARK_EXPENSIVE(ifname)) {
        mb_log("could not mark LTE interface as expensive; refusing unmanaged cost state");
        return NULL;
    }
    mb_log("LTE interface %s marked EXPENSIVE",ifname);
    SCDynamicStoreRef store = SCDynamicStoreCreate(NULL, CFSTR("Magic Bay LTE automatic"), NULL, NULL);
    if (!store) return NULL;
    mb_auto.store = store;
    CFStringRef service = CFStringCreateWithFormat(NULL, NULL, CFSTR("State:/Network/Service/MagicBay-LTE-%s"), ifname);
    /* configd reads service options from the service ROOT key (entity=NULL).
     * __SERVICE__ is its internal cache name, not a dynamic-store path. */
    mb_auto.options_key = CFRetain(service);
    mb_auto.proxies_key = CFStringCreateWithFormat(NULL, NULL, CFSTR("%@/Proxies"), service);
    CFStringRef ipv4_key = CFStringCreateWithFormat(NULL, NULL, CFSTR("%@/IPv4"), service);
    CFStringRef dns_key = CFStringCreateWithFormat(NULL, NULL, CFSTR("%@/DNS"), service);
    CFStringRef iface = CFStringCreateWithCString(NULL, ifname, kCFStringEncodingUTF8);
    CFStringRef address = CFStringCreateWithCString(NULL, ip, kCFStringEncodingUTF8);
    CFStringRef router = CFStringCreateWithCString(NULL, gateway, kCFStringEncodingUTF8);
    CFStringRef server1 = CFStringCreateWithCString(NULL, dns1, kCFStringEncodingUTF8);
    CFStringRef server2 = CFStringCreateWithCString(NULL, dns2, kCFStringEncodingUTF8);
    const void *one_address[] = {address}, *one_mask[] = {CFSTR("255.255.255.255")};
    const void *servers[] = {server1, server2};
    CFArrayRef addresses = CFArrayCreate(NULL, one_address, 1, &kCFTypeArrayCallBacks);
    CFArrayRef masks = CFArrayCreate(NULL, one_mask, 1, &kCFTypeArrayCallBacks);
    CFArrayRef dns_servers = CFArrayCreate(NULL, servers, strcmp(dns1,dns2) ? 2 : 1, &kCFTypeArrayCallBacks);
    const void *ip_keys[] = {CFSTR("Addresses"), CFSTR("SubnetMasks"), CFSTR("Router"), CFSTR("InterfaceName")};
    const void *ip_values[] = {addresses, masks, router, iface};
    CFDictionaryRef ipv4 = CFDictionaryCreate(NULL, ip_keys, ip_values, 4,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    const void *dns_keys[] = {CFSTR("ServerAddresses")}, *dns_values[] = {dns_servers};
    CFDictionaryRef dns = CFDictionaryCreate(NULL, dns_keys, dns_values, 1,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    const void *rank_keys[] = {CFSTR("PrimaryRank"), CFSTR("UserDefinedName")};
    const void *rank_values[] = {CFSTR("Scoped"), CFSTR("Magic Bay LTE")};
    CFDictionaryRef options = CFDictionaryCreate(NULL, rank_keys, rank_values, 2,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionaryRef empty = CFDictionaryCreate(NULL,NULL,NULL,0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    /* Rank must exist BEFORE IPv4, so startup cannot briefly steal the default. */
    Boolean ok = SCDynamicStoreAddTemporaryValue(store, mb_auto.options_key, options)
        && SCDynamicStoreAddTemporaryValue(store, mb_auto.proxies_key, empty)
        && SCDynamicStoreAddTemporaryValue(store, dns_key, dns)
        && SCDynamicStoreAddTemporaryValue(store, ipv4_key, ipv4);
    CFRelease(empty); CFRelease(options); CFRelease(dns); CFRelease(ipv4);
    CFRelease(dns_servers); CFRelease(masks); CFRelease(addresses);
    CFRelease(server2); CFRelease(server1); CFRelease(router); CFRelease(address); CFRelease(iface);
    CFRelease(dns_key); CFRelease(ipv4_key); CFRelease(service);
    if (!ok) { mb_log("managed SC registration failed: %s", SCErrorString(SCError())); CFRelease(store); mb_auto.store=NULL; return NULL; }
    if (mb_auto_copy_proxies()) { CFRelease(store); mb_auto.store=NULL; return NULL; }
    return store;
}
static int mb_auto_tick(void)
{
    char command;
    ssize_t n;
    while ((n=read(mb_auto.fd,&command,1)) == 1) {
        if (command=='Q') return -1;
        if (command=='P' && !mb_auto.active) {
            if (mb_auto_copy_proxies()) return -1;
        }
        if (command=='A' && !mb_auto.active) {
            /* Preserve the current app proxy settings without editing them. */
            if (mb_auto_copy_proxies() || mb_auto_rank(1)) return -1;
        } else if (command=='S' && mb_auto.active) {
            if (mb_auto_rank(0)) return -1;
        }
    }
    if (n==0) { mb_log("supervisor disconnected; releasing LTE network state"); return -1; }
    return errno==EAGAIN || errno==EWOULDBLOCK || errno==EINTR ? 0 : -1;
}
static void mb_auto_release(void)
{
    if (mb_auto.options_key) CFRelease(mb_auto.options_key);
    if (mb_auto.proxies_key) CFRelease(mb_auto.proxies_key);
    if (mb_auto.fd>=0) close(mb_auto.fd);
    mb_auto.store=NULL; mb_auto.options_key=NULL; mb_auto.proxies_key=NULL; mb_auto.fd=-1;
}
