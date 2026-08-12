#import "h3_ane.h"
#import "h3_ane_internal.h"

#import <CoreML/CoreML.h>
#import <Foundation/Foundation.h>

#include <dispatch/dispatch.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

typedef int (*h3_ane_load_fn)(void *, h3_ane_diagnostic *);
typedef int (*h3_ane_plan_fn)(void *, h3_ane_operation_usage *, size_t *,
                              h3_ane_diagnostic *);
typedef int (*h3_ane_predict_fn)(void *, const float *, size_t, float *, size_t,
                                 h3_ane_diagnostic *);
typedef void (*h3_ane_free_fn)(void *);

struct h3_ane {
    h3_ane_load_fn load;
    h3_ane_plan_fn plan;
    h3_ane_predict_fn predict;
    h3_ane_free_fn free_backend;
    void *opaque;
    h3_ane_stats stats;
    h3_ane_reason unavailable_reason;
    h3_ane_diagnostic diagnostic;
    h3_ane_inventory_summary inventory;
    int backend_loaded;
    int real_backend;
    int test_backend;
    int configured;
    pthread_mutex_t prediction_mutex;
};

@interface H3ANERealBackend : NSObject
@property(nonatomic, copy) NSString *modelPath;
@property(nonatomic, strong) MLModel *model;
@property(nonatomic, copy) NSString *inputName;
@property(nonatomic, copy) NSString *outputName;
@property(nonatomic) double inputSeconds;
@property(nonatomic) double predictionSeconds;
@property(nonatomic) double outputSeconds;
@property(nonatomic) h3_ane_contract contract;
@end

@implementation H3ANERealBackend
@end

#ifdef H3_ANE_TESTING
static h3_ane_test_backend h3_test_backend;
static int h3_test_backend_set;

void h3_ane_test_set_backend(const h3_ane_test_backend *backend) {
    @autoreleasepool {
        if (backend) {
            h3_test_backend = *backend;
            h3_test_backend_set = 1;
        } else {
            memset(&h3_test_backend, 0, sizeof(h3_test_backend));
            h3_test_backend_set = 0;
        }
    }
}
#endif

static double monotonic_seconds(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &value) != 0) return 0.0;
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

static void set_error(char *error, size_t error_size, const char *message) {
    if (!error || error_size == 0) return;
    snprintf(error, error_size, "%s", message ? message : "ANE failure");
}

void h3_ane_diagnostic_record_first(h3_ane_diagnostic *diagnostic,
                                    h3_ane_stage stage, h3_ane_code code,
                                    h3_ane_reason reason,
                                    const char *message) {
    if (!diagnostic || diagnostic->code != H3_ANE_CODE_NONE ||
        code == H3_ANE_CODE_NONE) return;
    diagnostic->stage = stage;
    diagnostic->code = code;
    diagnostic->reason = reason;
    snprintf(diagnostic->message, sizeof(diagnostic->message), "%s",
             message ? message : "ANE failure");
}

void h3_ane_diagnostic_merge_first(h3_ane_diagnostic *destination,
                                   const h3_ane_diagnostic *source) {
    if (!destination || destination->code != H3_ANE_CODE_NONE || !source ||
        source->code == H3_ANE_CODE_NONE) return;
    *destination = *source;
}

const char *h3_ane_stage_name(h3_ane_stage stage) {
    static const char *const names[] = {
        "none", "setup", "artifact", "contract", "receipt", "load",
        "compute_plan", "eligibility", "input", "prediction", "output",
        "parity", "publication",
    };
    return stage >= H3_ANE_STAGE_NONE && stage <= H3_ANE_STAGE_PUBLICATION ?
        names[stage] : NULL;
}

const char *h3_ane_code_name(h3_ane_code code) {
    static const char *const names[] = {
        "none", "disabled", "os_unsupported", "allocation_failed",
        "compiled_model_unreadable", "compiled_model_digest_failed",
        "source_weights_unreadable", "source_tensor_digest_failed",
        "metadata_missing", "metadata_mismatch", "fingerprint_mismatch",
        "shape_mismatch", "dtype_mismatch", "receipt_missing",
        "receipt_malformed", "receipt_digest_mismatch", "receipt_invalid",
        "model_load_failed", "model_load_exception", "plan_timeout",
        "plan_load_failed", "program_missing", "main_missing",
        "operation_inventory_empty", "operation_inventory_limit_exceeded",
        "operation_nesting_limit_exceeded", "operation_inventory_changed",
        "operation_usage_unknown", "operation_not_neural_engine_supported",
        "device_unknown", "input_shape_mismatch", "input_dtype_mismatch",
        "input_copy_failed", "prediction_failed", "prediction_exception",
        "output_shape_mismatch", "output_dtype_mismatch", "output_copy_failed",
        "output_nonfinite", "parity_metrics_nonfinite", "parity_bounds_failed",
        "result_write_failed", "receipt_write_failed",
    };
    return code >= H3_ANE_CODE_NONE && code <= H3_ANE_CODE_RECEIPT_WRITE_FAILED ?
        names[code] : NULL;
}

static void record_first(h3_ane *ane, h3_ane_stage stage, h3_ane_code code,
                         h3_ane_reason reason, const char *message) {
    if (ane) h3_ane_diagnostic_record_first(&ane->diagnostic, stage, code,
                                            reason, message);
}

static int diagnostics_enabled(void) {
    const char *trace = getenv("H3_ANE_TRACE");
    const char *profile = getenv("H3_PROFILE");
    return (trace && strcmp(trace, "1") == 0) ||
           (profile && strcmp(profile, "1") == 0);
}

static const char *reason_name(h3_ane_reason reason) {
    static const char *const names[] = {
        "none", "disabled", "os", "contract", "fingerprint", "receipt",
        "eligibility", "load", "prediction", "shape", "dtype", "nonfinite",
    };
    return reason >= H3_ANE_REASON_NONE && reason <= H3_ANE_REASON_NONFINITE ?
        names[reason] : "unknown";
}

static h3_ane_reason callback_reason(int result, h3_ane_reason fallback) {
    if (result >= 0) return fallback;
    int reason = -result;
    if (reason > (int)H3_ANE_REASON_NONE &&
        reason <= (int)H3_ANE_REASON_NONFINITE)
        return (h3_ane_reason)reason;
    return fallback;
}

static int valid_hex_digest(const char digest[65]) {
    if (!digest || strlen(digest) != 64) return 0;
    for (size_t index = 0; index < 64; index++) {
        char byte = digest[index];
        if (!((byte >= '0' && byte <= '9') ||
              (byte >= 'a' && byte <= 'f')))
            return 0;
    }
    return 1;
}

static h3_ane_reason validate_contract(const h3_ane_contract *contract) {
    static const uint32_t shape[5] = {1, 1, 256, 256, 128};
    if (!contract) return H3_ANE_REASON_CONTRACT;
    if (contract->boundary_dtype != H3_ANE_DTYPE_F32)
        return H3_ANE_REASON_DTYPE;
    if (contract->version != 1 || strcmp(contract->variant, "FL2VA") != 0 ||
        contract->block_level != 0 || contract->block_index != 0 ||
        strcmp(contract->weight_prefix, "encoder.down.0.block.0") != 0 ||
        memcmp(contract->shape, shape, sizeof(shape)) != 0 ||
        !valid_hex_digest(contract->source_sha256))
        return H3_ANE_REASON_CONTRACT;
    return H3_ANE_REASON_NONE;
}

static int canonical_strides(const ptrdiff_t strides[5],
                             const uint32_t shape[5]) {
    ptrdiff_t expected = 1;
    for (size_t reverse = 5; reverse > 0; reverse--) {
        size_t index = reverse - 1;
        if (strides[index] != expected) return 0;
        if (shape[index] && expected > PTRDIFF_MAX / shape[index]) return 0;
        expected *= shape[index];
    }
    return 1;
}

static int copy_to_strided(float *destination, const ptrdiff_t strides[5],
                           const uint32_t shape[5], const float *source) {
    if (!destination || !strides || !shape || !source) return 0;
    for (size_t index = 0; index < 5; index++)
        if (strides[index] < 0) return 0;
    size_t count = 1;
    for (size_t index = 0; index < 5; index++) count *= shape[index];
    if (canonical_strides(strides, shape)) {
        memcpy(destination, source, count * sizeof(*source));
        return 1;
    }
    size_t linear = 0;
    for (uint32_t i0 = 0; i0 < shape[0]; i0++)
        for (uint32_t i1 = 0; i1 < shape[1]; i1++)
            for (uint32_t i2 = 0; i2 < shape[2]; i2++)
                for (uint32_t i3 = 0; i3 < shape[3]; i3++)
                    for (uint32_t i4 = 0; i4 < shape[4]; i4++, linear++) {
                        ptrdiff_t offset = (ptrdiff_t)i0 * strides[0] +
                            (ptrdiff_t)i1 * strides[1] +
                            (ptrdiff_t)i2 * strides[2] +
                            (ptrdiff_t)i3 * strides[3] +
                            (ptrdiff_t)i4 * strides[4];
                        destination[offset] = source[linear];
                    }
    return 1;
}

static int copy_from_strided(float *destination, const float *source,
                             const ptrdiff_t strides[5],
                             const uint32_t shape[5]) {
    if (!destination || !strides || !shape || !source) return 0;
    for (size_t index = 0; index < 5; index++)
        if (strides[index] < 0) return 0;
    size_t count = 1;
    for (size_t index = 0; index < 5; index++) count *= shape[index];
    if (canonical_strides(strides, shape)) {
        memcpy(destination, source, count * sizeof(*destination));
        return 1;
    }
    size_t linear = 0;
    for (uint32_t i0 = 0; i0 < shape[0]; i0++)
        for (uint32_t i1 = 0; i1 < shape[1]; i1++)
            for (uint32_t i2 = 0; i2 < shape[2]; i2++)
                for (uint32_t i3 = 0; i3 < shape[3]; i3++)
                    for (uint32_t i4 = 0; i4 < shape[4]; i4++, linear++) {
                        ptrdiff_t offset = (ptrdiff_t)i0 * strides[0] +
                            (ptrdiff_t)i1 * strides[1] +
                            (ptrdiff_t)i2 * strides[2] +
                            (ptrdiff_t)i3 * strides[3] +
                            (ptrdiff_t)i4 * strides[4];
                        destination[linear] = source[offset];
                    }
    return 1;
}

#ifdef H3_ANE_TESTING
int h3_ane_test_copy_to_strided(float *destination,
                                const ptrdiff_t strides[5],
                                const uint32_t shape[5],
                                const float *source) {
    return copy_to_strided(destination, strides, shape, source);
}

int h3_ane_test_copy_from_strided(float *destination, const float *source,
                                  const ptrdiff_t strides[5],
                                  const uint32_t shape[5]) {
    return copy_from_strided(destination, source, strides, shape);
}
#endif

static h3_ane_reason validate_metadata_values(const char *const values[8],
                                              const h3_ane_contract *contract) {
    if (!values || !contract) return H3_ANE_REASON_CONTRACT;
    for (size_t index = 0; index < 8; index++)
        if (!values[index]) return H3_ANE_REASON_CONTRACT;
    char version[16], block_level[16], block_index[16], shape[64];
    int written = snprintf(version, sizeof(version), "%u", contract->version);
    if (written <= 0 || (size_t)written >= sizeof(version) ||
        strcmp(values[0], version) != 0 ||
        strcmp(values[1], contract->variant) != 0)
        return H3_ANE_REASON_CONTRACT;
    written = snprintf(block_level, sizeof(block_level), "%u",
                       contract->block_level);
    if (written <= 0 || (size_t)written >= sizeof(block_level) ||
        strcmp(values[2], block_level) != 0)
        return H3_ANE_REASON_CONTRACT;
    written = snprintf(block_index, sizeof(block_index), "%u",
                       contract->block_index);
    if (written <= 0 || (size_t)written >= sizeof(block_index) ||
        strcmp(values[3], block_index) != 0 ||
        strcmp(values[4], contract->weight_prefix) != 0)
        return H3_ANE_REASON_CONTRACT;
    if (strcmp(values[5], "F32") != 0) return H3_ANE_REASON_DTYPE;
    written = snprintf(shape, sizeof(shape), "%u,%u,%u,%u,%u",
                       contract->shape[0], contract->shape[1],
                       contract->shape[2], contract->shape[3],
                       contract->shape[4]);
    if (written <= 0 || (size_t)written >= sizeof(shape) ||
        strcmp(values[6], shape) != 0)
        return H3_ANE_REASON_SHAPE;
    if (!valid_hex_digest(values[7]) ||
        strcmp(values[7], contract->source_sha256) != 0)
        return H3_ANE_REASON_FINGERPRINT;
    return H3_ANE_REASON_NONE;
}

static h3_ane_reason validate_creator_metadata(id metadata,
                                               const h3_ane_contract *contract) {
    if (![metadata isKindOfClass:[NSDictionary class]])
        return H3_ANE_REASON_CONTRACT;
    NSDictionary *dictionary = metadata;
    static NSArray<NSString *> *keys;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        keys = @[@"version", @"variant", @"block_level", @"block_index",
                 @"weight_prefix", @"boundary_dtype", @"shape",
                 @"source_sha256"];
    });
    const char *values[8] = {0};
    for (size_t index = 0; index < 8; index++) {
        id value = dictionary[keys[index]];
        if (![value isKindOfClass:[NSString class]])
            return H3_ANE_REASON_CONTRACT;
        values[index] = [value UTF8String];
    }
    return validate_metadata_values(values, contract);
}

#ifdef H3_ANE_TESTING
int h3_ane_test_validate_metadata(const char *const values[8],
                                  const h3_ane_contract *contract) {
    @autoreleasepool {
        static NSString *const keys[8] = {
            @"version", @"variant", @"block_level", @"block_index",
            @"weight_prefix", @"boundary_dtype", @"shape", @"source_sha256",
        };
        NSMutableDictionary *dictionary = [NSMutableDictionary dictionary];
        for (size_t index = 0; index < 8; index++) {
            if (values[index])
                dictionary[keys[index]] =
                    [NSString stringWithUTF8String:values[index]];
        }
        return (int)validate_creator_metadata(dictionary, contract);
    }
}
#endif

static uint32_t device_bit(id<MLComputeDeviceProtocol> device)
    API_AVAILABLE(macos(14.4)) {
    if ([device isKindOfClass:[MLCPUComputeDevice class]])
        return H3_ANE_DEVICE_CPU;
    if ([device isKindOfClass:[MLGPUComputeDevice class]])
        return H3_ANE_DEVICE_GPU;
    if ([device isKindOfClass:[MLNeuralEngineComputeDevice class]])
        return H3_ANE_DEVICE_NEURAL_ENGINE;
    return 0;
}

typedef struct {
    const h3_ane_plan_tree_adapter *adapter;
    void *context;
    h3_ane_operation_usage *operations;
    size_t capacity;
    size_t count;
    h3_ane_inventory_summary summary;
    h3_ane_diagnostic *diagnostic;
} plan_walk;

static int record_inventory_failure(plan_walk *walk, h3_ane_code code,
                                    uint64_t observed, uint64_t limit,
                                    const char *message) {
    h3_ane_diagnostic_record_first(walk->diagnostic,
                                   H3_ANE_STAGE_COMPUTE_PLAN, code,
                                   H3_ANE_REASON_ELIGIBILITY, message);
    if (walk->diagnostic && walk->diagnostic->code == code) {
        walk->diagnostic->observed_count = observed;
        walk->diagnostic->limit = limit;
        walk->diagnostic->has_count = 1;
    }
    return 0;
}

static int walk_plan_node(plan_walk *walk, void *node, size_t depth) {
    if (depth > H3_ANE_MAX_OPERATION_DEPTH)
        return record_inventory_failure(
            walk, H3_ANE_CODE_OPERATION_NESTING_LIMIT_EXCEEDED, depth,
            H3_ANE_MAX_OPERATION_DEPTH, "operation nesting limit exceeded");
    if (walk->count == H3_ANE_MAX_OPERATIONS)
        return record_inventory_failure(
            walk, H3_ANE_CODE_OPERATION_INVENTORY_LIMIT_EXCEEDED,
            (uint64_t)walk->count + 1, H3_ANE_MAX_OPERATIONS,
            "operation inventory limit exceeded");
    h3_ane_operation_usage usage = {0};
    walk->adapter->usage(walk->context, node, &usage);
    if (walk->operations) {
        if (walk->count >= walk->capacity)
            return record_inventory_failure(
                walk, H3_ANE_CODE_OPERATION_INVENTORY_CHANGED,
                (uint64_t)walk->count + 1, walk->capacity,
                "operation inventory changed between count and fill");
        walk->operations[walk->count] = usage;
    }
    walk->count++;
    walk->summary.total++;
    if (usage.is_constant) {
        walk->summary.constant++;
        if (usage.supported_devices == 0 && usage.preferred_device == 0)
            walk->summary.constant_nil_usage++;
    } else {
        walk->summary.nonconstant++;
        if (usage.supported_devices == 0 || usage.preferred_device == 0) {
            walk->summary.unknown_nonconstant++;
            h3_ane_code code = usage.supported_devices == 0 ?
                H3_ANE_CODE_OPERATION_USAGE_UNKNOWN : H3_ANE_CODE_DEVICE_UNKNOWN;
            h3_ane_diagnostic_record_first(
                walk->diagnostic, H3_ANE_STAGE_ELIGIBILITY, code,
                H3_ANE_REASON_ELIGIBILITY,
                usage.supported_devices == 0 ?
                    "operation device usage is unknown" :
                    "operation preferred device is unknown");
        } else if (usage.supported_devices & H3_ANE_DEVICE_NEURAL_ENGINE) {
            walk->summary.neural_engine_supported++;
        } else {
            if (usage.supported_devices == H3_ANE_DEVICE_CPU)
                walk->summary.cpu_only++;
            if (usage.supported_devices == H3_ANE_DEVICE_GPU)
                walk->summary.gpu_only++;
            h3_ane_diagnostic_record_first(
                walk->diagnostic, H3_ANE_STAGE_ELIGIBILITY,
                H3_ANE_CODE_OPERATION_NOT_NEURAL_ENGINE_SUPPORTED,
                H3_ANE_REASON_ELIGIBILITY,
                "operation is not Neural Engine supported");
        }
        if (walk->diagnostic && walk->diagnostic->code != H3_ANE_CODE_NONE &&
            !walk->diagnostic->has_operation) {
            snprintf(walk->diagnostic->operation,
                     sizeof(walk->diagnostic->operation), "%s", usage.name);
            walk->diagnostic->has_operation = 1;
            walk->diagnostic->supported_devices = usage.supported_devices;
            walk->diagnostic->preferred_device = usage.preferred_device;
            walk->diagnostic->has_supported_devices = 1;
            walk->diagnostic->has_preferred_device = 1;
        }
    }
    size_t children = walk->adapter->child_count(walk->context, node);
    for (size_t index = 0; index < children; index++)
        if (!walk_plan_node(walk,
                            walk->adapter->child_at(walk->context, node, index),
                            depth + 1))
            return 0;
    return 1;
}

static int walk_plan_roots(plan_walk *walk) {
    size_t roots = walk->adapter->root_count(walk->context);
    for (size_t index = 0; index < roots; index++)
        if (!walk_plan_node(walk,
                            walk->adapter->root_at(walk->context, index), 0))
            return 0;
    if (walk->count == 0)
        return record_inventory_failure(
            walk, H3_ANE_CODE_OPERATION_INVENTORY_EMPTY, 0, 0,
            "operation inventory is empty");
    return 1;
}

int h3_ane_collect_plan_tree(const h3_ane_plan_tree_adapter *adapter,
                             void *context,
                             h3_ane_operation_usage **operations,
                             size_t *operation_count,
                             h3_ane_inventory_summary *summary,
                             h3_ane_diagnostic *diagnostic) {
    if (!adapter || !operations || !operation_count || !summary)
        return 0;
    *operations = NULL;
    *operation_count = 0;
    memset(summary, 0, sizeof(*summary));
    plan_walk count_walk = {.adapter = adapter, .context = context,
                            .diagnostic = diagnostic};
    if (!walk_plan_roots(&count_walk)) return 0;
    if (count_walk.count > SIZE_MAX / sizeof(**operations)) {
        return record_inventory_failure(
            &count_walk, H3_ANE_CODE_ALLOCATION_FAILED, count_walk.count,
            SIZE_MAX / sizeof(**operations),
            "operation inventory allocation overflow");
    }
    h3_ane_operation_usage *inventory =
        calloc(count_walk.count, sizeof(*inventory));
    if (!inventory) {
        h3_ane_diagnostic_record_first(
            diagnostic, H3_ANE_STAGE_COMPUTE_PLAN,
            H3_ANE_CODE_ALLOCATION_FAILED, H3_ANE_REASON_ELIGIBILITY,
            "operation inventory allocation failed");
        return 0;
    }
    h3_ane_diagnostic fill_diagnostic = {0};
    plan_walk fill_walk = {.adapter = adapter, .context = context,
                           .operations = inventory,
                           .capacity = count_walk.count,
                           .diagnostic = &fill_diagnostic};
    if (!walk_plan_roots(&fill_walk) || fill_walk.count != count_walk.count) {
        free(inventory);
        h3_ane_diagnostic_record_first(
            diagnostic, H3_ANE_STAGE_COMPUTE_PLAN,
            H3_ANE_CODE_OPERATION_INVENTORY_CHANGED,
            H3_ANE_REASON_ELIGIBILITY,
            "operation inventory changed between count and fill");
        if (diagnostic &&
            diagnostic->code == H3_ANE_CODE_OPERATION_INVENTORY_CHANGED) {
            diagnostic->observed_count = fill_walk.count;
            diagnostic->limit = count_walk.count;
            diagnostic->has_count = 1;
        }
        return 0;
    }
    if (fill_diagnostic.code != H3_ANE_CODE_NONE) {
        free(inventory);
        h3_ane_diagnostic_merge_first(diagnostic, &fill_diagnostic);
        return 0;
    }
    *operations = inventory;
    *operation_count = fill_walk.count;
    *summary = fill_walk.summary;
    return 1;
}

static int real_load(void *opaque, h3_ane_diagnostic *diagnostic) {
    H3ANERealBackend *backend = (__bridge H3ANERealBackend *)opaque;
    @try {
        NSURL *url = [NSURL fileURLWithPath:backend.modelPath];
        MLModelConfiguration *configuration = [[MLModelConfiguration alloc] init];
        configuration.computeUnits = MLComputeUnitsCPUAndNeuralEngine;
        NSError *error = nil;
        MLModel *model = [MLModel modelWithContentsOfURL:url
                                          configuration:configuration
                                                  error:&error];
        if (!model || error) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_LOAD,
                H3_ANE_CODE_MODEL_LOAD_FAILED, H3_ANE_REASON_LOAD,
                "Core ML model load failed");
            return 0;
        }
        h3_ane_contract contract = backend.contract;
        id creatorMetadata = model.modelDescription.metadata[MLModelCreatorDefinedKey];
        if (![creatorMetadata isKindOfClass:[NSDictionary class]]) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_CONTRACT,
                H3_ANE_CODE_METADATA_MISSING, H3_ANE_REASON_CONTRACT,
                "creator metadata is missing");
            return -(int)H3_ANE_REASON_CONTRACT;
        }
        static NSArray<NSString *> *requiredKeys;
        static dispatch_once_t metadataOnce;
        dispatch_once(&metadataOnce, ^{
            requiredKeys = @[@"version", @"variant", @"block_level",
                @"block_index", @"weight_prefix", @"boundary_dtype",
                @"shape", @"source_sha256"];
        });
        for (NSString *key in requiredKeys) {
            if (![creatorMetadata[key] isKindOfClass:[NSString class]]) {
                h3_ane_diagnostic_record_first(diagnostic,
                    H3_ANE_STAGE_CONTRACT, H3_ANE_CODE_METADATA_MISSING,
                    H3_ANE_REASON_CONTRACT, "creator metadata is missing");
                return -(int)H3_ANE_REASON_CONTRACT;
            }
        }
        h3_ane_reason metadataReason = validate_creator_metadata(
            creatorMetadata, &contract);
        if (metadataReason != H3_ANE_REASON_NONE) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_CONTRACT,
                H3_ANE_CODE_METADATA_MISMATCH, metadataReason,
                "creator metadata is missing or incompatible");
            return -(int)metadataReason;
        }
        NSDictionary<NSString *, MLFeatureDescription *> *inputs =
            model.modelDescription.inputDescriptionsByName;
        NSDictionary<NSString *, MLFeatureDescription *> *outputs =
            model.modelDescription.outputDescriptionsByName;
        if (inputs.count != 1 || outputs.count != 1) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_CONTRACT,
                H3_ANE_CODE_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                "Core ML boundary feature count is incompatible");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        NSString *inputName = inputs.allKeys.firstObject;
        NSString *outputName = outputs.allKeys.firstObject;
        MLFeatureDescription *input = inputs[inputName];
        MLFeatureDescription *output = outputs[outputName];
        if (input.type != MLFeatureTypeMultiArray ||
            output.type != MLFeatureTypeMultiArray) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_CONTRACT,
                H3_ANE_CODE_DTYPE_MISMATCH, H3_ANE_REASON_DTYPE,
                "Core ML boundary dtype is incompatible");
            return -(int)H3_ANE_REASON_DTYPE;
        }
        MLMultiArrayConstraint *inputConstraint = input.multiArrayConstraint;
        MLMultiArrayConstraint *outputConstraint = output.multiArrayConstraint;
        if (inputConstraint.dataType != MLMultiArrayDataTypeFloat32 ||
            outputConstraint.dataType != MLMultiArrayDataTypeFloat32) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_CONTRACT,
                H3_ANE_CODE_DTYPE_MISMATCH, H3_ANE_REASON_DTYPE,
                "Core ML boundary dtype is incompatible");
            return -(int)H3_ANE_REASON_DTYPE;
        }
        NSArray<NSNumber *> *shape = @[@1, @1, @256, @256, @128];
        if (![inputConstraint.shape isEqualToArray:shape] ||
            ![outputConstraint.shape isEqualToArray:shape]) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_CONTRACT,
                H3_ANE_CODE_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                "Core ML boundary shape is incompatible");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        backend.model = model;
        backend.inputName = inputName;
        backend.outputName = outputName;
        return 1;
    } @catch (__unused NSException *exception) {
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_LOAD,
            H3_ANE_CODE_MODEL_LOAD_EXCEPTION, H3_ANE_REASON_LOAD,
            "Core ML model load raised an exception");
        return 0;
    }
}

typedef struct {
    MLComputePlan *plan;
    NSArray<MLModelStructureProgramOperation *> *roots;
} real_plan_tree;

static size_t real_root_count(void *context) {
    return (size_t)((real_plan_tree *)context)->roots.count;
}

static void *real_root_at(void *context, size_t index) {
    return (__bridge void *)((real_plan_tree *)context)->roots[index];
}

static size_t real_child_count(void *context, void *node) {
    (void)context;
    MLModelStructureProgramOperation *operation = (__bridge id)node;
    size_t count = 0;
    for (MLModelStructureProgramBlock *block in operation.blocks)
        count += (size_t)block.operations.count;
    return count;
}

static void *real_child_at(void *context, void *node, size_t index) {
    (void)context;
    MLModelStructureProgramOperation *operation = (__bridge id)node;
    for (MLModelStructureProgramBlock *block in operation.blocks) {
        size_t count = (size_t)block.operations.count;
        if (index < count) return (__bridge void *)block.operations[index];
        index -= count;
    }
    return NULL;
}

static void real_usage(void *context, void *node,
                       h3_ane_operation_usage *usage)
    API_AVAILABLE(macos(14.4)) {
    real_plan_tree *tree = context;
    MLModelStructureProgramOperation *operation = (__bridge id)node;
    const char *name = operation.operatorName.UTF8String;
    snprintf(usage->name, sizeof(usage->name), "%s", name ? name : "unknown");
    usage->is_constant = [operation.operatorName isEqualToString:@"const"];
    MLComputePlanDeviceUsage *deviceUsage =
        [tree->plan computeDeviceUsageForMLProgramOperation:operation];
    for (id<MLComputeDeviceProtocol> device in deviceUsage.supportedComputeDevices)
        usage->supported_devices |= device_bit(device);
    usage->preferred_device = device_bit(deviceUsage.preferredComputeDevice);
}

static int real_plan(void *opaque, h3_ane_operation_usage *operations,
                     size_t *operation_count, h3_ane_diagnostic *diagnostic) {
    if (@available(macOS 14.4, *)) {
        H3ANERealBackend *backend = (__bridge H3ANERealBackend *)opaque;
        @try {
            MLModelConfiguration *configuration = [[MLModelConfiguration alloc] init];
            configuration.computeUnits = MLComputeUnitsCPUAndNeuralEngine;
            __block MLComputePlan *loadedPlan = nil;
            dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
            [MLComputePlan loadContentsOfURL:
                               [NSURL fileURLWithPath:backend.modelPath]
                                configuration:configuration
                            completionHandler:^(MLComputePlan *plan,
                                                __unused NSError *error) {
                loadedPlan = plan;
                dispatch_semaphore_signal(semaphore);
            }];
            long waitResult = dispatch_semaphore_wait(
                semaphore,
                dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));
            if (waitResult != 0) {
                h3_ane_diagnostic_record_first(diagnostic,
                    H3_ANE_STAGE_COMPUTE_PLAN, H3_ANE_CODE_PLAN_TIMEOUT,
                    H3_ANE_REASON_ELIGIBILITY, "Core ML compute plan timed out");
                return 0;
            }
            MLModelStructureProgram *program = loadedPlan.modelStructure.program;
            MLModelStructureProgramFunction *main = program.functions[@"main"];
            if (!loadedPlan) {
                h3_ane_diagnostic_record_first(diagnostic,
                    H3_ANE_STAGE_COMPUTE_PLAN, H3_ANE_CODE_PLAN_LOAD_FAILED,
                    H3_ANE_REASON_ELIGIBILITY, "Core ML compute plan load failed");
                return 0;
            }
            if (!program) {
                h3_ane_diagnostic_record_first(diagnostic,
                    H3_ANE_STAGE_COMPUTE_PLAN, H3_ANE_CODE_PROGRAM_MISSING,
                    H3_ANE_REASON_ELIGIBILITY, "ML Program is missing");
                return 0;
            }
            if (!main) {
                h3_ane_diagnostic_record_first(diagnostic,
                    H3_ANE_STAGE_COMPUTE_PLAN, H3_ANE_CODE_MAIN_MISSING,
                    H3_ANE_REASON_ELIGIBILITY, "ML Program main function is missing");
                return 0;
            }
            real_plan_tree tree = {.plan = loadedPlan,
                                   .roots = main.block.operations};
            const h3_ane_plan_tree_adapter adapter = {
                .root_count = real_root_count, .root_at = real_root_at,
                .child_count = real_child_count, .child_at = real_child_at,
                .usage = real_usage,
            };
            h3_ane_operation_usage *inventory = NULL;
            size_t count = 0;
            h3_ane_inventory_summary summary;
            if (!h3_ane_collect_plan_tree(&adapter, &tree, &inventory, &count,
                                          &summary, diagnostic))
                return 0;
            if (!operations) {
                *operation_count = count;
                free(inventory);
                return 1;
            }
            if (*operation_count != count) {
                free(inventory);
                h3_ane_diagnostic_record_first(
                    diagnostic, H3_ANE_STAGE_COMPUTE_PLAN,
                    H3_ANE_CODE_OPERATION_INVENTORY_CHANGED,
                    H3_ANE_REASON_ELIGIBILITY,
                    "operation inventory changed between count and fill");
                return 0;
            }
            memcpy(operations, inventory, count * sizeof(*operations));
            free(inventory);
            *operation_count = count;
            return 1;
        } @catch (__unused NSException *exception) {
            h3_ane_diagnostic_record_first(diagnostic,
                H3_ANE_STAGE_COMPUTE_PLAN, H3_ANE_CODE_PLAN_LOAD_FAILED,
                H3_ANE_REASON_ELIGIBILITY, "Core ML compute plan load failed");
            return 0;
        }
    }
    return -(int)H3_ANE_REASON_OS;
}

static int real_predict(void *opaque, const float *input, size_t input_count,
                        float *output, size_t output_count,
                        h3_ane_diagnostic *diagnostic) {
    H3ANERealBackend *backend = (__bridge H3ANERealBackend *)opaque;
    @try {
        NSError *error = nil;
        NSArray<NSNumber *> *shape = @[@1, @1, @256, @256, @128];
        double start = monotonic_seconds();
        MLMultiArray *inputArray = [[MLMultiArray alloc]
            initWithShape:shape dataType:MLMultiArrayDataTypeFloat32 error:&error];
        if (!inputArray || error || (size_t)inputArray.count != input_count) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_INPUT,
                H3_ANE_CODE_INPUT_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                "Core ML input shape is incompatible");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        ptrdiff_t inputStrides[5];
        if (inputArray.strides.count != 5) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_INPUT,
                H3_ANE_CODE_INPUT_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                "Core ML input shape is incompatible");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        for (size_t index = 0; index < 5; index++)
            inputStrides[index] = inputArray.strides[index].longLongValue;
        const uint32_t dimensions[5] = {1, 1, 256, 256, 128};
        if (!copy_to_strided(inputArray.dataPointer, inputStrides, dimensions,
                             input)) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_INPUT,
                H3_ANE_CODE_INPUT_COPY_FAILED, H3_ANE_REASON_SHAPE,
                "Core ML input copy failed");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        MLDictionaryFeatureProvider *provider = [[MLDictionaryFeatureProvider alloc]
            initWithDictionary:@{backend.inputName:
                                     [MLFeatureValue featureValueWithMultiArray:
                                                         inputArray]}
                           error:&error];
        if (!provider || error) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_INPUT,
                H3_ANE_CODE_INPUT_COPY_FAILED, H3_ANE_REASON_PREDICTION,
                "Core ML input provider creation failed");
            return 0;
        }
        backend.inputSeconds = monotonic_seconds() - start;
        start = monotonic_seconds();
        id<MLFeatureProvider> prediction =
            [backend.model predictionFromFeatures:provider error:&error];
        backend.predictionSeconds = monotonic_seconds() - start;
        if (!prediction || error) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_PREDICTION,
                H3_ANE_CODE_PREDICTION_FAILED, H3_ANE_REASON_PREDICTION,
                "Core ML prediction failed");
            return 0;
        }
        start = monotonic_seconds();
        MLFeatureValue *value = [prediction featureValueForName:backend.outputName];
        MLMultiArray *array = value.multiArrayValue;
        if (!array) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_OUTPUT,
                H3_ANE_CODE_OUTPUT_COPY_FAILED, H3_ANE_REASON_SHAPE,
                "Core ML output is missing");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        if (array.dataType != MLMultiArrayDataTypeFloat32) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_OUTPUT,
                H3_ANE_CODE_OUTPUT_DTYPE_MISMATCH, H3_ANE_REASON_DTYPE,
                "Core ML output dtype is incompatible");
            return -(int)H3_ANE_REASON_DTYPE;
        }
        if ((size_t)array.count != output_count) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_OUTPUT,
                H3_ANE_CODE_OUTPUT_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                "Core ML output shape is incompatible");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        ptrdiff_t outputStrides[5];
        if (array.shape.count != 5 || array.strides.count != 5) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_OUTPUT,
                H3_ANE_CODE_OUTPUT_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                "Core ML output shape is incompatible");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        for (size_t index = 0; index < 5; index++) {
            if (array.shape[index].unsignedLongLongValue != dimensions[index]) {
                h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_OUTPUT,
                    H3_ANE_CODE_OUTPUT_SHAPE_MISMATCH, H3_ANE_REASON_SHAPE,
                    "Core ML output shape is incompatible");
                return -(int)H3_ANE_REASON_SHAPE;
            }
            outputStrides[index] = array.strides[index].longLongValue;
        }
        if (!copy_from_strided(output, array.dataPointer, outputStrides,
                               dimensions)) {
            h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_OUTPUT,
                H3_ANE_CODE_OUTPUT_COPY_FAILED, H3_ANE_REASON_SHAPE,
                "Core ML output copy failed");
            return -(int)H3_ANE_REASON_SHAPE;
        }
        backend.outputSeconds = monotonic_seconds() - start;
        return 1;
    } @catch (__unused NSException *exception) {
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_PREDICTION,
            H3_ANE_CODE_PREDICTION_EXCEPTION, H3_ANE_REASON_PREDICTION,
            "Core ML prediction raised an exception");
        return 0;
    }
}

static void real_free(void *opaque) {
    (void)CFBridgingRelease(opaque);
}

static void initialize_real_backend(h3_ane *ane, const char *model_path) {
    H3ANERealBackend *backend = [[H3ANERealBackend alloc] init];
    backend.modelPath = [NSString stringWithUTF8String:model_path];
    backend.contract = (h3_ane_contract){0};
    ane->load = real_load;
    ane->plan = real_plan;
    ane->predict = real_predict;
    ane->free_backend = real_free;
    ane->opaque = (__bridge_retained void *)backend;
    ane->real_backend = 1;
}

#ifdef H3_ANE_TESTING
typedef struct {
    const h3_ane_test_plan_node *nodes;
    size_t count;
} test_plan_tree;

static size_t test_root_count(void *context) {
    return ((test_plan_tree *)context)->count;
}

static void *test_root_at(void *context, size_t index) {
    return (void *)&((test_plan_tree *)context)->nodes[index];
}

static size_t test_child_count(void *context, void *node) {
    (void)context;
    return ((h3_ane_test_plan_node *)node)->child_count;
}

static void *test_child_at(void *context, void *node, size_t index) {
    (void)context;
    return (void *)&((h3_ane_test_plan_node *)node)->children[index];
}

static void test_usage(void *context, void *node,
                       h3_ane_operation_usage *usage) {
    (void)context;
    *usage = ((h3_ane_test_plan_node *)node)->usage;
}

int h3_ane_test_collect_plan(const h3_ane_test_plan_node *nodes,
                             size_t node_count,
                             h3_ane_operation_usage **operations,
                             size_t *operation_count,
                             h3_ane_inventory_summary *summary,
                             h3_ane_diagnostic *diagnostic) {
    test_plan_tree tree = {.nodes = nodes, .count = node_count};
    const h3_ane_plan_tree_adapter adapter = {
        .root_count = test_root_count, .root_at = test_root_at,
        .child_count = test_child_count, .child_at = test_child_at,
        .usage = test_usage,
    };
    return h3_ane_collect_plan_tree(&adapter, &tree, operations,
                                    operation_count, summary, diagnostic);
}

static int call_test_plan_bounded(h3_ane *ane,
                                  h3_ane_operation_usage *operations,
                                  size_t *operation_count) {
    h3_ane_plan_fn plan = ane->plan;
    void *opaque = ane->opaque;
    size_t capacity = operations ? *operation_count : 0;
    h3_ane_operation_usage *temporary = operations ?
        calloc(capacity, sizeof(*temporary)) : NULL;
    if (operations && !temporary) return 0;
    __block int result = 0;
    __block size_t count = capacity;
    dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        @autoreleasepool {
            result = plan(opaque, temporary, &count, &ane->diagnostic);
            dispatch_semaphore_signal(semaphore);
        }
    });
    long waitResult = dispatch_semaphore_wait(
        semaphore, dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC));
    if (waitResult != 0) return 0;
    if (operations && count <= capacity)
        memcpy(operations, temporary, count * sizeof(*operations));
    *operation_count = count;
    free(temporary);
    return result;
}
#endif

static void mark_unavailable(h3_ane *ane, h3_ane_reason reason,
                             char *error, size_t error_size,
                             const char *message) {
    ane->unavailable_reason = reason;
    ane->stats.last_reason = reason;
    set_error(error, error_size, message);
    if (ane->configured && diagnostics_enabled())
        fprintf(stderr, "h3-ane fallback reason=%s message=%s\n",
                reason_name(reason), message ? message : "ANE failure");
}

static h3_ane *create_impl(const char *model_path,
                           const h3_ane_contract *contract, int shadow,
                           int authorized,
                           char *error, size_t error_size) {
    h3_ane *ane = calloc(1, sizeof(*ane));
    if (!ane) {
        set_error(error, error_size, "cannot allocate ANE handle");
        return NULL;
    }
    if (pthread_mutex_init(&ane->prediction_mutex, NULL) != 0) {
        free(ane);
        set_error(error, error_size, "cannot initialize ANE prediction lock");
        return NULL;
    }
    ane->stats.shadow = shadow != 0;
    const char *enabled_path = getenv("H3_ANE_MODEL");
    ane->configured = authorized || (enabled_path && *enabled_path);
    if (!model_path || !*model_path ||
        (!authorized && (!enabled_path || !*enabled_path ||
                         strcmp(model_path, enabled_path) != 0))) {
        record_first(ane, H3_ANE_STAGE_SETUP, H3_ANE_CODE_DISABLED,
                     H3_ANE_REASON_DISABLED, "ANE backend is disabled");
        mark_unavailable(ane, H3_ANE_REASON_DISABLED, error, error_size,
                         "ANE backend is disabled");
        return ane;
    }
    if (![[NSProcessInfo processInfo] isOperatingSystemAtLeastVersion:
            (NSOperatingSystemVersion){14, 4, 0}]) {
        record_first(ane, H3_ANE_STAGE_SETUP, H3_ANE_CODE_OS_UNSUPPORTED,
                     H3_ANE_REASON_OS, "ANE backend requires macOS 14.4 or later");
        mark_unavailable(ane, H3_ANE_REASON_OS, error, error_size,
                         "ANE backend requires macOS 14.4 or later");
        return ane;
    }
    h3_ane_reason contract_reason = validate_contract(contract);
    if (contract_reason != H3_ANE_REASON_NONE) {
        record_first(ane, H3_ANE_STAGE_CONTRACT,
                     contract_reason == H3_ANE_REASON_DTYPE ?
                         H3_ANE_CODE_DTYPE_MISMATCH : H3_ANE_CODE_METADATA_MISMATCH,
                     contract_reason, "ANE model contract is incompatible");
        mark_unavailable(ane, contract_reason, error, error_size,
                         "ANE model contract is incompatible");
        return ane;
    }
    if (!shadow) {
        char digest[65];
        struct stat model_status;
        if (lstat(model_path, &model_status) != 0 ||
            !S_ISDIR(model_status.st_mode)) {
            record_first(ane, H3_ANE_STAGE_ARTIFACT,
                         H3_ANE_CODE_COMPILED_MODEL_UNREADABLE,
                         H3_ANE_REASON_FINGERPRINT,
                         "compiled model is unreadable");
            mark_unavailable(ane, H3_ANE_REASON_FINGERPRINT, error, error_size,
                             "compiled ANE model is unreadable");
            return ane;
        }
        if (!h3_ane_sha256_directory(model_path, digest, error, error_size)) {
            record_first(ane, H3_ANE_STAGE_ARTIFACT,
                         H3_ANE_CODE_COMPILED_MODEL_DIGEST_FAILED,
                         H3_ANE_REASON_FINGERPRINT,
                         "compiled model digest failed");
            mark_unavailable(ane, H3_ANE_REASON_FINGERPRINT, error, error_size,
                             "cannot fingerprint compiled ANE model");
            return ane;
        }
        size_t receipt_size = strlen(model_path) +
                              strlen(".qualification.json") + 1;
        char *receipt_path = malloc(receipt_size);
        if (!receipt_path) {
            record_first(ane, H3_ANE_STAGE_SETUP, H3_ANE_CODE_ALLOCATION_FAILED,
                         H3_ANE_REASON_LOAD, "receipt path allocation failed");
            pthread_mutex_destroy(&ane->prediction_mutex);
            free(ane);
            set_error(error, error_size, "cannot allocate receipt path");
            return NULL;
        }
        snprintf(receipt_path, receipt_size, "%s.qualification.json", model_path);
        h3_ane_receipt receipt;
        struct stat receipt_status;
        int receipt_exists = lstat(receipt_path, &receipt_status) == 0;
        int loaded = h3_ane_receipt_load(receipt_path, &receipt, error, error_size);
        free(receipt_path);
        if (!loaded) {
            record_first(ane, H3_ANE_STAGE_RECEIPT,
                         receipt_exists ? H3_ANE_CODE_RECEIPT_MALFORMED :
                                          H3_ANE_CODE_RECEIPT_MISSING,
                         H3_ANE_REASON_RECEIPT,
                         "qualification receipt is missing or malformed");
            mark_unavailable(ane, H3_ANE_REASON_RECEIPT, error, error_size,
                             "ANE qualification receipt is missing or invalid");
            return ane;
        }
        if (strcmp(receipt.source_sha256, contract->source_sha256) != 0) {
            record_first(ane, H3_ANE_STAGE_RECEIPT,
                         H3_ANE_CODE_FINGERPRINT_MISMATCH,
                         H3_ANE_REASON_FINGERPRINT,
                         "source fingerprint does not match");
            mark_unavailable(ane, H3_ANE_REASON_FINGERPRINT, error, error_size,
                             "ANE source fingerprint does not match");
            return ane;
        }
        if (strcmp(receipt.model_sha256, digest) != 0) {
            record_first(ane, H3_ANE_STAGE_RECEIPT,
                         H3_ANE_CODE_RECEIPT_DIGEST_MISMATCH,
                         H3_ANE_REASON_RECEIPT,
                         "receipt model digest does not match");
            mark_unavailable(ane, H3_ANE_REASON_RECEIPT, error, error_size,
                             "ANE qualification receipt digest does not match");
            return ane;
        }
        if (!h3_ane_receipt_validate(contract, &receipt, digest, error,
                                     error_size)) {
            record_first(ane, H3_ANE_STAGE_RECEIPT,
                         H3_ANE_CODE_RECEIPT_INVALID,
                         H3_ANE_REASON_RECEIPT,
                         "qualification receipt is invalid");
            mark_unavailable(ane, H3_ANE_REASON_RECEIPT, error, error_size,
                             "ANE qualification receipt does not match");
            return ane;
        }
    }

#ifdef H3_ANE_TESTING
    if (h3_test_backend_set) {
        ane->load = h3_test_backend.load;
        ane->plan = h3_test_backend.plan;
        ane->predict = h3_test_backend.predict;
        ane->free_backend = h3_test_backend.free;
        ane->opaque = h3_test_backend.opaque;
        ane->test_backend = 1;
    } else
#endif
    {
        initialize_real_backend(ane, model_path);
        H3ANERealBackend *backend = (__bridge H3ANERealBackend *)ane->opaque;
        backend.contract = *contract;
    }

    if (!ane->load || !ane->plan || !ane->predict || !ane->free_backend) {
        record_first(ane, H3_ANE_STAGE_LOAD, H3_ANE_CODE_MODEL_LOAD_FAILED,
                     H3_ANE_REASON_LOAD, "ANE backend is incomplete");
        mark_unavailable(ane, H3_ANE_REASON_LOAD, error, error_size,
                         "ANE backend is incomplete");
        return ane;
    }
    double start = monotonic_seconds();
    int load_result = ane->load(ane->opaque, &ane->diagnostic);
    ane->stats.load_seconds = monotonic_seconds() - start;
    if (load_result <= 0) {
        record_first(ane, H3_ANE_STAGE_LOAD, H3_ANE_CODE_MODEL_LOAD_FAILED,
                     H3_ANE_REASON_LOAD, "Core ML model load failed");
        mark_unavailable(ane, callback_reason(load_result, H3_ANE_REASON_LOAD),
                         error, error_size, "Core ML model load failed");
        return ane;
    }
    ane->backend_loaded = 1;
    h3_ane_operation_usage *operations = NULL;
    size_t operation_count = 0;
    int plan_result;
#ifdef H3_ANE_TESTING
    if (ane->test_backend)
        plan_result = call_test_plan_bounded(ane, NULL, &operation_count);
    else
#endif
        plan_result = ane->plan(ane->opaque, NULL, &operation_count,
                                &ane->diagnostic);
    if (plan_result <= 0 || operation_count == 0 ||
        operation_count > H3_ANE_MAX_OPERATIONS) {
        h3_ane_code plan_code = H3_ANE_CODE_PLAN_LOAD_FAILED;
        if (plan_result > 0 && operation_count == 0)
            plan_code = H3_ANE_CODE_OPERATION_INVENTORY_EMPTY;
        else if (operation_count > H3_ANE_MAX_OPERATIONS)
            plan_code = H3_ANE_CODE_OPERATION_INVENTORY_LIMIT_EXCEEDED;
        record_first(ane, H3_ANE_STAGE_COMPUTE_PLAN, plan_code,
                     H3_ANE_REASON_ELIGIBILITY,
                     "Core ML compute plan is unavailable");
        mark_unavailable(ane,
                         callback_reason(plan_result,
                                         H3_ANE_REASON_ELIGIBILITY),
                         error, error_size, "Core ML compute plan is unavailable");
        return ane;
    }
    if (operation_count > SIZE_MAX / sizeof(*operations)) {
        record_first(ane, H3_ANE_STAGE_COMPUTE_PLAN,
                     H3_ANE_CODE_ALLOCATION_FAILED,
                     H3_ANE_REASON_ELIGIBILITY,
                     "operation inventory allocation overflow");
        mark_unavailable(ane, H3_ANE_REASON_ELIGIBILITY, error, error_size,
                         "Core ML compute plan is unavailable");
        return ane;
    }
    operations = calloc(operation_count, sizeof(*operations));
    if (!operations) {
        record_first(ane, H3_ANE_STAGE_COMPUTE_PLAN,
                     H3_ANE_CODE_ALLOCATION_FAILED,
                     H3_ANE_REASON_ELIGIBILITY,
                     "operation inventory allocation failed");
        mark_unavailable(ane, H3_ANE_REASON_ELIGIBILITY, error, error_size,
                         "Core ML compute plan is unavailable");
        return ane;
    }
    size_t fill_count = operation_count;
#ifdef H3_ANE_TESTING
    if (ane->test_backend)
        plan_result = call_test_plan_bounded(ane, operations, &fill_count);
    else
#endif
        plan_result = ane->plan(ane->opaque, operations, &fill_count,
                                &ane->diagnostic);
    if (plan_result <= 0 || fill_count != operation_count) {
        free(operations);
        record_first(ane, H3_ANE_STAGE_COMPUTE_PLAN,
                     H3_ANE_CODE_OPERATION_INVENTORY_CHANGED,
                     H3_ANE_REASON_ELIGIBILITY,
                     "operation inventory changed between count and fill");
        if (ane->diagnostic.code ==
            H3_ANE_CODE_OPERATION_INVENTORY_CHANGED) {
            ane->diagnostic.observed_count = fill_count;
            ane->diagnostic.limit = operation_count;
            ane->diagnostic.has_count = 1;
        }
        mark_unavailable(ane, H3_ANE_REASON_ELIGIBILITY, error, error_size,
                         "Core ML compute plan is unavailable");
        return ane;
    }
    int trace = getenv("H3_ANE_TRACE") &&
                strcmp(getenv("H3_ANE_TRACE"), "1") == 0;
    for (size_t index = 0; index < operation_count; index++) {
        h3_ane_operation_usage *usage = &operations[index];
        ane->inventory.total++;
        if (usage->is_constant) {
            ane->inventory.constant++;
            if (usage->supported_devices == 0 && usage->preferred_device == 0)
                ane->inventory.constant_nil_usage++;
        } else {
            ane->inventory.nonconstant++;
            if (usage->supported_devices == 0 || usage->preferred_device == 0)
                ane->inventory.unknown_nonconstant++;
            else if (usage->supported_devices & H3_ANE_DEVICE_NEURAL_ENGINE)
                ane->inventory.neural_engine_supported++;
            else if (usage->supported_devices == H3_ANE_DEVICE_CPU)
                ane->inventory.cpu_only++;
            else if (usage->supported_devices == H3_ANE_DEVICE_GPU)
                ane->inventory.gpu_only++;
        }
        ane->stats.preferred_device |= usage->preferred_device;
        if (trace) {
            fprintf(stderr,
                    "h3-ane operation=%s constant=%d supported=0x%x "
                    "preferred=0x%x\n",
                    usage->name, usage->is_constant, usage->supported_devices,
                    usage->preferred_device);
        }
        if (!usage->is_constant &&
            (usage->supported_devices == 0 || usage->preferred_device == 0)) {
            h3_ane_code code = usage->supported_devices == 0 ?
                H3_ANE_CODE_OPERATION_USAGE_UNKNOWN : H3_ANE_CODE_DEVICE_UNKNOWN;
            record_first(ane, H3_ANE_STAGE_ELIGIBILITY, code,
                         H3_ANE_REASON_ELIGIBILITY,
                         usage->supported_devices == 0 ?
                             "operation device usage is unknown" :
                             "operation preferred device is unknown");
            h3_ane_diagnostic *diagnostic = &ane->diagnostic;
            snprintf(diagnostic->operation, sizeof(diagnostic->operation), "%s",
                     usage->name);
            diagnostic->has_operation = 1;
            if (usage->supported_devices) {
                diagnostic->supported_devices = usage->supported_devices;
                diagnostic->has_supported_devices = 1;
            }
            if (usage->preferred_device) {
                diagnostic->preferred_device = usage->preferred_device;
                diagnostic->has_preferred_device = 1;
            }
            mark_unavailable(ane, H3_ANE_REASON_ELIGIBILITY, error, error_size,
                             "Core ML operation device usage is unknown");
            free(operations);
            return ane;
        }
        if (!usage->is_constant &&
            !(usage->supported_devices & H3_ANE_DEVICE_NEURAL_ENGINE)) {
            record_first(ane, H3_ANE_STAGE_ELIGIBILITY,
                         H3_ANE_CODE_OPERATION_NOT_NEURAL_ENGINE_SUPPORTED,
                         H3_ANE_REASON_ELIGIBILITY,
                         "operation is not Neural Engine supported");
            h3_ane_diagnostic *diagnostic = &ane->diagnostic;
            snprintf(diagnostic->operation, sizeof(diagnostic->operation), "%s",
                     usage->name);
            diagnostic->has_operation = 1;
            diagnostic->supported_devices = usage->supported_devices;
            diagnostic->has_supported_devices = 1;
            diagnostic->preferred_device = usage->preferred_device;
            diagnostic->has_preferred_device = 1;
            mark_unavailable(ane, H3_ANE_REASON_ELIGIBILITY, error, error_size,
                             "Core ML operation is not Neural Engine eligible");
            free(operations);
            return ane;
        }
    }
    free(operations);
    ane->stats.last_reason = H3_ANE_REASON_NONE;
    set_error(error, error_size, "");
    return ane;
}

h3_ane *h3_ane_create(const char *model_path,
                      const h3_ane_contract *contract, int shadow,
                      char *error, size_t error_size) {
    @autoreleasepool {
        return create_impl(model_path, contract, shadow, 0, error, error_size);
    }
}

h3_ane *h3_ane_create_authorized(const char *model_path,
                                 const h3_ane_contract *contract, int shadow,
                                 char *error, size_t error_size) {
    @autoreleasepool {
        return create_impl(model_path, contract, shadow, 1, error, error_size);
    }
}

void h3_ane_stats_snapshot(h3_ane *ane, h3_ane_stats *stats) {
    if (!stats) return;
    if (!ane) {
        memset(stats, 0, sizeof(*stats));
        stats->last_reason = H3_ANE_REASON_DISABLED;
        return;
    }
    pthread_mutex_lock(&ane->prediction_mutex);
    *stats = ane->stats;
    pthread_mutex_unlock(&ane->prediction_mutex);
}

void h3_ane_diagnostic_snapshot(h3_ane *ane,
                                h3_ane_diagnostic *diagnostic) {
    if (!diagnostic) return;
    if (!ane) {
        memset(diagnostic, 0, sizeof(*diagnostic));
        return;
    }
    pthread_mutex_lock(&ane->prediction_mutex);
    *diagnostic = ane->diagnostic;
    pthread_mutex_unlock(&ane->prediction_mutex);
}

void h3_ane_inventory_snapshot(h3_ane *ane,
                               h3_ane_inventory_summary *summary) {
    if (!summary) return;
    if (!ane) {
        memset(summary, 0, sizeof(*summary));
        return;
    }
    pthread_mutex_lock(&ane->prediction_mutex);
    *summary = ane->inventory;
    pthread_mutex_unlock(&ane->prediction_mutex);
}

void h3_ane_record_fallback(h3_ane *ane, h3_ane_reason reason,
                            h3_ane_stats *stats) {
    if (!ane) {
        if (stats) {
            memset(stats, 0, sizeof(*stats));
            stats->attempts = 1;
            stats->fallbacks = 1;
            stats->last_reason = reason;
        }
        return;
    }
    pthread_mutex_lock(&ane->prediction_mutex);
    ane->stats.attempts++;
    ane->stats.fallbacks++;
    ane->stats.last_reason = reason;
    ane->stats.input_seconds = 0.0;
    ane->stats.prediction_seconds = 0.0;
    ane->stats.output_seconds = 0.0;
    if (stats) *stats = ane->stats;
    pthread_mutex_unlock(&ane->prediction_mutex);
}

void h3_ane_record_current_attempt_fallback(h3_ane *ane,
                                            h3_ane_reason reason,
                                            h3_ane_stats *stats) {
    if (!ane) {
        h3_ane_record_fallback(NULL, reason, stats);
        return;
    }
    pthread_mutex_lock(&ane->prediction_mutex);
    ane->stats.fallbacks++;
    ane->stats.last_reason = reason;
    if (stats) *stats = ane->stats;
    pthread_mutex_unlock(&ane->prediction_mutex);
}

int h3_ane_is_shadow(const h3_ane *ane) {
    @autoreleasepool {
        return ane ? ane->stats.shadow : 0;
    }
}

static int prediction_failure(h3_ane *ane, h3_ane_reason reason,
                              h3_ane_stats *stats, char *error,
                              size_t error_size, const char *message) {
    ane->stats.fallbacks++;
    ane->stats.last_reason = reason;
    if (stats) *stats = ane->stats;
    set_error(error, error_size, message);
    return 0;
}

static int predict_impl(h3_ane *ane, const float *input, size_t input_count,
                        float *output, size_t output_count, h3_ane_stats *stats,
                        char *error, size_t error_size) {
    if (!ane) {
        set_error(error, error_size, "ANE handle is null");
        return 0;
    }
    ane->stats.input_seconds = 0.0;
    ane->stats.prediction_seconds = 0.0;
    ane->stats.output_seconds = 0.0;
    ane->stats.attempts++;
    if (ane->unavailable_reason != H3_ANE_REASON_NONE)
        return prediction_failure(ane, ane->unavailable_reason, stats, error,
                                  error_size, "ANE backend is unavailable");
    const size_t expected = (size_t)1 * 1 * 256 * 256 * 128;
    if (!input || !output || input_count != expected || output_count != expected)
        record_first(ane, H3_ANE_STAGE_INPUT, H3_ANE_CODE_INPUT_SHAPE_MISMATCH,
                     H3_ANE_REASON_SHAPE, "ANE boundary shape is invalid");
    if (!input || !output || input_count != expected || output_count != expected)
        return prediction_failure(ane, H3_ANE_REASON_SHAPE, stats, error,
                                  error_size, "ANE boundary shape is invalid");
    float *scratch = malloc(output_count * sizeof(*scratch));
    if (!scratch)
        record_first(ane, H3_ANE_STAGE_OUTPUT, H3_ANE_CODE_ALLOCATION_FAILED,
                     H3_ANE_REASON_PREDICTION, "ANE output allocation failed");
    if (!scratch)
        return prediction_failure(ane, H3_ANE_REASON_PREDICTION, stats, error,
                                  error_size, "cannot allocate ANE output");
    double start = monotonic_seconds();
    int result = ane->predict(ane->opaque, input, input_count, scratch,
                              output_count, &ane->diagnostic);
    double elapsed = monotonic_seconds() - start;
    if (ane->real_backend) {
        H3ANERealBackend *backend = (__bridge H3ANERealBackend *)ane->opaque;
        ane->stats.input_seconds = backend.inputSeconds;
        ane->stats.prediction_seconds = backend.predictionSeconds;
        ane->stats.output_seconds = backend.outputSeconds;
    } else {
        ane->stats.prediction_seconds = elapsed;
    }
    if (result <= 0) {
        record_first(ane, H3_ANE_STAGE_PREDICTION,
                     H3_ANE_CODE_PREDICTION_FAILED,
                     H3_ANE_REASON_PREDICTION, "Core ML prediction failed");
        free(scratch);
        return prediction_failure(
            ane, callback_reason(result, H3_ANE_REASON_PREDICTION), stats,
            error, error_size, "Core ML prediction failed");
    }
    for (size_t index = 0; index < output_count; index++) {
        if (!isfinite(scratch[index])) {
            record_first(ane, H3_ANE_STAGE_OUTPUT,
                         H3_ANE_CODE_OUTPUT_NONFINITE,
                         H3_ANE_REASON_NONFINITE,
                         "Core ML output is non-finite");
            free(scratch);
            return prediction_failure(ane, H3_ANE_REASON_NONFINITE, stats,
                                      error, error_size,
                                      "Core ML output is non-finite");
        }
    }
    memcpy(output, scratch, output_count * sizeof(*output));
    free(scratch);
    ane->stats.predictions++;
    ane->stats.last_reason = H3_ANE_REASON_NONE;
    if (stats) *stats = ane->stats;
    set_error(error, error_size, "");
    return 1;
}

int h3_ane_predict(h3_ane *ane, const float *input, size_t input_count,
                   float *output, size_t output_count, h3_ane_stats *stats,
                   char *error, size_t error_size) {
    @autoreleasepool {
        if (!ane) return predict_impl(ane, input, input_count, output,
                                      output_count, stats, error, error_size);
        pthread_mutex_lock(&ane->prediction_mutex);
        if (ane->real_backend) {
            H3ANERealBackend *backend = (__bridge H3ANERealBackend *)ane->opaque;
            backend.inputSeconds = 0.0;
            backend.predictionSeconds = 0.0;
            backend.outputSeconds = 0.0;
        }
        int result = predict_impl(ane, input, input_count, output, output_count,
                                  stats, error, error_size);
        pthread_mutex_unlock(&ane->prediction_mutex);
        return result;
    }
}

void h3_ane_free(h3_ane *ane) {
    @autoreleasepool {
        if (!ane) return;
        pthread_mutex_lock(&ane->prediction_mutex);
        if (ane->backend_loaded && ane->free_backend)
            ane->free_backend(ane->opaque);
        else if (ane->real_backend && ane->opaque)
            real_free(ane->opaque);
        pthread_mutex_unlock(&ane->prediction_mutex);
        pthread_mutex_destroy(&ane->prediction_mutex);
        free(ane);
    }
}
