# SPDX-License-Identifier: AGPL-3.0-only
"""Adapt the MIT-licensed Sierra MBIM engine to Lenovo's observed layout."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
base = root / 'build/engine'
base.mkdir(parents=True, exist_ok=True)
source = root / 'third_party/cellular/Sources/mbim_lte.c'
s = source.read_text()

def replace(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:100], s.count(old), count)
    s = s.replace(old, new)

replace('#define VID      0x1199', '#define VID      0x17ef')
replace('#define PID      0x9071', '#define PID      0x7240')
replace('#define IF_CTRL  12', '#define IF_CTRL  0')
replace('#define IF_DATA  13', '#define IF_DATA  1')
replace('#define EP_INT   0x87', '#define EP_INT   0x82')
replace('            0x04,\n            ntb,', '            0x01,\n            ntb,')
replace('            0x86,\n            rx,', '            0x81,\n            rx,')
replace('int main(void)\n{', 'int main(void)\n{\n    setvbuf(stdout, NULL, _IONBF, 0);')
replace('if (++timeouts >= 20)', 'if (++timeouts >= 4)')
# Keep protocol logic in reviewable headers; regenerate without losing fixes.
replace('#include <stdio.h>', '#include <stdio.h>\n#include <stdarg.h>\n#include "magicbay_ntb.h"')
a = s.index('static uint16_t get16le(')
b = s.index('static int create_utun(', a)
s = s[:a] + s[b:]
a = s.index('struct bridge_ctx {')
b = s.index('static const unsigned char internet_context_uuid', a)
s = s[:a] + '#include "magicbay_bridge.h"\n\n' + s[b:]

# Match the probe's control-response polling fallback when a notification is lost.
replace('    if (r != 0)\n        return r;\n\n    memset(resp, 0, max);', '    if (r != 0 && r != LIBUSB_ERROR_TIMEOUT)\n        return r;\n\n    memset(resp, 0, max);')
# A malformed declared length must not reach any CID-specific parser.
replace('        uint32_t rt = le32(resp);', '        uint32_t declared = le32(resp + 4);\n        if (declared < 12 || declared > (uint32_t)r) continue;\n        r = (int)declared;\n        if (le32(resp) == 0x80000003 &&\n            (r < 48 || le32(resp + 44) > (uint32_t)r - 48)) continue;\n        uint32_t rt = le32(resp);')
replace('    if (libusb_init(&ctx) != 0)\n        return 1;', '    if (libusb_init(&ctx) != 0)\n        return 1;\n    libusb_set_log_cb(ctx, mb_usb_log, LIBUSB_LOG_CB_GLOBAL);\n    libusb_set_option(ctx, LIBUSB_OPTION_LOG_LEVEL, LIBUSB_LOG_LEVEL_WARNING);\n    struct mb_limits limits = {0};\n    mb_log("engine start: Lenovo 17ef:7240, libusb %u.%u.%u", libusb_get_version()->major, libusb_get_version()->minor, libusb_get_version()->micro);')
replace('        printf("EM7455 nu a fost gă�sit\\n");\n        return 1;', '        fprintf(stderr, "Lenovo Magic Bay LTE 17ef:7240 not found\\n");\n        libusb_exit(ctx);\n        return 1;')
replace('CLAIM IF12:', 'CLAIM IF0:')
replace('CLAIM IF13:', 'CLAIM IF1:')
# Preserve the previously working alt-setting sequence, but check every result.
replace('    libusb_set_interface_alt_setting(h, IF_DATA, 1);\n    usleep(20000);\n    libusb_set_interface_alt_setting(h, IF_DATA, 0);', '    r = libusb_set_interface_alt_setting(h, IF_DATA, 1);\n    mb_log("IF1 ALT1 initial: %s (%d)", libusb_error_name(r), r);\n    if (r) goto cleanup;\n    usleep(20000);\n    r = libusb_set_interface_alt_setting(h, IF_DATA, 0);\n    mb_log("IF1 ALT0 configure: %s (%d)", libusb_error_name(r), r);\n    if (r) goto cleanup;')
replace('    if (r < 0) goto cleanup;\n\n    usleep(20000);\n    libusb_set_interface_alt_setting(h, IF_DATA, 1);\n    usleep(20000);', '    if (r < 0 || mb_parameters(ntb, (size_t)r, &limits)) {\n        mb_log("invalid/unsupported NTB parameters, returned=%d", r);\n        goto cleanup;\n    }\n    mb_log("NTB16 rx=%u tx=%u NDP=%u payload=%u divisor=%u remainder=%u alignment=%u formats=0x%x",\n           limits.rx_max, limits.tx_max, limits.ndp, limits.payload,\n           mb_u16(ntb+20), mb_u16(ntb+22), mb_u16(ntb+24), limits.formats);\n    /* A device advertising NTB16 only already has the required format. */\n    if (limits.formats & 2) {\n        r = libusb_control_transfer(h, 0x21, 0x84, 0, IF_CTRL, NULL, 0, 3000);\n        mb_log("SET_NTB_FORMAT(16): %d", r);\n        if (r != 0) goto cleanup;\n    }\n    unsigned char input_size[4];\n    mb_p32(input_size, limits.rx_max);\n    r = libusb_control_transfer(h, 0x21, 0x86, 0, IF_CTRL, input_size, 4, 3000);\n    mb_log("SET_NTB_INPUT_SIZE(%u): %d", limits.rx_max, r);\n    if (r != 4) goto cleanup;\n    usleep(20000);\n    r = libusb_set_interface_alt_setting(h, IF_DATA, 1);\n    mb_log("IF1 ALT1 data: %s (%d)", libusb_error_name(r), r);\n    if (r) goto cleanup;\n    usleep(20000);')
a = s.index('                                /*\n                                 * Explicit NTB16 + input buffer.')
b = s.index('                                struct bridge_ctx bc;', a)
s = s[:a] + s[b:]
replace('                                bc.h = h;', '                                bc.h = h;\n                                bc.limits = limits;')
replace('                    if (!mtu)\n                        mtu = 1430;', '                    if (!mtu) mtu = 1430;\n                    unsigned max_mtu = limits.tx_max - limits.payload;\n                    if (max_mtu > MB_IP_MAX) max_mtu = MB_IP_MAX;\n                    if (mtu > max_mtu) mtu = max_mtu;')
# Never erase a stop request received during startup.
replace('                                bridge_stop = 0;', '                                if (bridge_stop) mb_log("stop requested during startup");')
# Handlers are already installed before USB OPEN. Avoid a late goto skipping route/DNS cleanup.
a=s.index('                                if (install_bridge_signal_handlers() != 0) {')
b=s.index('                                int txok = pthread_create(',a)
s=s[:a]+s[b:]
replace('                                    printf("\\nBridge oprit.\\n");', '                                    mb_log("bridge stopped: TX=%llu RX=%llu TX-dropped=%llu RX-invalid=%llu",\n                                           bc.tx_packets, bc.rx_packets, bc.tx_dropped, bc.rx_invalid);\n                                    printf("\\nBridge oprit.\\n");')

# Make cancellation effective during startup while still allowing bounded cleanup.
replace('static volatile sig_atomic_t bridge_stop = 0;','')
replace('#define EP_INT   0x82', '#define EP_INT   0x82\nstatic volatile sig_atomic_t bridge_stop = 0;\nstatic int mb_shutting_down = 0;')
replace('h, EP_INT, intr, sizeof(intr), &got, 3000',
        'h, EP_INT, intr, sizeof(intr), &got, mb_shutting_down ? 500 : 3000')
replace('resp, max, 5000', 'resp, max, mb_shutting_down ? 1000 : 5000')
replace('    for (int i = 0; i < 60; i++) {\n        int r = receive_one', '    for (int i = 0; i < 60; i++) {\n        if (bridge_stop && !mb_shutting_down) return LIBUSB_ERROR_INTERRUPTED;\n        int r = receive_one')
replace('if (++timeouts >= 4)', 'if (++timeouts >= (mb_shutting_down ? 1 : 4))')
replace('    unsigned char q[48];', '    if (bridge_stop) return LIBUSB_ERROR_INTERRUPTED;\n    unsigned char q[48];')
replace('    size_t apn_chars = apn ? strlen(apn) : 0;', '    if (bridge_stop) return 0;\n    size_t apn_chars = apn ? strlen(apn) : 0;')
replace('    for (int attempt = 0; attempt < max_wait_seconds; attempt++) {\n        sleep(1);', '    for (int attempt = 0; attempt < max_wait_seconds && !bridge_stop; attempt++) {\n        sleep(1);\n        if (bridge_stop) break;')
replace('if (bearer_activated) {', 'if (bearer_activated && !bridge_stop) {', count=6)
# Restore the final deactivation branch, which must also execute after stop.
replace('        if (bearer_activated && !bridge_stop) {\n            printf("\\n============================================\\n");\n            printf(" DEACTIVATE SESSION 0\\n");', '        mb_shutting_down = 1;\n        if (bearer_activated) {\n            printf("\\n============================================\\n");\n            printf(" DEACTIVATE SESSION 0\\n");')
replace('    /* CLOSE TID 599 */', '    mb_shutting_down = 1;\n    /* CLOSE TID 599 */')
# Bound IP configuration offsets using subtraction, avoiding integer wraparound.
for offset, size in [('v4off',8), ('gw4off',4), ('gwoff',4), ('dnsoff',4), ('dnsoff',8)]:
    replace(f'{offset} + {size} <= infolen', f'{offset} >= 60 && {offset} <= infolen && {size} <= infolen - {offset}', count=2 if offset=='v4off' else 1)
replace('dns4off + (dns4count * 4) <= infolen',
        'dns4off >= 60 && dns4off <= infolen && dns4count <= (infolen - dns4off) / 4')

# Default APN discovery is attempted first; no region-specific fallback is guessed.
replace('if (!bearer_activated &&\n            strcasecmp(preferred, "broadband") != 0)',
        'if (0 && !bearer_activated &&\n            strcasecmp(preferred, "broadband") != 0)')

# The diagnostic binary routes only its selected test destination over LTE.
old='"/sbin/route -n add -net 0.0.0.0/1 -interface %s && /sbin/route -n add -net 128.0.0.0/1 -interface %s",\n                                ifname, ifname'
new='''
#ifdef MAGICBAY_TEST
                                "/sbin/route -n add -host 223.5.5.5 -interface %s",
                                ifname
#else
                                "/sbin/route -n add -net 0.0.0.0/1 -interface %s && /sbin/route -n add -net 128.0.0.0/1 -interface %s",
                                ifname, ifname
#endif'''
replace(old,new)
old='''SCDynamicStoreRef lte_store =
                                    publish_lte_state(
                                        ifname,
                                        srcs,
                                        gws,
                                        dnss,
                                        dns2s
                                    );'''
new='''SCDynamicStoreRef lte_store = NULL;
#ifndef MAGICBAY_TEST
                                lte_store = publish_lte_state(ifname, srcs, gws, dnss, dns2s);
#endif'''
replace(old,new)
old='''"/sbin/route -n delete -net 0.0.0.0/1 -interface %s >/dev/null 2>&1; "
                                    "/sbin/route -n delete -net 128.0.0.0/1 -interface %s >/dev/null 2>&1",
                                    ifname, ifname'''
new='''
#ifdef MAGICBAY_TEST
                                    "/sbin/route -n delete -host 223.5.5.5 -interface %s >/dev/null 2>&1",
                                    ifname
#else
                                    "/sbin/route -n delete -net 0.0.0.0/1 -interface %s >/dev/null 2>&1; "
                                    "/sbin/route -n delete -net 128.0.0.0/1 -interface %s >/dev/null 2>&1",
                                    ifname, ifname
#endif'''
replace(old,new)
replace('''while (!bridge_stop)
                                        sleep(1);''', '''int active_seconds = 0;
                                    const char *limit_env = getenv("MAGICBAY_DURATION");
                                    int active_limit = limit_env ? atoi(limit_env) : 0;
                                    while (!bridge_stop) {
                                        sleep(1);
                                        if (active_limit > 0 && ++active_seconds >= active_limit)
                                            bridge_stop = 1;
                                    }''')

# A separate managed binary never installs /1 or host routes. The supervisor
# alone promotes its temporary SC service after health checks.
replace('#include "magicbay_bridge.h"', '#include "magicbay_bridge.h"\n#ifdef MAGICBAY_MANAGED\n#include "magicbay_network.h"\n#include "magicbay_modem.h"\n#endif')
replace('#ifdef MAGICBAY_TEST\n                                "/sbin/route -n add',
        '#ifdef MAGICBAY_MANAGED\n                                "%s", "/usr/bin/true"\n#elif defined(MAGICBAY_TEST)\n                                "/sbin/route -n add')
replace('#ifdef MAGICBAY_TEST\n                                    "/sbin/route -n delete',
        '#ifdef MAGICBAY_MANAGED\n                                    "%s", "/usr/bin/true"\n#elif defined(MAGICBAY_TEST)\n                                    "/sbin/route -n delete')
replace('#ifndef MAGICBAY_TEST\n                                lte_store = publish_lte_state(ifname, srcs, gws, dnss, dns2s);\n#endif', '#ifdef MAGICBAY_MANAGED\n                                lte_store = mb_auto_publish(ifname, srcs, gws, dnss, dns2s);\n                                if (!lte_store) bridge_stop = 1;\n#elif !defined(MAGICBAY_TEST)\n                                lte_store = publish_lte_state(ifname, srcs, gws, dnss, dns2s);\n#endif')
replace('                                    cellular_milestone("utun + routes ready");', '                                    cellular_milestone("utun + routes ready");\n#ifdef MAGICBAY_MANAGED\n                                    if (lte_store) printf("MB_AUTO_READY {\\"interface\\":\\"%s\\",\\"ipv4\\":\\"%s\\",\\"gateway\\":\\"%s\\",\\"dns\\":\\"%s\\"}\\n", ifname, srcs, gws, dnss);\n#endif')
replace('                                    while (!bridge_stop) {\n                                        sleep(1);', '                                    while (!bridge_stop) {\n#ifdef MAGICBAY_MANAGED\n                                        if (mb_auto_tick()) bridge_stop = 1;\n                                        if (!bridge_stop) mb_modem_tick(h);\n#endif\n                                        sleep(1);')
replace('                                printf("Rutele LTE eliminate.\\n");', '#ifdef MAGICBAY_MANAGED\n                                mb_auto_release();\n#endif\n                                printf("Rutele LTE eliminate.\\n");')

# Each engine owns fresh transaction IDs; never accept an old OPEN_DONE as new.
for message, tid in [('q','tid'),('con','tid'),('cq','qtid'),('deact','tid'),
                     ('openmsg','500'),('ipq','730'),('bq','741'),('deact','790'),('closemsg','599')]:
    import re
    pattern = r'put32\('+message+r' \+ 8,\s*'+tid+r'\);'
    s, count = re.subn(pattern, 'put32('+message+' + 8, mb_wire_tid('+tid+'));', s)
    assert count == 1, (message,tid,count)
a=s.index('static int wait_for(')
b=s.index('static int send_query(',a)
s=s[:a]+'#include "magicbay_session.h"\n\n'+s[b:]
replace('        printf("MBIM_OPEN NU A REUȃ�IT\\n");\n        goto cleanup;',
        '        mb_log("MBIM OPEN not ready: result=%d status=%u wire_tid=%u", r, r>=16 ? le32(resp+12) : 0xffffffffu, mb_wire_tid(500));\n        goto mb_close_session;')
replace('    mb_shutting_down = 1;\n    /* CLOSE TID 599 */',
        'mb_close_session: ;\n    mb_shutting_down = 1;\n    /* CLOSE TID 599 */')
replace('    cellular_milestone("preflight begin");', '''    /* OPEN success alone does not mean Subscriber Ready has completed. */
    int subscriber_ready=0;
    for (int attempt=0;attempt<12 && !bridge_stop;attempt++) {
        r=send_query(h,2,850+attempt,resp,sizeof(resp));
        if (r>=76 && le32(resp+40)==0 && le32(resp+44)>=28) {
            uint32_t ready=le32(resp+48);
            if (ready==1) { subscriber_ready=1;break; }
            if (ready==2 || ready==3 || ready==6) {
                mb_log("Subscriber cannot connect: ready_state=%u",ready);
                break;
            }
        }
        usleep(500000);
    }
    if (!subscriber_ready) {
        mb_log("Subscriber still initializing; defer data activation");
        goto mb_close_session;
    }
    cellular_milestone("preflight begin");''')

# Control-only standby never enters the activation or bridge path.
replace('static struct timespec cellular_t0;', '#ifdef MAGICBAY_MANAGED\n#include "magicbay_idle.h"\n#endif\n\nstatic struct timespec cellular_t0;')
replace('    cellular_milestone("preflight complete");', '''    cellular_milestone("preflight complete");
#ifdef MAGICBAY_MANAGED
    if (getenv("MAGICBAY_MONITOR_ONLY")) {
        (void)mb_idle_monitor(h);
        goto mb_close_session;
    }
#endif''')
replace('mb_close_session: ;', '''mb_close_session: ;
#ifdef MAGICBAY_MANAGED
    mbm_export(0);
#endif''')

# A monitoring session needs IF0 only. Do not fail module registration on an
# unnecessary IF1 alternate-setting/NTB transaction while firmware is booting.
replace('    int r;\n\n    if (libusb_init(&ctx)', '''    int r;
    int data_claimed=0,control_only=0;
#ifdef MAGICBAY_MANAGED
    control_only=getenv("MAGICBAY_MONITOR_ONLY")!=NULL;
#endif

    if (libusb_init(&ctx)''')
a=s.index('    r = libusb_claim_interface(h, IF_DATA);')
b=s.index('    /* OPEN TID 500 */',a)
data_setup=s[a:b]
assert data_setup.count('    if (r != 0) goto rel12;')==1
data_setup=data_setup.replace('    if (r != 0) goto rel12;',
    '    if (r != 0) goto rel12;\n    data_claimed=1;')
s=s[:a]+'''    if (control_only) {
        mb_log("control-only initialization: IF0 only; IF1 and NTB untouched");
    } else {
'''+data_setup+'    }\n\n'+s[b:]
replace('''cleanup:
    libusb_set_interface_alt_setting(h, IF_DATA, 0);
    libusb_release_interface(h, IF_DATA);''','''cleanup:
    if (data_claimed) {
        libusb_set_interface_alt_setting(h, IF_DATA, 0);
        libusb_release_interface(h, IF_DATA);
    }''')

header = '// Adapted for Lenovo Magic Bay LTE 17ef:7240; upstream MIT license in third_party/cellular/LICENSE.\n'
(base/'magicbay_lte.c').write_text(header+s)
upstream = json.loads((root/'third_party/cellular/UPSTREAM.json').read_text())
assert hashlib.sha256(source.read_bytes()).hexdigest() == upstream['source_sha256'], 'Upstream source changed; review and update its pin.'
commit = upstream['commit']
(base/'engine-source.json').write_text(json.dumps({'upstream_commit':commit,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'adapted_sha256':hashlib.sha256((base/'magicbay_lte.c').read_bytes()).hexdigest()},indent=2))
print('Engine adapted to IF0/IF1, interrupt 82, bulk OUT01/IN81.')
