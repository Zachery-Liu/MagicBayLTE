// SPDX-License-Identifier: AGPL-3.0-only
/* Real CoreFoundation dictionaries, fake configd store. Never changes networking. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <unistd.h>
#include <errno.h>
#include <assert.h>
#include <CoreFoundation/CoreFoundation.h>
#include <SystemConfiguration/SystemConfiguration.h>
static CFMutableDictionaryRef fake_store;
static int fail_update;
static int preferred_missing;
static int expensive_marks,fail_cost;
static int fake_cost(const char *name) {
    assert(!strcmp(name,"utun99"));expensive_marks++;
    return fail_cost ? -1 : 0;
}
#define MB_AUTO_MARK_EXPENSIVE fake_cost
static void mb_log(const char *fmt, ...) { (void)fmt; }
static SCDynamicStoreRef fake_create(CFAllocatorRef a, CFStringRef n, SCDynamicStoreCallBack cb, SCDynamicStoreContext *c)
{
    (void)a;(void)n;(void)cb;(void)c;
    fake_store=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    return (SCDynamicStoreRef)fake_store;
}
static Boolean fake_set(SCDynamicStoreRef s, CFStringRef k, CFPropertyListRef v)
{
    if (fail_update) return FALSE;
    CFDictionarySetValue((CFMutableDictionaryRef)s,k,v);
    return TRUE;
}
static Boolean fake_add(SCDynamicStoreRef s, CFStringRef k, CFPropertyListRef v)
{
    if (CFStringHasSuffix(k,CFSTR("/IPv4"))) {
        assert(expensive_marks>0);
        CFDictionaryRef options=CFDictionaryGetValue((CFDictionaryRef)s,
            CFSTR("State:/Network/Service/MagicBay-LTE-utun99"));
        assert(options && CFEqual(CFDictionaryGetValue(options,CFSTR("PrimaryRank")),CFSTR("Scoped")));
    }
    return fake_set(s,k,v);
}
static CFPropertyListRef fake_copy(SCDynamicStoreRef s, CFStringRef k)
{
    if (CFEqual(k,CFSTR("State:/Network/Global/IPv4"))) {
        if (preferred_missing) return NULL;
        return CFDictionaryCreate(NULL,NULL,NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    }
    if (CFEqual(k,CFSTR("State:/Network/Global/Proxies"))) {
        const void *keys[]={CFSTR("HTTPSEnable"),CFSTR("HTTPSProxy"),CFSTR("__SCOPED__")};
        int one=1;
        CFNumberRef enabled=CFNumberCreate(NULL,kCFNumberIntType,&one);
        const void *values[]={enabled,CFSTR("127.0.0.1"),CFSTR("global expansion")};
        CFDictionaryRef p=CFDictionaryCreate(NULL,keys,values,3,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
        CFRelease(enabled);
        return p;
    }
    CFPropertyListRef v=CFDictionaryGetValue((CFDictionaryRef)s,k);
    return v ? CFRetain(v) : NULL;
}
#define SCDynamicStoreCreate fake_create
#define SCDynamicStoreAddTemporaryValue fake_add
#define SCDynamicStoreSetValue fake_set
#define SCDynamicStoreCopyValue fake_copy
#include "../engine/magicbay_network.h"
int main(void)
{
    unsetenv("MAGICBAY_CONTROL_FD");
    assert(!mb_auto_publish("utun99","10.0.0.2","10.0.0.1","223.5.5.5","119.29.29.29"));
    int fds[2];assert(pipe(fds)==0);
    char text[32];snprintf(text,sizeof(text),"%d",fds[0]);setenv("MAGICBAY_CONTROL_FD",text,1);
    fail_cost=1;
    assert(!mb_auto_publish("utun99","10.0.0.2","10.0.0.1","223.5.5.5","119.29.29.29"));
    fail_cost=0;
    SCDynamicStoreRef store=mb_auto_publish("utun99","10.0.0.2","10.0.0.1","223.5.5.5","119.29.29.29");
    assert(store && !mb_auto.active && mb_auto_tick()==0);
    CFStringRef expected=SCDynamicStoreKeyCreateNetworkServiceEntity(NULL,
        kSCDynamicStoreDomainState,CFSTR("MagicBay-LTE-utun99"),NULL);
    assert(CFEqual(expected,mb_auto.options_key));CFRelease(expected);
    assert(write(fds[1],"A",1)==1 && mb_auto_tick()==0 && mb_auto.active);
    CFDictionaryRef options=CFDictionaryGetValue(fake_store,mb_auto.options_key);
    assert(CFEqual(CFDictionaryGetValue(options,CFSTR("PrimaryRank")),CFSTR("First")));
    CFDictionaryRef proxies=CFDictionaryGetValue(fake_store,mb_auto.proxies_key);
    assert(CFEqual(CFDictionaryGetValue(proxies,CFSTR("HTTPSProxy")),CFSTR("127.0.0.1")));
    assert(!CFDictionaryContainsKey(proxies,CFSTR("__SCOPED__")));
    assert(write(fds[1],"S",1)==1 && mb_auto_tick()==0 && !mb_auto.active);
    preferred_missing=1;
    assert(write(fds[1],"A",1)==1 && mb_auto_tick()==0 && mb_auto.active);
    proxies=CFDictionaryGetValue(fake_store,mb_auto.proxies_key);
    assert(CFEqual(CFDictionaryGetValue(proxies,CFSTR("HTTPSProxy")),CFSTR("127.0.0.1")));
    assert(write(fds[1],"S",1)==1 && mb_auto_tick()==0 && !mb_auto.active);
    preferred_missing=0;
    fail_update=1;
    assert(write(fds[1],"A",1)==1 && mb_auto_tick()==-1 && !mb_auto.active);
    fail_update=0;
    close(fds[1]);assert(mb_auto_tick()==-1);
    CFRelease(store);mb_auto_release();
    puts("PASS: standby rank precedes IPv4; promotion/demotion; proxy preservation; supervisor EOF and failed update cleanup");
    return 0;
}
