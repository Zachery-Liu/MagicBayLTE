// SPDX-License-Identifier: AGPL-3.0-only
/* Read-only SystemConfiguration notifications. Never changes network settings. */
#include <SystemConfiguration/SystemConfiguration.h>
#include <dispatch/dispatch.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int self_test;
static CFStringRef test_key;

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
