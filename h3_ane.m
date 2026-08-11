#import "h3_ane.h"

#import <CoreML/CoreML.h>
#import <Foundation/Foundation.h>

#include <dispatch/dispatch.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { H3_ANE_MAX_OPERATIONS = 256 };

typedef int (*h3_ane_load_fn)(void *);
typedef int (*h3_ane_plan_fn)(void *, h3_ane_operation_usage *, size_t *);
typedef int (*h3_ane_predict_fn)(void *, const float *, size_t, float *, size_t);
typedef void (*h3_ane_free_fn)(void *);

struct h3_ane {
    h3_ane_load_fn load;
    h3_ane_plan_fn plan;
    h3_ane_predict_fn predict;
    h3_ane_free_fn free_backend;
    void *opaque;
    h3_ane_stats stats;
    h3_ane_reason unavailable_reason;
    int backend_loaded;
    int real_backend;
};

@interface H3ANERealBackend : NSObject
@property(nonatomic, copy) NSString *modelPath;
@property(nonatomic, strong) MLModel *model;
@property(nonatomic, copy) NSString *inputName;
@property(nonatomic, copy) NSString *outputName;
@property(nonatomic) double inputSeconds;
@property(nonatomic) double predictionSeconds;
@property(nonatomic) double outputSeconds;
@end

@implementation H3ANERealBackend
@end

#ifdef H3_ANE_TESTING
static h3_ane_test_backend h3_test_backend;
static int h3_test_backend_set;

void h3_ane_test_set_backend(const h3_ane_test_backend *backend) {
    if (backend) {
        h3_test_backend = *backend;
        h3_test_backend_set = 1;
    } else {
        memset(&h3_test_backend, 0, sizeof(h3_test_backend));
        h3_test_backend_set = 0;
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

static int real_load(void *opaque) {
    H3ANERealBackend *backend = (__bridge H3ANERealBackend *)opaque;
    @try {
        NSURL *url = [NSURL fileURLWithPath:backend.modelPath];
        MLModelConfiguration *configuration = [[MLModelConfiguration alloc] init];
        configuration.computeUnits = MLComputeUnitsCPUAndNeuralEngine;
        NSError *error = nil;
        MLModel *model = [MLModel modelWithContentsOfURL:url
                                          configuration:configuration
                                                  error:&error];
        if (!model || error) return 0;
        NSDictionary<NSString *, MLFeatureDescription *> *inputs =
            model.modelDescription.inputDescriptionsByName;
        NSDictionary<NSString *, MLFeatureDescription *> *outputs =
            model.modelDescription.outputDescriptionsByName;
        if (inputs.count != 1 || outputs.count != 1)
            return -(int)H3_ANE_REASON_SHAPE;
        NSString *inputName = inputs.allKeys.firstObject;
        NSString *outputName = outputs.allKeys.firstObject;
        MLFeatureDescription *input = inputs[inputName];
        MLFeatureDescription *output = outputs[outputName];
        if (input.type != MLFeatureTypeMultiArray ||
            output.type != MLFeatureTypeMultiArray)
            return -(int)H3_ANE_REASON_DTYPE;
        MLMultiArrayConstraint *inputConstraint = input.multiArrayConstraint;
        MLMultiArrayConstraint *outputConstraint = output.multiArrayConstraint;
        if (inputConstraint.dataType != MLMultiArrayDataTypeFloat32 ||
            outputConstraint.dataType != MLMultiArrayDataTypeFloat32)
            return -(int)H3_ANE_REASON_DTYPE;
        NSArray<NSNumber *> *shape = @[@1, @1, @256, @256, @128];
        if (![inputConstraint.shape isEqualToArray:shape] ||
            ![outputConstraint.shape isEqualToArray:shape])
            return -(int)H3_ANE_REASON_SHAPE;
        backend.model = model;
        backend.inputName = inputName;
        backend.outputName = outputName;
        return 1;
    } @catch (__unused NSException *exception) {
        return 0;
    }
}

static int append_operations(MLComputePlan *plan,
                             NSArray<MLModelStructureProgramOperation *> *source,
                             h3_ane_operation_usage *operations,
                             size_t capacity, size_t *count)
    API_AVAILABLE(macos(14.4)) {
    for (MLModelStructureProgramOperation *operation in source) {
        if (*count >= capacity) return 0;
        h3_ane_operation_usage *usage = &operations[*count];
        memset(usage, 0, sizeof(*usage));
        const char *name = operation.operatorName.UTF8String;
        snprintf(usage->name, sizeof(usage->name), "%s",
                 name ? name : "unknown");
        usage->is_constant = [operation.operatorName isEqualToString:@"const"];
        MLComputePlanDeviceUsage *deviceUsage =
            [plan computeDeviceUsageForMLProgramOperation:operation];
        for (id<MLComputeDeviceProtocol> device in
             deviceUsage.supportedComputeDevices)
            usage->supported_devices |= device_bit(device);
        usage->preferred_device = device_bit(deviceUsage.preferredComputeDevice);
        (*count)++;
        for (MLModelStructureProgramBlock *block in operation.blocks) {
            if (!append_operations(plan, block.operations, operations, capacity,
                                   count))
                return 0;
        }
    }
    return 1;
}

static int real_plan(void *opaque, h3_ane_operation_usage *operations,
                     size_t *operation_count) {
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
            dispatch_semaphore_wait(semaphore, DISPATCH_TIME_FOREVER);
            MLModelStructureProgram *program = loadedPlan.modelStructure.program;
            MLModelStructureProgramFunction *main = program.functions[@"main"];
            if (!loadedPlan || !program || !main) return 0;
            size_t capacity = *operation_count;
            size_t count = 0;
            if (!append_operations(loadedPlan, main.block.operations, operations,
                                   capacity, &count))
                return 0;
            *operation_count = count;
            return count > 0;
        } @catch (__unused NSException *exception) {
            return 0;
        }
    }
    return -(int)H3_ANE_REASON_OS;
}

static int real_predict(void *opaque, const float *input, size_t input_count,
                        float *output, size_t output_count) {
    H3ANERealBackend *backend = (__bridge H3ANERealBackend *)opaque;
    @try {
        NSError *error = nil;
        NSArray<NSNumber *> *shape = @[@1, @1, @256, @256, @128];
        double start = monotonic_seconds();
        MLMultiArray *inputArray = [[MLMultiArray alloc]
            initWithShape:shape dataType:MLMultiArrayDataTypeFloat32 error:&error];
        if (!inputArray || error || (size_t)inputArray.count != input_count)
            return -(int)H3_ANE_REASON_SHAPE;
        memcpy(inputArray.dataPointer, input, input_count * sizeof(*input));
        MLDictionaryFeatureProvider *provider = [[MLDictionaryFeatureProvider alloc]
            initWithDictionary:@{backend.inputName:
                                     [MLFeatureValue featureValueWithMultiArray:
                                                         inputArray]}
                           error:&error];
        if (!provider || error) return 0;
        backend.inputSeconds = monotonic_seconds() - start;
        start = monotonic_seconds();
        id<MLFeatureProvider> prediction =
            [backend.model predictionFromFeatures:provider error:&error];
        backend.predictionSeconds = monotonic_seconds() - start;
        if (!prediction || error) return 0;
        start = monotonic_seconds();
        MLFeatureValue *value = [prediction featureValueForName:backend.outputName];
        MLMultiArray *array = value.multiArrayValue;
        if (!array || array.dataType != MLMultiArrayDataTypeFloat32)
            return -(int)H3_ANE_REASON_DTYPE;
        if ((size_t)array.count != output_count)
            return -(int)H3_ANE_REASON_SHAPE;
        memcpy(output, array.dataPointer, output_count * sizeof(*output));
        backend.outputSeconds = monotonic_seconds() - start;
        return 1;
    } @catch (__unused NSException *exception) {
        return 0;
    }
}

static void real_free(void *opaque) {
    (void)CFBridgingRelease(opaque);
}

static void initialize_real_backend(h3_ane *ane, const char *model_path) {
    H3ANERealBackend *backend = [[H3ANERealBackend alloc] init];
    backend.modelPath = [NSString stringWithUTF8String:model_path];
    ane->load = real_load;
    ane->plan = real_plan;
    ane->predict = real_predict;
    ane->free_backend = real_free;
    ane->opaque = (__bridge_retained void *)backend;
    ane->real_backend = 1;
}

static void mark_unavailable(h3_ane *ane, h3_ane_reason reason,
                             char *error, size_t error_size,
                             const char *message) {
    ane->unavailable_reason = reason;
    ane->stats.last_reason = reason;
    set_error(error, error_size, message);
}

h3_ane *h3_ane_create(const char *model_path,
                      const h3_ane_contract *contract, int shadow,
                      char *error, size_t error_size) {
    h3_ane *ane = calloc(1, sizeof(*ane));
    if (!ane) {
        set_error(error, error_size, "cannot allocate ANE handle");
        return NULL;
    }
    ane->stats.shadow = shadow != 0;
    const char *enabled_path = getenv("H3_ANE_MODEL");
    if (!model_path || !*model_path || !enabled_path || !*enabled_path ||
        strcmp(model_path, enabled_path) != 0) {
        mark_unavailable(ane, H3_ANE_REASON_DISABLED, error, error_size,
                         "ANE backend is disabled");
        return ane;
    }
    if (![[NSProcessInfo processInfo] isOperatingSystemAtLeastVersion:
            (NSOperatingSystemVersion){14, 4, 0}]) {
        mark_unavailable(ane, H3_ANE_REASON_OS, error, error_size,
                         "ANE backend requires macOS 14.4 or later");
        return ane;
    }
    h3_ane_reason contract_reason = validate_contract(contract);
    if (contract_reason != H3_ANE_REASON_NONE) {
        mark_unavailable(ane, contract_reason, error, error_size,
                         "ANE model contract is incompatible");
        return ane;
    }
    if (!shadow) {
        char digest[65];
        if (!h3_ane_sha256_directory(model_path, digest, error, error_size)) {
            mark_unavailable(ane, H3_ANE_REASON_FINGERPRINT, error, error_size,
                             "cannot fingerprint compiled ANE model");
            return ane;
        }
        size_t receipt_size = strlen(model_path) +
                              strlen(".qualification.json") + 1;
        char *receipt_path = malloc(receipt_size);
        if (!receipt_path) {
            free(ane);
            set_error(error, error_size, "cannot allocate receipt path");
            return NULL;
        }
        snprintf(receipt_path, receipt_size, "%s.qualification.json", model_path);
        h3_ane_receipt receipt;
        int loaded = h3_ane_receipt_load(receipt_path, &receipt, error, error_size);
        free(receipt_path);
        if (!loaded) {
            mark_unavailable(ane, H3_ANE_REASON_RECEIPT, error, error_size,
                             "ANE qualification receipt is missing or invalid");
            return ane;
        }
        if (strcmp(receipt.source_sha256, contract->source_sha256) != 0) {
            mark_unavailable(ane, H3_ANE_REASON_FINGERPRINT, error, error_size,
                             "ANE source fingerprint does not match");
            return ane;
        }
        if (!h3_ane_receipt_validate(contract, &receipt, digest, error,
                                     error_size)) {
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
    } else
#endif
    {
        initialize_real_backend(ane, model_path);
    }

    if (!ane->load || !ane->plan || !ane->predict || !ane->free_backend) {
        mark_unavailable(ane, H3_ANE_REASON_LOAD, error, error_size,
                         "ANE backend is incomplete");
        return ane;
    }
    double start = monotonic_seconds();
    int load_result = ane->load(ane->opaque);
    ane->stats.load_seconds = monotonic_seconds() - start;
    if (load_result <= 0) {
        mark_unavailable(ane, callback_reason(load_result, H3_ANE_REASON_LOAD),
                         error, error_size, "Core ML model load failed");
        return ane;
    }
    ane->backend_loaded = 1;
    h3_ane_operation_usage operations[H3_ANE_MAX_OPERATIONS];
    size_t operation_count = H3_ANE_MAX_OPERATIONS;
    int plan_result = ane->plan(ane->opaque, operations, &operation_count);
    if (plan_result <= 0 || operation_count == 0 ||
        operation_count > H3_ANE_MAX_OPERATIONS) {
        mark_unavailable(ane,
                         callback_reason(plan_result,
                                         H3_ANE_REASON_ELIGIBILITY),
                         error, error_size, "Core ML compute plan is unavailable");
        return ane;
    }
    int trace = getenv("H3_ANE_TRACE") &&
                strcmp(getenv("H3_ANE_TRACE"), "1") == 0;
    for (size_t index = 0; index < operation_count; index++) {
        h3_ane_operation_usage *usage = &operations[index];
        ane->stats.preferred_device |= usage->preferred_device;
        if (trace) {
            fprintf(stderr,
                    "h3-ane operation=%s constant=%d supported=0x%x "
                    "preferred=0x%x\n",
                    usage->name, usage->is_constant, usage->supported_devices,
                    usage->preferred_device);
        }
        if (!usage->is_constant &&
            !(usage->supported_devices & H3_ANE_DEVICE_NEURAL_ENGINE)) {
            mark_unavailable(ane, H3_ANE_REASON_ELIGIBILITY, error, error_size,
                             "Core ML operation is not Neural Engine eligible");
            return ane;
        }
    }
    ane->stats.last_reason = H3_ANE_REASON_NONE;
    set_error(error, error_size, "");
    return ane;
}

int h3_ane_is_shadow(const h3_ane *ane) {
    return ane ? ane->stats.shadow : 0;
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

int h3_ane_predict(h3_ane *ane, const float *input, size_t input_count,
                   float *output, size_t output_count, h3_ane_stats *stats,
                   char *error, size_t error_size) {
    if (!ane) {
        set_error(error, error_size, "ANE handle is null");
        return 0;
    }
    ane->stats.attempts++;
    if (ane->unavailable_reason != H3_ANE_REASON_NONE)
        return prediction_failure(ane, ane->unavailable_reason, stats, error,
                                  error_size, "ANE backend is unavailable");
    const size_t expected = (size_t)1 * 1 * 256 * 256 * 128;
    if (!input || !output || input_count != expected || output_count != expected)
        return prediction_failure(ane, H3_ANE_REASON_SHAPE, stats, error,
                                  error_size, "ANE boundary shape is invalid");
    float *scratch = malloc(output_count * sizeof(*scratch));
    if (!scratch)
        return prediction_failure(ane, H3_ANE_REASON_PREDICTION, stats, error,
                                  error_size, "cannot allocate ANE output");
    double start = monotonic_seconds();
    int result = ane->predict(ane->opaque, input, input_count, scratch,
                              output_count);
    double elapsed = monotonic_seconds() - start;
    if (ane->real_backend) {
        H3ANERealBackend *backend = (__bridge H3ANERealBackend *)ane->opaque;
        ane->stats.input_seconds += backend.inputSeconds;
        ane->stats.prediction_seconds += backend.predictionSeconds;
        ane->stats.output_seconds += backend.outputSeconds;
    } else {
        ane->stats.prediction_seconds += elapsed;
    }
    if (result <= 0) {
        free(scratch);
        return prediction_failure(
            ane, callback_reason(result, H3_ANE_REASON_PREDICTION), stats,
            error, error_size, "Core ML prediction failed");
    }
    for (size_t index = 0; index < output_count; index++) {
        if (!isfinite(scratch[index])) {
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

void h3_ane_free(h3_ane *ane) {
    if (!ane) return;
    if (ane->backend_loaded && ane->free_backend)
        ane->free_backend(ane->opaque);
    else if (ane->real_backend && ane->opaque)
        real_free(ane->opaque);
    free(ane);
}
