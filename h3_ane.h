#ifndef H3_ANE_H
#define H3_ANE_H

#include "h3_ane_receipt.h"

#include <stddef.h>
#include <stdint.h>

typedef enum {
    H3_ANE_REASON_NONE,
    H3_ANE_REASON_DISABLED,
    H3_ANE_REASON_OS,
    H3_ANE_REASON_CONTRACT,
    H3_ANE_REASON_FINGERPRINT,
    H3_ANE_REASON_RECEIPT,
    H3_ANE_REASON_ELIGIBILITY,
    H3_ANE_REASON_LOAD,
    H3_ANE_REASON_PREDICTION,
    H3_ANE_REASON_SHAPE,
    H3_ANE_REASON_DTYPE,
    H3_ANE_REASON_NONFINITE
} h3_ane_reason;

enum {
    H3_ANE_DEVICE_CPU = 1u << 0,
    H3_ANE_DEVICE_GPU = 1u << 1,
    H3_ANE_DEVICE_NEURAL_ENGINE = 1u << 2
};

typedef struct {
    char name[96];
    int is_constant;
    uint32_t supported_devices;
    uint32_t preferred_device;
} h3_ane_operation_usage;

typedef struct {
    double load_seconds;
    double input_seconds;
    double prediction_seconds;
    double output_seconds;
    uint64_t attempts;
    uint64_t predictions;
    uint64_t fallbacks;
    h3_ane_reason last_reason;
    uint32_t preferred_device;
    int shadow;
} h3_ane_stats;

typedef struct h3_ane h3_ane;

/*
 * One handle has one owner. Prediction calls on that handle are serialized;
 * h3_ane_free must be called only after all callers have returned.
 */
h3_ane *h3_ane_create(const char *model_path,
                      const h3_ane_contract *contract, int shadow,
                      char *error, size_t error_size);
int h3_ane_is_shadow(const h3_ane *ane);
int h3_ane_predict(h3_ane *ane, const float *input, size_t input_count,
                   float *output, size_t output_count, h3_ane_stats *stats,
                   char *error, size_t error_size);
void h3_ane_free(h3_ane *ane);

#ifdef H3_ANE_TESTING
typedef struct {
    int (*load)(void *);
    int (*plan)(void *, h3_ane_operation_usage *, size_t *);
    int (*predict)(void *, const float *, size_t, float *, size_t);
    void (*free)(void *);
    void *opaque;
} h3_ane_test_backend;

void h3_ane_test_set_backend(const h3_ane_test_backend *backend);
int h3_ane_test_copy_to_strided(float *destination,
                                const ptrdiff_t strides[5],
                                const uint32_t shape[5],
                                const float *source);
int h3_ane_test_copy_from_strided(float *destination,
                                  const float *source,
                                  const ptrdiff_t strides[5],
                                  const uint32_t shape[5]);
#endif

#endif
