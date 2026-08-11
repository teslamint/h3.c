#ifndef H3_ANE_DISPATCH_H
#define H3_ANE_DISPATCH_H

#include "h3_ane.h"
#include "h3_gpu.h"

#include <stddef.h>

typedef h3_gpu_tensor *(*h3_ane_metal_block_fn)(
    void *opaque, h3_gpu_tensor *original_input,
    char *error, size_t error_size);

h3_gpu_tensor *h3_ane_dispatch_gpu_block(
    h3_ane *ane, h3_gpu *gpu, h3_gpu_tensor *original_input, size_t count,
    h3_ane_metal_block_fn metal, void *metal_opaque, h3_ane_stats *stats,
    char *error, size_t error_size);

#ifdef H3_ANE_TESTING
void h3_ane_dispatch_test_fail_allocation(int enabled);
void h3_ane_dispatch_test_fail_host_read(int enabled);
void h3_ane_dispatch_test_fail_replacement_allocation(int enabled);
#endif

#endif
