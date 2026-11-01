// SPDX-License-Identifier: AGPL-3.0-only
/* Read-only SystemConfiguration notifications. Never changes network settings. */
#include <SystemConfiguration/SystemConfiguration.h>
#include <IOKit/IOKitLib.h>
#include <dispatch/dispatch.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int self_test;
static CFStringRef test_key;
static unsigned modem_count;

/* Match the same compatibility service that libusb opens, not a serial number.
 * The parent observes these events without claiming USB or issuing MBIM commands. */
static CFMutableDictionaryRef modem_match(void)
{
    CFMutableDictionaryRef match=IOServiceMatching("IOUSBDevice");
    if (!match) return NULL;
    CFMutableDictionaryRef properties=CFDictionaryCreateMutable(NULL,0,
        &kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    int vid=0x17ef,pid=0x7240;
    CFNumberRef vendor=CFNumberCreate(NULL,kCFNumberIntType,&vid);
    CFNumberRef product=CFNumberCreate(NULL,kCFNumberIntType,&pid);
    CFDictionarySetValue(properties,CFSTR("idVendor"),vendor);
    CFDictionarySetValue(properties,CFSTR("idProduct"),product);
    CFDictionarySetValue(match,CFSTR(kIOPropertyMatchKey),properties);
    CFRelease(vendor);CFRelease(product);CFRelease(properties);
    return match;
}

static void modem_changed(void *context,io_iterator_t iterator)
{
    int added=context!=NULL,changed=0;
    io_service_t device;
    while ((device=IOIteratorNext(iterator))) {
        IOObjectRelease(device);
        if (added) modem_count++;
        else if (modem_count) modem_count--;
        changed=1;
    }
    /* Emit even if rapid re-enumeration leaves final presence unchanged: the
     * old libusb handle is still invalid and the supervisor must replace it. */
    if (changed) puts(modem_count ? "MODEM_PRESENT" : "MODEM_ABSENT");
}

static void watch_modem(void)
{
    IONotificationPortRef port=IONotificationPortCreate(kIOMainPortDefault);
    if (!port) return;
    IONotificationPortSetDispatchQueue(port,dispatch_get_main_queue());
    io_iterator_t removed=IO_OBJECT_NULL,added=IO_OBJECT_NULL;
    CFMutableDictionaryRef match=modem_match();
    if (!match || IOServiceAddMatchingNotification(port,kIOTerminatedNotification,
            match,modem_changed,NULL,&removed)!=KERN_SUCCESS) goto failed;
    /* Initial termination enumeration is only priming, never a removal. */
    io_service_t device;
    while ((device=IOIteratorNext(removed))) IOObjectRelease(device);
    match=modem_match();
    if (!match || IOServiceAddMatchingNotification(port,kIOFirstMatchNotification,
            match,modem_changed,(void *)1,&added)!=KERN_SUCCESS) goto failed;
    modem_changed((void *)1,added);
    if (!modem_count) puts("MODEM_ABSENT");
    return; /* Port and iterators live until this parent-owned process exits. */
failed:
    if (removed) IOObjectRelease(removed);
    if (added) IOObjectRelease(added);
    IONotificationPortDestroy(port);
    puts("MODEM_OBSERVER_UNAVAILABLE");
}

static void changed(SCDynamicStoreRef store, CFArrayRef keys, void *context)
{
    (void)store;(void)context;
    if (!keys || !CFArrayGetCount(keys)) return;
    puts("NETWORK_CHANGE");fflush(stdout);
    if (self_test) {
        puts("PASS: private notification delivered; no interface or route changed");
        exit(0);
    }
}

int main(int argc,char **argv)
{
    setvbuf(stdout,NULL,_IONBF,0);
    self_test=argc==2 && !strcmp(argv[1],"--self-test");
    if (argc!=1 && !self_test) return 2;
    SCDynamicStoreRef store=SCDynamicStoreCreate(NULL,CFSTR("Magic Bay LTE network observer"),changed,NULL);
    if (!store) return 1;
    /* Physical interfaces only: LTE/Clash utun updates must not trigger a loop. */
    const void *patterns[]={
        CFSTR("^State:/Network/Interface/en[0-9]+/(IPv4|IPv6|Link|AirPort)$"),
        CFSTR("^Setup:/Network/Service/[^/]+/(IPv4|IPv6|Interface)$"),
        CFSTR("^Setup:/Network/Global/IPv4$")
    };
    CFArrayRef watched=CFArrayCreate(NULL,patterns,3,&kCFTypeArrayCallBacks);
    CFArrayRef exact=NULL;
    if (self_test) {
        test_key=CFStringCreateWithFormat(NULL,NULL,CFSTR("State:/MagicBayLTE/ObserverSelfTest/%d"),getpid());
        const void *items[]={test_key};
        exact=CFArrayCreate(NULL,items,1,&kCFTypeArrayCallBacks);
    }
    Boolean ok=SCDynamicStoreSetNotificationKeys(store,exact,self_test ? NULL : watched);
    if (exact) CFRelease(exact);
    CFRelease(watched);
    if (!ok || !SCDynamicStoreSetDispatchQueue(store,dispatch_get_main_queue())) {
        CFRelease(store);return 1;
    }
    puts("NETWORK_READY");
    if (self_test) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,200*NSEC_PER_MSEC),dispatch_get_main_queue(),^{
            if (!SCDynamicStoreNotifyValue(store,test_key)) {
                fprintf(stderr,"private notification failed: %s\n",SCErrorString(SCError()));
                exit(3);
            }
        });
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,3*NSEC_PER_SEC),dispatch_get_main_queue(),^{exit(4);});
    } else {
        watch_modem();
        /* Parent owns the write end. EOF guarantees observer exits with supervisor. */
        if (fcntl(STDIN_FILENO,F_SETFL,O_NONBLOCK)<0) return 1;
        dispatch_source_t parent=dispatch_source_create(DISPATCH_SOURCE_TYPE_READ,STDIN_FILENO,0,dispatch_get_main_queue());
        if (!parent) return 1;
        dispatch_source_set_event_handler(parent,^{
            char byte;
            if (read(STDIN_FILENO,&byte,1)==0) exit(0);
        });
        dispatch_resume(parent);
    }
    dispatch_main();
}
