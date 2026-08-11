#include "h3_ane_dispatch.h"
#include "h3_ane_internal.h"

#include <stdio.h>
#include <stdlib.h>

static const size_t h3_ane_block_elements =
    (size_t)1 * 1 * 256 * 256 * 128;

#ifdef H3_ANE_TESTING
static int fail_allocation;
static int fail_host_read;
static int fail_replacement_allocation;

void h3_ane_dispatch_test_fail_allocation(int enabled) {
    fail_allocation = enabled;
}

void h3_ane_dispatch_test_fail_host_read(int enabled) {
    fail_host_read = enabled;
}

void h3_ane_dispatch_test_fail_replacement_allocation(int enabled) {
    fail_replacement_allocation = enabled;
}
#endif

static void set_error(char *error, size_t error_size, const char *message) {
    if (error && error_size)
        snprintf(error, error_size, "%s", message ? message : "ANE failure");
}

static h3_gpu_tensor *run_metal(h3_ane_metal_block_fn metal,
                                void *metal_opaque,
                                h3_gpu_tensor *original_input,
                                char *error, size_t error_size) {
    if (!metal) {
        set_error(error, error_size, "Metal fallback callback is null");
        return NULL;
    }
    return metal(metal_opaque, original_input, error, error_size);
}

h3_gpu_tensor *h3_ane_dispatch_gpu_block(
    h3_ane *ane, h3_gpu *gpu, h3_gpu_tensor *original_input, size_t count,
    h3_ane_metal_block_fn metal, void *metal_opaque, h3_ane_stats *stats,
    char *error, size_t error_size) {
    h3_ane_stats current = {0};
    if (!ane) {
        h3_ane_record_fallback(NULL, H3_ANE_REASON_DISABLED, stats);
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }
    if (!gpu || !original_input || count != h3_ane_block_elements) {
        h3_ane_record_fallback(ane, H3_ANE_REASON_SHAPE, stats);
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }
    if (h3_gpu_tensor_elements(original_input) != count) {
        h3_ane_record_fallback(ane, H3_ANE_REASON_SHAPE, stats);
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }
    if (h3_gpu_tensor_dtype(original_input) != H3_GPU_F32) {
        h3_ane_record_fallback(ane, H3_ANE_REASON_DTYPE, stats);
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }

    int inject_allocation = 0, inject_read = 0, inject_replacement = 0;
#ifdef H3_ANE_TESTING
    inject_allocation = fail_allocation;
    fail_allocation = 0;
    inject_read = fail_host_read;
    fail_host_read = 0;
    inject_replacement = fail_replacement_allocation;
    fail_replacement_allocation = 0;
#endif
    float *input = inject_allocation ? NULL : malloc(count * sizeof(*input));
    float *output = inject_allocation ? NULL : malloc(count * sizeof(*output));
    char ane_error[256] = {0};
    int read = !inject_read && input && output &&
               h3_gpu_tensor_read_f32(original_input, input, count);
    int predicted = read &&
        h3_ane_predict(ane, input, count, output, count, &current,
                       ane_error, sizeof(ane_error));
    if (!read) {
        h3_ane_record_fallback(ane, H3_ANE_REASON_PREDICTION, &current);
    }
    free(input);

    if (predicted && !h3_ane_is_shadow(ane)) {
        h3_gpu_tensor *replacement = inject_replacement ? NULL :
            h3_gpu_tensor_from_f32(gpu, output, count);
        free(output);
        if (replacement) {
            if (stats) *stats = current;
            set_error(error, error_size, "");
            return replacement;
        }
        h3_ane_record_current_attempt_fallback(
            ane, H3_ANE_REASON_PREDICTION, &current);
    } else {
        free(output);
    }

    if (stats) *stats = current;
    return run_metal(metal, metal_opaque, original_input, error, error_size);
}
