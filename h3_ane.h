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

typedef enum {
    H3_ANE_STAGE_NONE, H3_ANE_STAGE_SETUP, H3_ANE_STAGE_ARTIFACT,
    H3_ANE_STAGE_CONTRACT, H3_ANE_STAGE_RECEIPT, H3_ANE_STAGE_LOAD,
    H3_ANE_STAGE_COMPUTE_PLAN, H3_ANE_STAGE_ELIGIBILITY,
    H3_ANE_STAGE_INPUT, H3_ANE_STAGE_PREDICTION, H3_ANE_STAGE_OUTPUT,
    H3_ANE_STAGE_PARITY, H3_ANE_STAGE_PUBLICATION
} h3_ane_stage;

typedef enum {
    H3_ANE_CODE_NONE, H3_ANE_CODE_DISABLED, H3_ANE_CODE_OS_UNSUPPORTED,
    H3_ANE_CODE_ALLOCATION_FAILED, H3_ANE_CODE_COMPILED_MODEL_UNREADABLE,
    H3_ANE_CODE_COMPILED_MODEL_DIGEST_FAILED,
    H3_ANE_CODE_SOURCE_WEIGHTS_UNREADABLE,
    H3_ANE_CODE_SOURCE_TENSOR_DIGEST_FAILED, H3_ANE_CODE_METADATA_MISSING,
    H3_ANE_CODE_METADATA_MISMATCH, H3_ANE_CODE_FINGERPRINT_MISMATCH,
    H3_ANE_CODE_SHAPE_MISMATCH, H3_ANE_CODE_DTYPE_MISMATCH,
    H3_ANE_CODE_RECEIPT_MISSING, H3_ANE_CODE_RECEIPT_MALFORMED,
    H3_ANE_CODE_RECEIPT_DIGEST_MISMATCH, H3_ANE_CODE_RECEIPT_INVALID,
    H3_ANE_CODE_MODEL_LOAD_FAILED, H3_ANE_CODE_MODEL_LOAD_EXCEPTION,
    H3_ANE_CODE_PLAN_TIMEOUT, H3_ANE_CODE_PLAN_LOAD_FAILED,
    H3_ANE_CODE_PROGRAM_MISSING, H3_ANE_CODE_MAIN_MISSING,
    H3_ANE_CODE_OPERATION_INVENTORY_EMPTY,
    H3_ANE_CODE_OPERATION_INVENTORY_LIMIT_EXCEEDED,
    H3_ANE_CODE_OPERATION_NESTING_LIMIT_EXCEEDED,
    H3_ANE_CODE_OPERATION_INVENTORY_CHANGED,
    H3_ANE_CODE_OPERATION_USAGE_UNKNOWN,
    H3_ANE_CODE_OPERATION_NOT_NEURAL_ENGINE_SUPPORTED,
    H3_ANE_CODE_DEVICE_UNKNOWN, H3_ANE_CODE_INPUT_SHAPE_MISMATCH,
    H3_ANE_CODE_INPUT_DTYPE_MISMATCH, H3_ANE_CODE_INPUT_COPY_FAILED,
    H3_ANE_CODE_PREDICTION_FAILED, H3_ANE_CODE_PREDICTION_EXCEPTION,
    H3_ANE_CODE_OUTPUT_SHAPE_MISMATCH, H3_ANE_CODE_OUTPUT_DTYPE_MISMATCH,
    H3_ANE_CODE_OUTPUT_COPY_FAILED, H3_ANE_CODE_OUTPUT_NONFINITE,
    H3_ANE_CODE_PARITY_METRICS_NONFINITE, H3_ANE_CODE_PARITY_BOUNDS_FAILED,
    H3_ANE_CODE_RESULT_WRITE_FAILED, H3_ANE_CODE_RECEIPT_WRITE_FAILED
} h3_ane_code;

typedef enum {
    H3_ANE_ARTIFACT_NONE, H3_ANE_ARTIFACT_COMPILED_MODEL,
    H3_ANE_ARTIFACT_SOURCE_WEIGHTS
} h3_ane_artifact_role;

typedef enum {
    H3_ANE_CONTRACT_FIELD_NONE, H3_ANE_CONTRACT_FIELD_VERSION,
    H3_ANE_CONTRACT_FIELD_VARIANT, H3_ANE_CONTRACT_FIELD_BLOCK_LEVEL,
    H3_ANE_CONTRACT_FIELD_BLOCK_INDEX, H3_ANE_CONTRACT_FIELD_WEIGHT_PREFIX,
    H3_ANE_CONTRACT_FIELD_BOUNDARY_DTYPE, H3_ANE_CONTRACT_FIELD_SHAPE,
    H3_ANE_CONTRACT_FIELD_SOURCE_SHA256
} h3_ane_contract_field;

typedef struct {
    h3_ane_stage stage;
    h3_ane_code code;
    h3_ane_reason reason;
    char message[160];
    char operation[96];
    h3_ane_artifact_role artifact_role;
    h3_ane_contract_field contract_field;
    char digest[65];
    uint32_t supported_devices;
    uint32_t preferred_device;
    uint64_t observed_count;
    uint64_t limit;
    double max_abs;
    double relative_l2;
    unsigned has_operation:1;
    unsigned has_artifact_role:1;
    unsigned has_contract_field:1;
    unsigned has_digest:1;
    unsigned has_supported_devices:1;
    unsigned has_preferred_device:1;
    unsigned has_count:1;
    unsigned has_metrics:1;
} h3_ane_diagnostic;

void h3_ane_diagnostic_record_first(h3_ane_diagnostic *diagnostic,
                                    h3_ane_stage stage, h3_ane_code code,
                                    h3_ane_reason reason,
                                    const char *message);
void h3_ane_diagnostic_merge_first(h3_ane_diagnostic *destination,
                                   const h3_ane_diagnostic *source);
const char *h3_ane_stage_name(h3_ane_stage stage);
const char *h3_ane_code_name(h3_ane_code code);
const char *h3_ane_artifact_role_name(h3_ane_artifact_role role);
const char *h3_ane_contract_field_name(h3_ane_contract_field field);

enum {
    H3_ANE_MAX_OPERATIONS = 4096,
    H3_ANE_MAX_OPERATION_DEPTH = 64,
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
    uint64_t total;
    uint64_t constant;
    uint64_t nonconstant;
    uint64_t neural_engine_supported;
    uint64_t cpu_only;
    uint64_t gpu_only;
    uint64_t unknown_nonconstant;
    uint64_t constant_nil_usage;
} h3_ane_inventory_summary;

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
void h3_ane_diagnostic_snapshot(h3_ane *ane, h3_ane_diagnostic *diagnostic);
void h3_ane_inventory_snapshot(h3_ane *ane,
                               h3_ane_inventory_summary *summary);

#ifdef H3_ANE_TESTING
typedef struct {
    int (*load)(void *, h3_ane_diagnostic *);
    int (*plan)(void *, h3_ane_operation_usage *, size_t *, h3_ane_diagnostic *);
    int (*predict)(void *, const float *, size_t, float *, size_t,
                   h3_ane_diagnostic *);
    void (*free)(void *);
    void *opaque;
} h3_ane_test_backend;

typedef struct h3_ane_test_plan_node {
    h3_ane_operation_usage usage;
    const struct h3_ane_test_plan_node *children;
    size_t child_count;
} h3_ane_test_plan_node;

void h3_ane_test_set_backend(const h3_ane_test_backend *backend);
int h3_ane_test_collect_plan(const h3_ane_test_plan_node *nodes,
                             size_t node_count,
                             h3_ane_operation_usage **operations,
                             size_t *operation_count,
                             h3_ane_inventory_summary *summary,
                             h3_ane_diagnostic *diagnostic);
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
