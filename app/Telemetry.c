// SPDX-License-Identifier: AGPL-3.0-only
#include "Telemetry.h"
#include <sys/types.h>
#include <sys/sysctl.h>
#include <sys/socket.h>
#include <net/if.h>
#include <net/route.h>
#include <stdlib.h>
#include <IOKit/IOKitLib.h>
#include <CoreFoundation/CoreFoundation.h>
#include <sys/un.h>
#include <unistd.h>
#include <string.h>

/* Three fixed requests to the root-owned helper. No shell or password handling. */
static int mb_helper_command(char command)
{
    if (command!='E' && command!='D' && command!='R') return -1;
    int fd=socket(AF_UNIX,SOCK_STREAM,0);
    if (fd<0) return -1;
    struct timeval timeout={3,0};
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
    setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    int no_sigpipe=1;
    setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&no_sigpipe,sizeof(no_sigpipe));
    struct sockaddr_un address={0};
    address.sun_family=AF_UNIX;
    strlcpy(address.sun_path,"/Library/Application Support/MagicBayLTE/control.sock",sizeof(address.sun_path));
    address.sun_len=sizeof(address);
    uid_t uid;gid_t gid;
    int result=-1;
    if (!connect(fd,(struct sockaddr *)&address,sizeof(address)) &&
        !getpeereid(fd,&uid,&gid) && uid==0) {
        const char request[2]={command,'\n'};
        if (write(fd,request,2)==2) {
            char reply[4]={0};size_t received=0;
            while (received<3) {
                ssize_t count=read(fd,reply+received,3-received);
                if (count<=0) break;
                received+=(size_t)count;
            }
            if (received==3 && !memcmp(reply,"OK\n",3)) result=0;
        }
    }
    close(fd);
    return result;
}

int mb_set_enabled(int enabled) { return mb_helper_command(enabled ? 'E' : 'D'); }
int mb_reconnect(void) { return mb_helper_command('R'); }

/* Read-only 64-bit interface counters; no USB access, packets or route writes. */
int mb_interface_counters(const char *name, uint64_t *received, uint64_t *sent)
{
    unsigned index = if_nametoindex(name);
    if (!index) return -1;
    int mib[] = {CTL_NET, PF_ROUTE, 0, 0, NET_RT_IFLIST2, 0};
    size_t size = 0;
    if (sysctl(mib,6,NULL,&size,NULL,0)) return -1;
    char *buffer = malloc(size);
    if (!buffer) return -1;
    if (sysctl(mib,6,buffer,&size,NULL,0)) { free(buffer); return -1; }
    int result = -1;
    for (char *p=buffer; p+sizeof(struct if_msghdr)<=buffer+size;) {
        struct if_msghdr *header=(struct if_msghdr *)p;
        if (!header->ifm_msglen || p+header->ifm_msglen>buffer+size) break;
        if (header->ifm_type==RTM_IFINFO2 && header->ifm_msglen>=sizeof(struct if_msghdr2)) {
            struct if_msghdr2 *info=(struct if_msghdr2 *)p;
            if (info->ifm_index==index) {
                *received=info->ifm_data.ifi_ibytes;
                *sent=info->ifm_data.ifi_obytes;
                result=0;
                break;
            }
        }
        p+=header->ifm_msglen;
    }
    free(buffer);
    return result;
}

int mb_module_present(void)
{
    io_iterator_t iterator=IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching("IOUSBHostDevice"),&iterator)!=KERN_SUCCESS)
        return -1;
    io_service_t device;
    int found=0;
    while ((device=IOIteratorNext(iterator))) {
        CFTypeRef vendor=IORegistryEntryCreateCFProperty(device,CFSTR("idVendor"),kCFAllocatorDefault,0);
        CFTypeRef product=IORegistryEntryCreateCFProperty(device,CFSTR("idProduct"),kCFAllocatorDefault,0);
        int vid=0,pid=0;
        if (vendor && CFGetTypeID(vendor)==CFNumberGetTypeID()) CFNumberGetValue(vendor,kCFNumberIntType,&vid);
        if (product && CFGetTypeID(product)==CFNumberGetTypeID()) CFNumberGetValue(product,kCFNumberIntType,&pid);
        if (vendor) CFRelease(vendor);
        if (product) CFRelease(product);
        IOObjectRelease(device);
        if (vid==0x17ef && pid==0x7240) { found=1;break; }
    }
    IOObjectRelease(iterator);
    return found;
}
