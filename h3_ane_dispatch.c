#include "h3_ane_dispatch.h"

#include <stdio.h>
#include <stdlib.h>

static const size_t h3_ane_block_elements =
    (size_t)1 * 1 * 256 * 256 * 128;

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
        current.last_reason = H3_ANE_REASON_DISABLED;
        current.fallbacks = 1;
        if (stats) *stats = current;
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }
    if (!gpu || !original_input || count != h3_ane_block_elements) {
        current.last_reason = H3_ANE_REASON_SHAPE;
        current.fallbacks = 1;
        current.shadow = h3_ane_is_shadow(ane);
        if (stats) *stats = current;
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }
    if (h3_gpu_tensor_elements(original_input) != count) {
        current.last_reason = H3_ANE_REASON_SHAPE;
        current.fallbacks = 1;
        current.shadow = h3_ane_is_shadow(ane);
        if (stats) *stats = current;
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }
    if (h3_gpu_tensor_dtype(original_input) != H3_GPU_F32) {
        current.last_reason = H3_ANE_REASON_DTYPE;
        current.fallbacks = 1;
        current.shadow = h3_ane_is_shadow(ane);
        if (stats) *stats = current;
        return run_metal(metal, metal_opaque, original_input, error, error_size);
    }

    float *input = malloc(count * sizeof(*input));
    float *output = malloc(count * sizeof(*output));
    char ane_error[256] = {0};
    int read = input && output &&
               h3_gpu_tensor_read_f32(original_input, input, count);
    int predicted = read &&
        h3_ane_predict(ane, input, count, output, count, &current,
                       ane_error, sizeof(ane_error));
    if (!read) {
        current.last_reason = H3_ANE_REASON_PREDICTION;
        current.fallbacks++;
    }
    free(input);

    if (predicted && !h3_ane_is_shadow(ane)) {
        h3_gpu_tensor *replacement =
            h3_gpu_tensor_from_f32(gpu, output, count);
        free(output);
        if (replacement) {
            if (stats) *stats = current;
            set_error(error, error_size, "");
            return replacement;
        }
        current.last_reason = H3_ANE_REASON_PREDICTION;
        current.fallbacks++;
    } else {
        free(output);
    }

    if (stats) *stats = current;
    return run_metal(metal, metal_opaque, original_input, error, error_size);
}
