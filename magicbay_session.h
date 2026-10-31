// SPDX-License-Identifier: AGPL-3.0-only
/* Startup transactions must not accept delayed replies from an older process. */
#ifndef MAGICBAY_SESSION_H
#define MAGICBAY_SESSION_H
static uint32_t mb_session_base;
static uint32_t mb_wire_tid(uint32_t logical)
{
    if (!mb_session_base) mb_session_base=0x10000000u+(arc4random() & 0x6ffffc00u);
    return mb_session_base+logical;
}
static int wait_for(libusb_device_handle *h,
                    uint32_t type, uint32_t tid,
                    unsigned char *resp, int max)
{
    tid = mb_wire_tid(tid);
    int timeouts = 0, stalls = 0;

    for (int i = 0; i < 60; i++) {
        if (bridge_stop && !mb_shutting_down) return LIBUSB_ERROR_INTERRUPTED;
        int r = receive_one(h, resp, max);

        /* During OPEN a temporarily stalled control read can precede readiness.
         * Retry the read only: do not send duplicate OPENs or reset the device. */
        if (type==0x80000001 && r==LIBUSB_ERROR_PIPE && stalls++<3) {
            usleep(250000);
            continue;
        }
        if (r == LIBUSB_ERROR_TIMEOUT) {
            if (++timeouts >= (mb_shutting_down ? 1 : 4))
                return r;
            continue;
        }

        if (r < 0)
            return r;

        if (r < 12)
            continue;

        uint32_t declared = le32(resp + 4);
        if (declared < 12 || declared > (uint32_t)r) continue;
        r = (int)declared;
        if (le32(resp) == 0x80000003 &&
            (r < 48 || le32(resp + 44) > (uint32_t)r - 48)) continue;
        uint32_t rt = le32(resp);
        uint32_t id = le32(resp + 8);

        if (id == tid && rt == 0x80000004) {
            printf("FUNCTION_ERROR TID=%u cod=%u\n",
                   tid, r >= 16 ? le32(resp + 12) : 0);
            return -100;
        }

        if (rt == type && id == tid)
            return r;
    }

    return -101;
}

#endif
