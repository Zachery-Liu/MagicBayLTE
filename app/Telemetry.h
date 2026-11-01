// SPDX-License-Identifier: AGPL-3.0-only
#include <stdint.h>
int mb_interface_counters(const char *name, uint64_t *received, uint64_t *sent);
int mb_module_present(void);
int mb_set_enabled(int enabled);
int mb_reconnect(void);
