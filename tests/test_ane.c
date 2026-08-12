#include "h3_ane_receipt.h"
#include "h3_ane.h"
#include "h3_ane_dispatch.h"
#include "h3_ane_internal.h"
#include "h3_video_encoder.h"

#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

int h3_ane_test_validate_metadata(const char *const values[8],
                                  const h3_ane_contract *contract);

static void die(const char *message) {
    fprintf(stderr, "FAIL tests/test_ane.c: %s\n", message);
    exit(1);
}

static void require(int condition, const char *message) {
    if (!condition) die(message);
}

static double test_monotonic_seconds(void) {
    struct timespec value;
    require(clock_gettime(CLOCK_MONOTONIC_RAW, &value) == 0,
            "cannot read monotonic clock");
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

static void write_bytes(const char *path, const void *data, size_t size) {
    FILE *file = fopen(path, "wb");
    require(file != NULL, "cannot create fixture file");
    require(fwrite(data, 1, size, file) == size, "cannot write fixture file");
    require(fclose(file) == 0, "cannot close fixture file");
}

static void make_path(char out[512], const char *directory, const char *name) {
    int written = snprintf(out, 512, "%s/%s", directory, name);
    require(written > 0 && written < 512, "fixture path is too long");
}

static void make_directory(char path[512], const char *root, const char *name) {
    make_path(path, root, name);
    require(mkdir(path, 0700) == 0, "cannot create fixture directory");
}

static void write_safetensors(const char *path, uint8_t first, uint8_t second) {
    static const char json[] =
        "{\"a\":{\"dtype\":\"U8\",\"shape\":[1],\"data_offsets\":[0,1]},"
        "\"b\":{\"dtype\":\"U8\",\"shape\":[1],\"data_offsets\":[1,2]}}";
    uint64_t header_size = sizeof(json) - 1;
    FILE *file = fopen(path, "wb");
    require(file != NULL, "cannot create safetensors fixture");
    require(fwrite(&header_size, sizeof(header_size), 1, file) == 1,
            "cannot write safetensors length");
    require(fwrite(json, 1, (size_t)header_size, file) == header_size,
            "cannot write safetensors header");
    require(fputc(first, file) != EOF && fputc(second, file) != EOF,
            "cannot write safetensors data");
    require(fclose(file) == 0, "cannot close safetensors fixture");
}

static const char *valid_receipt_json(const char *model, const char *source) {
    static char json[1024];
    int written = snprintf(
        json, sizeof(json),
        "{\"version\":1,\"model_sha256\":\"%s\","
        "\"source_sha256\":\"%s\",\"test_vector\":\"ane-v1-seed-7\","
        "\"qualified_at\":\"2026-08-11T00:00:00Z\","
        "\"max_abs\":0.001,\"relative_l2\":0.01,\"status\":\"passed\"}",
        model, source);
    require(written > 0 && (size_t)written < sizeof(json),
            "receipt JSON is too long");
    return json;
}

static h3_ane_contract valid_contract(const char *source) {
    h3_ane_contract contract = {
        .version = 1,
        .variant = "FL2VA",
        .block_level = 0,
        .block_index = 0,
        .weight_prefix = "encoder.down.0.block.0",
        .boundary_dtype = H3_ANE_DTYPE_F32,
        .shape = {1, 1, 256, 256, 128},
    };
    memcpy(contract.source_sha256, source, 65);
    return contract;
}

static void test_directory_digest(const char *root) {
    char first[512], second[512], nested[512], path[512];
    make_directory(first, root, "compiled-a");
    make_directory(second, root, "compiled-b");
    make_directory(nested, first, "nested");
    make_path(path, first, "z.bin");
    write_bytes(path, "zeta", 4);
    make_path(path, nested, "a.bin");
    write_bytes(path, "alpha", 5);
    make_path(path, second, "nested");
    require(mkdir(path, 0700) == 0, "cannot create second nested directory");
    make_path(path, second, "nested/a.bin");
    write_bytes(path, "alpha", 5);
    make_path(path, second, "z.bin");
    write_bytes(path, "zeta", 4);

    char digest_a[65], digest_b[65], changed[65], error[256];
    require(h3_ane_sha256_directory(first, digest_a, error, sizeof(error)), error);
    require(h3_ane_sha256_directory(second, digest_b, error, sizeof(error)), error);
    require(strcmp(digest_a, digest_b) == 0,
            "directory digest depends on enumeration order");
    require(strlen(digest_a) == 64, "directory digest is not SHA-256 hex");

    make_path(path, second, "z.bin");
    write_bytes(path, "Zeta", 4);
    require(h3_ane_sha256_directory(second, changed, error, sizeof(error)), error);
    require(strcmp(digest_a, changed) != 0,
            "directory digest ignores changed file bytes");

    char outside[512], linked[512];
    make_path(outside, root, "outside.bin");
    write_bytes(outside, "secret", 6);
    make_path(linked, first, "escape");
    require(symlink(outside, linked) == 0, "cannot create traversal fixture");
    require(!h3_ane_sha256_directory(first, changed, error, sizeof(error)),
            "directory digest followed a symlink traversal");

    char outside_directory[512], directory_link[512];
    make_directory(outside_directory, root, "outside-directory");
    make_path(path, outside_directory, "payload.bin");
    write_bytes(path, "outside", 7);
    make_path(directory_link, second, "substituted-directory");
    require(symlink(outside_directory, directory_link) == 0,
            "cannot create directory substitution fixture");
    require(!h3_ane_sha256_directory(second, changed, error, sizeof(error)),
            "directory digest followed a substituted directory symlink");
}

static void test_tensor_digest(const char *root) {
    char weights[512], shard[512], error[256];
    make_directory(weights, root, "weights");
    make_path(shard, weights, "model.safetensors");
    write_safetensors(shard, 0x11, 0x22);
    h3_weight_store *store = h3_weight_store_open(weights, error, sizeof(error));
    require(store != NULL, error);
    const char *names[] = {"a", "b"};
    char digest[65], repeated[65], changed[65];
    require(h3_ane_sha256_tensors(store, names, 2, digest, error, sizeof(error)),
            error);
    require(h3_ane_sha256_tensors(store, names, 2, repeated, error,
                                  sizeof(error)), error);
    require(strcmp(digest, repeated) == 0, "tensor digest is not deterministic");
    const char *reversed_names[] = {"b", "a"};
    require(h3_ane_sha256_tensors(store, reversed_names, 2, repeated, error,
                                  sizeof(error)), error);
    require(strcmp(digest, repeated) == 0,
            "tensor digest depends on caller tensor order");
    const char *duplicate_names[] = {"a", "a"};
    require(!h3_ane_sha256_tensors(store, duplicate_names, 2, repeated, error,
                                   sizeof(error)),
            "duplicate tensor name was accepted");
    require(!h3_ane_sha256_tensors(store, (const char *const[]){"missing"}, 1,
                                   changed, error, sizeof(error)),
            "missing tensor was accepted");
    h3_weight_store_free(store);

    write_safetensors(shard, 0x11, 0x23);
    store = h3_weight_store_open(weights, error, sizeof(error));
    require(store != NULL, error);
    require(h3_ane_sha256_tensors(store, names, 2, changed, error, sizeof(error)),
            error);
    require(strcmp(digest, changed) != 0, "tensor digest ignores raw bytes");
    h3_weight_store_free(store);
}

static void test_receipt_load_and_validate(const char *root) {
    static const char source[] =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    static const char model[] =
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    char path[512], error[256];
    make_path(path, root, "receipt.json");
    const char *json = valid_receipt_json(model, source);
    write_bytes(path, json, strlen(json));
    h3_ane_receipt receipt;
    require(h3_ane_receipt_load(path, &receipt, error, sizeof(error)), error);
    h3_ane_contract contract = valid_contract(source);
    require(h3_ane_receipt_validate(&contract, &receipt, model, error,
                                    sizeof(error)), error);

    const char reordered[] =
        "{\"status\":\"passed\",\"relative_l2\":0.01,\"max_abs\":0.001,"
        "\"qualified_at\":\"2026-08-11T00:00:00Z\","
        "\"test_vector\":\"ane-v1-seed-7\","
        "\"source_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
        "\"model_sha256\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\","
        "\"version\":1}";
    write_bytes(path, reordered, sizeof(reordered) - 1);
    require(h3_ane_receipt_load(path, &receipt, error, sizeof(error)),
            "receipt parser depends on JSON field order");

    const char missing[] =
        "{\"version\":1,\"model_sha256\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\"}";
    write_bytes(path, missing, sizeof(missing) - 1);
    require(!h3_ane_receipt_load(path, &receipt, error, sizeof(error)),
            "receipt with missing fields was accepted");

    json = valid_receipt_json(model, source);
    char invalid[1200];
    snprintf(invalid, sizeof(invalid), "%.*s,\"unexpected\":1}",
             (int)strlen(json) - 1, json);
    write_bytes(path, invalid, strlen(invalid));
    require(!h3_ane_receipt_load(path, &receipt, error, sizeof(error)),
            "receipt with unknown field was accepted");

    const char trailing_comma[] =
        "{\"version\":1,"
        "\"model_sha256\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\","
        "\"source_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
        "\"test_vector\":\"ane-v1-seed-7\","
        "\"qualified_at\":\"2026-08-11T00:00:00Z\","
        "\"max_abs\":0.001,\"relative_l2\":0.01,"
        "\"status\":\"passed\",}";
    write_bytes(path, trailing_comma, sizeof(trailing_comma) - 1);
    require(!h3_ane_receipt_load(path, &receipt, error, sizeof(error)),
            "receipt parser accepted a trailing comma");

    const char non_json_number[] =
        "{\"version\":1,"
        "\"model_sha256\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\","
        "\"source_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
        "\"test_vector\":\"ane-v1-seed-7\","
        "\"qualified_at\":\"2026-08-11T00:00:00Z\","
        "\"max_abs\":0x1p-10,\"relative_l2\":0.01,\"status\":\"passed\"}";
    write_bytes(path, non_json_number, sizeof(non_json_number) - 1);
    require(!h3_ane_receipt_load(path, &receipt, error, sizeof(error)),
            "receipt parser accepted a non-JSON hexadecimal number");

    write_bytes(path, valid_receipt_json(model, source),
                strlen(valid_receipt_json(model, source)));
    require(h3_ane_receipt_load(path, &receipt, error, sizeof(error)), error);
    receipt.version = 2;
    require(!h3_ane_receipt_validate(&contract, &receipt, model, error,
                                     sizeof(error)),
            "unknown receipt version was accepted");
    receipt.version = 1;
    receipt.model_sha256[0] = 'g';
    require(!h3_ane_receipt_validate(&contract, &receipt, model, error,
                                     sizeof(error)),
            "malformed digest was accepted");
    memcpy(receipt.model_sha256, model, 65);
    receipt.source_sha256[0] = 'b';
    require(!h3_ane_receipt_validate(&contract, &receipt, model, error,
                                     sizeof(error)),
            "source digest mismatch was accepted");
    memcpy(receipt.source_sha256, source, 65);
    receipt.passed = 0;
    require(!h3_ane_receipt_validate(&contract, &receipt, model, error,
                                     sizeof(error)),
            "failed receipt was accepted");
    receipt.passed = 1;
    receipt.max_abs = 0.002;
    require(!h3_ane_receipt_validate(&contract, &receipt, model, error,
                                     sizeof(error)),
            "max-absolute equality was accepted");
    receipt.max_abs = 0.001;
    receipt.relative_l2 = 0.02;
    require(!h3_ane_receipt_validate(&contract, &receipt, model, error,
                                     sizeof(error)),
            "relative-L2 equality was accepted");
}

static void test_contract_is_exact(void) {
    static const char source[] =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    static const char model[] =
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    h3_ane_contract contract = valid_contract(source);
    h3_ane_receipt receipt = {
        .version = 1,
        .model_sha256 =
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        .source_sha256 =
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        .test_vector = "ane-v1-seed-7",
        .qualified_at = "2026-08-11T00:00:00Z",
        .max_abs = 0.001,
        .relative_l2 = 0.01,
        .passed = 1,
    };
    char error[256];
    require(h3_ane_receipt_validate(&contract, &receipt, model, error,
                                    sizeof(error)), error);

    h3_ane_contract changed = contract;
    memcpy(changed.variant, "Ref2VA", 7);
    require(!h3_ane_receipt_validate(&changed, &receipt, model, error,
                                     sizeof(error)),
            "non-FL2VA contract was accepted");
    changed = contract;
    changed.block_level = 1;
    require(!h3_ane_receipt_validate(&changed, &receipt, model, error,
                                     sizeof(error)),
            "nonzero block level was accepted");
    changed = contract;
    changed.block_index = 1;
    require(!h3_ane_receipt_validate(&changed, &receipt, model, error,
                                     sizeof(error)),
            "nonzero block index was accepted");
    changed = contract;
    memcpy(changed.weight_prefix, "encoder.down.0.block.1", 23);
    require(!h3_ane_receipt_validate(&changed, &receipt, model, error,
                                     sizeof(error)),
            "wrong weight prefix was accepted");
    for (size_t dimension = 0; dimension < 5; dimension++) {
        changed = contract;
        changed.shape[dimension]++;
        require(!h3_ane_receipt_validate(&changed, &receipt, model, error,
                                         sizeof(error)),
                "wrong fixed boundary shape was accepted");
    }
}

static void test_compiled_directory_receipt_integration(const char *root) {
    static const char source[] =
        "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
    char compiled[512], artifact[512], receipt_path[512];
    char model_digest[65], changed_digest[65], error[256];
    make_directory(compiled, root, "compiled-integration");
    make_path(artifact, compiled, "model.mil");
    write_bytes(artifact, "compiled-model-v1", 17);
    require(h3_ane_sha256_directory(compiled, model_digest, error,
                                    sizeof(error)), error);
    make_path(receipt_path, root, "integration-receipt.json");
    const char *json = valid_receipt_json(model_digest, source);
    write_bytes(receipt_path, json, strlen(json));
    h3_ane_receipt receipt;
    h3_ane_contract contract = valid_contract(source);
    require(h3_ane_receipt_load(receipt_path, &receipt, error, sizeof(error)),
            error);
    require(h3_ane_receipt_validate(&contract, &receipt, model_digest, error,
                                    sizeof(error)), error);

    write_bytes(artifact, "compiled-model-v2", 17);
    require(h3_ane_sha256_directory(compiled, changed_digest, error,
                                    sizeof(error)), error);
    require(!h3_ane_receipt_validate(&contract, &receipt, changed_digest, error,
                                     sizeof(error)),
            "receipt remained valid after compiled bytes changed");
}

typedef struct {
    int load_result;
    int plan_result;
    int predict_result;
    int load_count;
    int plan_count;
    int predict_count;
    int free_count;
    int emit_nonfinite;
    int plan_never_completes;
    int predict_delay_us;
    const char *predict_block_ready_path;
    int active_predictions;
    int max_active_predictions;
    h3_ane_operation_usage operations[3];
    size_t operation_count;
} fake_ane_backend;

static int fake_load(void *opaque, h3_ane_diagnostic *diagnostic) {
    fake_ane_backend *fake = opaque;
    fake->load_count++;
    if (!fake->load_result)
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_LOAD,
                                       H3_ANE_CODE_MODEL_LOAD_FAILED,
                                       H3_ANE_REASON_LOAD,
                                       "Core ML model load failed");
    return fake->load_result;
}

static int fake_plan(void *opaque, h3_ane_operation_usage *operations,
                     size_t *operation_count, h3_ane_diagnostic *diagnostic) {
    fake_ane_backend *fake = opaque;
    fake->plan_count++;
    if (fake->plan_never_completes) {
        for (;;) pause();
    }
    if (!fake->plan_result) {
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_COMPUTE_PLAN,
                                       H3_ANE_CODE_PLAN_LOAD_FAILED,
                                       H3_ANE_REASON_ELIGIBILITY,
                                       "Core ML compute plan load failed");
        return 0;
    }
    require(*operation_count >= fake->operation_count,
            "bridge did not provide enough operation storage");
    memcpy(operations, fake->operations,
           fake->operation_count * sizeof(*operations));
    *operation_count = fake->operation_count;
    return fake->plan_result;
}

static int fake_predict(void *opaque, const float *input, size_t input_count,
                        float *output, size_t output_count,
                        h3_ane_diagnostic *diagnostic) {
    fake_ane_backend *fake = opaque;
    fake->predict_count++;
    fake->active_predictions++;
    if (fake->active_predictions > fake->max_active_predictions)
        fake->max_active_predictions = fake->active_predictions;
    if (fake->predict_delay_us > 0)
        usleep((useconds_t)fake->predict_delay_us);
    if (fake->predict_block_ready_path) {
        write_bytes(fake->predict_block_ready_path, "ready\n", 6);
        for (;;) pause();
    }
    if (!fake->predict_result) {
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_PREDICTION,
                                       H3_ANE_CODE_PREDICTION_FAILED,
                                       H3_ANE_REASON_PREDICTION,
                                       "Core ML prediction failed");
        fake->active_predictions--;
        return 0;
    }
    require(input != output, "prediction reused caller input storage");
    require(input_count == output_count, "fake prediction count mismatch");
    for (size_t index = 0; index < output_count; index++)
        output[index] = input[index] + 1.0f;
    if (fake->emit_nonfinite) output[output_count - 1] = NAN;
    fake->active_predictions--;
    return fake->predict_result;
}

static void fake_free(void *opaque) {
    fake_ane_backend *fake = opaque;
    fake->free_count++;
}

static fake_ane_backend valid_fake_backend(void) {
    fake_ane_backend fake = {
        .load_result = 1,
        .plan_result = 1,
        .predict_result = 1,
        .operations = {
            {.name = "const-weight", .is_constant = 1,
             .supported_devices = H3_ANE_DEVICE_CPU,
             .preferred_device = H3_ANE_DEVICE_CPU},
            {.name = "conv_0", .is_constant = 0,
             .supported_devices = H3_ANE_DEVICE_CPU |
                                  H3_ANE_DEVICE_NEURAL_ENGINE,
             .preferred_device = H3_ANE_DEVICE_NEURAL_ENGINE},
            {.name = "add_0", .is_constant = 0,
             .supported_devices = H3_ANE_DEVICE_CPU |
                                  H3_ANE_DEVICE_NEURAL_ENGINE,
             .preferred_device = H3_ANE_DEVICE_CPU},
        },
        .operation_count = 3,
    };
    return fake;
}

static void install_fake_backend(fake_ane_backend *fake) {
    h3_ane_test_backend backend = {
        .load = fake_load,
        .plan = fake_plan,
        .predict = fake_predict,
        .free = fake_free,
        .opaque = fake,
    };
    h3_ane_test_set_backend(&backend);
}

static void make_qualified_model(const char *root, const char *name,
                                 const char *source, char model_path[512]) {
    char artifact[512], receipt_path[512], digest[65], error[256];
    make_directory(model_path, root, name);
    make_path(artifact, model_path, "model.mil");
    write_bytes(artifact, "runtime-model", 13);
    require(h3_ane_sha256_directory(model_path, digest, error, sizeof(error)),
            error);
    int written = snprintf(receipt_path, sizeof(receipt_path),
                           "%s.qualification.json", model_path);
    require(written > 0 && (size_t)written < sizeof(receipt_path),
            "qualification receipt path is too long");
    const char *json = valid_receipt_json(digest, source);
    write_bytes(receipt_path, json, strlen(json));
}

static h3_ane *create_enabled(const char *model_path,
                              const h3_ane_contract *contract, int shadow,
                              char error[256]) {
    require(setenv("H3_ANE_MODEL", model_path, 1) == 0,
            "cannot enable fake ANE model");
    return h3_ane_create(model_path, contract, shadow, error, 256);
}

static void require_predict_reason(h3_ane *ane, size_t count,
                                   h3_ane_reason expected,
                                   const char *message) {
    float input = 1.0f, output = 0.0f;
    h3_ane_stats stats = {0};
    char error[256];
    require(!h3_ane_predict(ane, &input, count, &output, count, &stats, error,
                            sizeof(error)), message);
    require(stats.last_reason == expected, message);
}

static void test_multiarray_stride_copy(void) {
    const uint32_t shape[5] = {1, 1, 2, 2, 2};
    const ptrdiff_t strides[5] = {16, 16, 8, 4, 1};
    const float contiguous[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    float storage[14] = {0};
    float roundtrip[8] = {0};
    require(h3_ane_test_copy_to_strided(storage, strides, shape, contiguous),
            "noncontiguous MLMultiArray input copy failed");
    require(storage[0] == 1 && storage[1] == 2 &&
                storage[4] == 3 && storage[5] == 4 &&
                storage[8] == 5 && storage[9] == 6 &&
                storage[12] == 7 && storage[13] == 8,
            "noncontiguous MLMultiArray input used linear memcpy");
    require(h3_ane_test_copy_from_strided(roundtrip, storage, strides, shape),
            "noncontiguous MLMultiArray output copy failed");
    require(memcmp(roundtrip, contiguous, sizeof(contiguous)) == 0,
            "noncontiguous MLMultiArray output order changed");
    ptrdiff_t invalid[5] = {16, 16, 8, 4, -1};
    require(!h3_ane_test_copy_from_strided(roundtrip, storage, invalid, shape),
            "negative MLMultiArray stride was accepted");
}

static void test_first_diagnostic_is_immutable(void) {
    h3_ane_diagnostic diagnostic = {0};
    h3_ane_diagnostic_record_first(
        &diagnostic, H3_ANE_STAGE_CONTRACT, H3_ANE_CODE_METADATA_MISSING,
        H3_ANE_REASON_CONTRACT, "creator metadata is missing");
    h3_ane_diagnostic_record_first(
        &diagnostic, H3_ANE_STAGE_PREDICTION, H3_ANE_CODE_PREDICTION_FAILED,
        H3_ANE_REASON_PREDICTION, "later prediction failed");
    require(diagnostic.stage == H3_ANE_STAGE_CONTRACT &&
                diagnostic.code == H3_ANE_CODE_METADATA_MISSING &&
                diagnostic.reason == H3_ANE_REASON_CONTRACT &&
                strcmp(diagnostic.message, "creator metadata is missing") == 0,
            "later failure replaced the first diagnostic");
    h3_ane_diagnostic source = {0};
    h3_ane_diagnostic_record_first(
        &source, H3_ANE_STAGE_OUTPUT, H3_ANE_CODE_OUTPUT_NONFINITE,
        H3_ANE_REASON_NONFINITE, "Core ML output is non-finite");
    h3_ane_diagnostic_merge_first(&diagnostic, &source);
    require(diagnostic.code == H3_ANE_CODE_METADATA_MISSING,
            "merge replaced an existing diagnostic");
    memset(&diagnostic, 0, sizeof(diagnostic));
    h3_ane_diagnostic_merge_first(&diagnostic, &source);
    require(diagnostic.code == H3_ANE_CODE_OUTPUT_NONFINITE,
            "merge did not preserve a source diagnostic");

    char long_message[400];
    memset(long_message, 'x', sizeof(long_message));
    long_message[sizeof(long_message) - 1] = '\0';
    memset(&diagnostic, 0, sizeof(diagnostic));
    h3_ane_diagnostic_record_first(
        &diagnostic, H3_ANE_STAGE_SETUP, H3_ANE_CODE_ALLOCATION_FAILED,
        H3_ANE_REASON_LOAD, long_message);
    require(diagnostic.message[sizeof(diagnostic.message) - 1] == '\0',
            "diagnostic message is not bounded and terminated");
}

static void test_complete_diagnostic_taxonomy(void) {
    for (int stage = H3_ANE_STAGE_NONE; stage <= H3_ANE_STAGE_PUBLICATION;
         stage++) {
        const char *name = h3_ane_stage_name((h3_ane_stage)stage);
        require(name != NULL && *name, "diagnostic stage has no stable name");
    }
    require(h3_ane_stage_name((h3_ane_stage)-1) == NULL,
            "invalid diagnostic stage received a name");
    for (int code = H3_ANE_CODE_NONE;
         code <= H3_ANE_CODE_RECEIPT_WRITE_FAILED; code++) {
        const char *name = h3_ane_code_name((h3_ane_code)code);
        require(name != NULL && *name, "diagnostic code has no stable name");
    }
    require(h3_ane_code_name((h3_ane_code)-1) == NULL,
            "invalid diagnostic code received a name");
}

static void test_diagnostic_code_snapshots(void) {
    static const struct {
        h3_ane_stage stage;
        h3_ane_code code;
        h3_ane_reason reason;
    } cases[] = {
        {H3_ANE_STAGE_SETUP, H3_ANE_CODE_DISABLED, H3_ANE_REASON_DISABLED},
        {H3_ANE_STAGE_ARTIFACT, H3_ANE_CODE_COMPILED_MODEL_UNREADABLE, H3_ANE_REASON_FINGERPRINT},
        {H3_ANE_STAGE_CONTRACT, H3_ANE_CODE_INPUT_DTYPE_MISMATCH, H3_ANE_REASON_DTYPE},
        {H3_ANE_STAGE_RECEIPT, H3_ANE_CODE_RECEIPT_DIGEST_MISMATCH, H3_ANE_REASON_RECEIPT},
        {H3_ANE_STAGE_ELIGIBILITY, H3_ANE_CODE_OPERATION_USAGE_UNKNOWN, H3_ANE_REASON_ELIGIBILITY},
        {H3_ANE_STAGE_OUTPUT, H3_ANE_CODE_OUTPUT_COPY_FAILED, H3_ANE_REASON_SHAPE},
        {H3_ANE_STAGE_PUBLICATION, H3_ANE_CODE_RESULT_WRITE_FAILED, H3_ANE_REASON_RECEIPT},
    };
    for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); index++) {
        h3_ane_diagnostic diagnostic = {0};
        h3_ane_diagnostic_record_first(&diagnostic, cases[index].stage,
                                       cases[index].code, cases[index].reason,
                                       "stable fixture failure");
        require(diagnostic.stage == cases[index].stage &&
                    diagnostic.code == cases[index].code &&
                    h3_ane_stage_name(diagnostic.stage) != NULL &&
                    h3_ane_code_name(diagnostic.code) != NULL,
                "diagnostic fixture did not snapshot exact taxonomy");
    }
}

static size_t capture_create_diagnostic(const char *model_path,
                                        const h3_ane_contract *contract,
                                        int authorized, char output[512]) {
    int descriptors[2];
    require(pipe(descriptors) == 0, "cannot create diagnostic capture pipe");
    int saved = dup(STDERR_FILENO);
    require(saved >= 0 && dup2(descriptors[1], STDERR_FILENO) >= 0,
            "cannot capture ANE diagnostic");
    close(descriptors[1]);
    char error[256];
    h3_ane *ane = authorized ?
        h3_ane_create_authorized(model_path, contract, 0, error, sizeof(error)) :
        h3_ane_create(model_path, contract, 0, error, sizeof(error));
    h3_ane_free(ane);
    fflush(stderr);
    require(dup2(saved, STDERR_FILENO) >= 0, "cannot restore stderr");
    close(saved);
    ssize_t size = read(descriptors[0], output, 511);
    require(size >= 0, "cannot read ANE diagnostic");
    close(descriptors[0]);
    output[size] = '\0';
    return (size_t)size;
}

static void test_runtime_metadata(void) {
    static const char source[] =
        "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
    h3_ane_contract contract = valid_contract(source);
    const char *valid[8] = {
        "1", "FL2VA", "0", "0", "encoder.down.0.block.0", "F32",
        "1,1,256,256,128", source,
    };
    require(h3_ane_test_validate_metadata(valid, &contract) ==
                H3_ANE_REASON_NONE,
            "matching creator-defined metadata was rejected");
    for (size_t index = 0; index < 8; index++) {
        const char *missing[8];
        memcpy(missing, valid, sizeof(missing));
        missing[index] = NULL;
        require(h3_ane_test_validate_metadata(missing, &contract) !=
                    H3_ANE_REASON_NONE,
                "missing creator-defined metadata was accepted");
    }
    const char *malformed[8];
    memcpy(malformed, valid, sizeof(malformed));
    malformed[0] = "01";
    require(h3_ane_test_validate_metadata(malformed, &contract) ==
                H3_ANE_REASON_CONTRACT,
            "malformed metadata version was accepted");
    static const char *mismatches[8] = {
        "2", "Ref2VA", "1", "1", "encoder.down.0.block.1", "F16",
        "1,1,128,128,128",
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    };
    static const h3_ane_reason reasons[8] = {
        H3_ANE_REASON_CONTRACT, H3_ANE_REASON_CONTRACT,
        H3_ANE_REASON_CONTRACT, H3_ANE_REASON_CONTRACT,
        H3_ANE_REASON_CONTRACT, H3_ANE_REASON_DTYPE,
        H3_ANE_REASON_SHAPE, H3_ANE_REASON_FINGERPRINT,
    };
    for (size_t index = 0; index < 8; index++) {
        const char *changed[8];
        memcpy(changed, valid, sizeof(changed));
        changed[index] = mismatches[index];
        require(h3_ane_test_validate_metadata(changed, &contract) ==
                    (int)reasons[index],
                "metadata mismatch returned the wrong stable reason");
    }
}

typedef struct {
    h3_ane *ane;
    const float *input;
    float *output;
    size_t count;
    int result;
} predict_thread;

static void *run_prediction_thread(void *opaque) {
    predict_thread *thread = opaque;
    h3_ane_stats stats;
    char error[256];
    thread->result = h3_ane_predict(thread->ane, thread->input, thread->count,
                                    thread->output, thread->count, &stats,
                                    error, sizeof(error));
    return NULL;
}

static void test_runtime_bridge(const char *root) {
    static const char source[] =
        "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
    char model_path[512], error[256];
    make_qualified_model(root, "runtime-model", source, model_path);
    h3_ane_contract contract = valid_contract(source);
    fake_ane_backend fake = valid_fake_backend();
    install_fake_backend(&fake);

    require(unsetenv("H3_ANE_MODEL") == 0, "cannot clear ANE model setting");
    h3_ane *ane = h3_ane_create(model_path, &contract, 0, error, sizeof(error));
    require(ane != NULL, "default-off create did not return fallback handle");
    require(fake.load_count == 0, "default environment loaded Core ML");
    require_predict_reason(ane, 1, H3_ANE_REASON_DISABLED,
                           "default-off reason was unstable");
    h3_ane_free(ane);
    require(fake.free_count == 0, "disabled handle freed an unloaded backend");

    char diagnostic[512];
    require(setenv("H3_ANE_TRACE", "1", 1) == 0,
            "cannot enable default-off diagnostic capture");
    require(capture_create_diagnostic(model_path, &contract, 0, diagnostic) == 0,
            "default-off ANE run emitted a diagnostic");
    require(unsetenv("H3_ANE_TRACE") == 0,
            "cannot clear default-off diagnostic capture");

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = h3_ane_create_authorized(model_path, &contract, 0, error,
                                   sizeof(error));
    require(ane != NULL && fake.load_count == 1 && fake.plan_count == 1,
            "explicit authorized creation depended on H3_ANE_MODEL");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    fake.load_result = 0;
    install_fake_backend(&fake);
    require(setenv("H3_ANE_MODEL", model_path, 1) == 0 &&
                setenv("H3_PROFILE", "1", 1) == 0,
            "cannot enable configured fallback diagnostic");
    require(capture_create_diagnostic(model_path, &contract, 0, diagnostic) > 0,
            "configured fallback was silent under profiling");
    require(strcmp(diagnostic,
                   "h3-ane fallback reason=load message=Core ML model load failed\n") == 0,
            "configured fallback diagnostic was not concise and stable");
    require(unsetenv("H3_PROFILE") == 0,
            "cannot clear configured fallback profile setting");

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require(ane != NULL, error);
    require(fake.load_count == 1 && fake.plan_count == 1,
            "qualified fake backend did not load and plan exactly once");
    require(!h3_ane_is_shadow(ane), "qualified handle became shadow");
    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    float *input = calloc(count, sizeof(*input));
    float *output = calloc(count, sizeof(*output));
    require(input != NULL && output != NULL, "cannot allocate bridge fixture");
    input[0] = 4.0f;
    h3_ane_stats stats = {0};
    require(h3_ane_predict(ane, input, count, output, count, &stats, error,
                           sizeof(error)), error);
    require(input[0] == 4.0f && output[0] == 5.0f,
            "prediction mutated input or failed to copy separate output");
    require(stats.attempts == 1 && stats.predictions == 1 &&
                stats.fallbacks == 0 && stats.last_reason == H3_ANE_REASON_NONE,
            "successful prediction stats are incorrect");
    require(stats.preferred_device ==
                (H3_ANE_DEVICE_CPU | H3_ANE_DEVICE_NEURAL_ENGINE),
            "preferred placement summary is incorrect");
    require(stats.shadow == 0 && stats.load_seconds >= 0.0 &&
                stats.input_seconds >= 0.0 &&
                stats.prediction_seconds >= 0.0 &&
                stats.output_seconds >= 0.0,
            "timing or mode stats are incorrect");

    fake.predict_result = 0;
    memset(&stats, 0, sizeof(stats));
    require(!h3_ane_predict(ane, input, count, output, count, &stats, error,
                            sizeof(error)),
            "success-then-failure prediction was accepted");
    require(stats.input_seconds == 0.0 && stats.output_seconds == 0.0 &&
                stats.prediction_seconds >= 0.0,
            "failed call inherited timing from the previous prediction");
    h3_ane_free(ane);
    require(fake.free_count == 1, "loaded backend was not freed exactly once");

    char shadow_path[512];
    make_directory(shadow_path, root, "shadow-model");
    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(shadow_path, &contract, 1, error);
    require(ane != NULL && h3_ane_is_shadow(ane),
            "shadow model without receipt did not load");
    memset(&stats, 0, sizeof(stats));
    require(h3_ane_predict(ane, input, count, output, count, &stats, error,
                           sizeof(error)), error);
    require(stats.shadow == 1, "shadow output was marked adoptable");
    h3_ane_free(ane);

    const char *metadata_cases[3][8] = {
        {"1", "FL2VA", "0", "0", "encoder.down.0.block.0", "F32",
         "1,1,256,256,128", NULL},
        {"01", "FL2VA", "0", "0", "encoder.down.0.block.0", "F32",
         "1,1,256,256,128", source},
        {"1", "Ref2VA", "0", "0", "encoder.down.0.block.0", "F32",
         "1,1,256,256,128", source},
    };
    for (size_t mode = 0; mode < 2; mode++) {
        const char *path = mode ? shadow_path : model_path;
        for (size_t metadata_case = 0; metadata_case < 3; metadata_case++) {
            h3_ane_reason reason = (h3_ane_reason)h3_ane_test_validate_metadata(
                metadata_cases[metadata_case], &contract);
            require(reason != H3_ANE_REASON_NONE,
                    "invalid metadata case did not fail validation");
            fake = valid_fake_backend();
            fake.load_result = -(int)reason;
            install_fake_backend(&fake);
            ane = create_enabled(path, &contract, (int)mode, error);
            require_predict_reason(
                ane, 1, reason,
                mode ? "shadow metadata failure was not enforced"
                     : "qualified metadata failure was not enforced");
            h3_ane_free(ane);
        }
    }

    fake = valid_fake_backend();
    fake.plan_never_completes = 1;
    install_fake_backend(&fake);
    double timeout_start = test_monotonic_seconds();
    ane = create_enabled(model_path, &contract, 0, error);
    double timeout_elapsed = test_monotonic_seconds() - timeout_start;
    require(timeout_elapsed < 1.0,
            "never-completing compute plan blocked create indefinitely");
    require_predict_reason(ane, 1, H3_ANE_REASON_ELIGIBILITY,
                           "compute-plan timeout reason was unstable");
    h3_ane_free(ane);

    h3_ane_contract changed = contract;
    changed.block_index = 1;
    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &changed, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_CONTRACT,
                           "contract failure reason was unstable");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    fake.predict_delay_us = 50000;
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    pthread_t first_thread, second_thread;
    predict_thread first = {.ane = ane, .input = input, .output = output,
                            .count = count};
    predict_thread second = first;
    require(pthread_create(&first_thread, NULL, run_prediction_thread, &first) ==
                0,
            "cannot create first prediction thread");
    require(pthread_create(&second_thread, NULL, run_prediction_thread,
                           &second) == 0,
            "cannot create second prediction thread");
    require(pthread_join(first_thread, NULL) == 0 &&
                pthread_join(second_thread, NULL) == 0,
            "cannot join prediction threads");
    require(first.result && second.result && fake.max_active_predictions == 1,
            "single-owner prediction calls were not serialized");
    h3_ane_free(ane);

    changed = contract;
    changed.boundary_dtype = (h3_ane_dtype)99;
    ane = create_enabled(model_path, &changed, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_DTYPE,
                           "dtype failure reason was unstable");
    h3_ane_free(ane);

    h3_ane_contract fingerprint = contract;
    fingerprint.source_sha256[0] = 'e';
    ane = create_enabled(model_path, &fingerprint, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_FINGERPRINT,
                           "fingerprint failure reason was unstable");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    fake.load_result = 0;
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_LOAD,
                           "load failure reason was unstable");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    fake.load_result = -(int)H3_ANE_REASON_OS;
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_OS,
                           "OS failure reason was unstable");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    fake.operations[1].supported_devices = H3_ANE_DEVICE_CPU;
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_ELIGIBILITY,
                           "eligibility failure reason was unstable");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    require(setenv("H3_ANE_TRACE", "1", 1) == 0,
            "cannot enable ANE trace");
    ane = create_enabled(model_path, &contract, 0, error);
    require(ane != NULL, "trace-enabled plan failed");
    h3_ane_free(ane);
    require(unsetenv("H3_ANE_TRACE") == 0, "cannot clear ANE trace");

    fake = valid_fake_backend();
    fake.predict_result = 0;
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require(!h3_ane_predict(ane, input, count, output, count, &stats, error,
                            sizeof(error)),
            "prediction failure was accepted");
    require(stats.last_reason == H3_ANE_REASON_PREDICTION &&
                stats.attempts == 1 && stats.predictions == 0 &&
                stats.fallbacks == 1,
            "prediction failure stats are incorrect");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require_predict_reason(ane, count - 1, H3_ANE_REASON_SHAPE,
                           "shape failure reason was unstable");
    h3_ane_free(ane);

    fake = valid_fake_backend();
    fake.emit_nonfinite = 1;
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    require(!h3_ane_predict(ane, input, count, output, count, &stats, error,
                            sizeof(error)),
            "non-finite prediction was accepted");
    require(stats.last_reason == H3_ANE_REASON_NONFINITE,
            "non-finite failure reason was unstable");
    h3_ane_free(ane);

    char unqualified[512];
    make_directory(unqualified, root, "unqualified-model");
    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(unqualified, &contract, 0, error);
    require_predict_reason(ane, 1, H3_ANE_REASON_RECEIPT,
                           "receipt failure reason was unstable");
    h3_ane_free(ane);

    free(output);
    free(input);
    h3_ane_test_set_backend(NULL);
    unsetenv("H3_ANE_MODEL");
}

typedef struct {
    h3_gpu *gpu;
    h3_gpu_tensor *expected_input;
    h3_gpu_tensor *returned;
    size_t count;
    int calls;
} fake_metal_block;

static h3_gpu_tensor *fake_metal_run(void *opaque,
                                     h3_gpu_tensor *original_input,
                                     char *error, size_t error_size) {
    fake_metal_block *fake = opaque;
    (void)error;
    (void)error_size;
    require(original_input == fake->expected_input,
            "Metal fallback did not receive the original tensor pointer");
    fake->calls++;
    fake->returned = h3_gpu_tensor_new_f32(fake->gpu, fake->count);
    return fake->returned;
}

static void test_dispatch_fallback(const char *root) {
    static const char source[] =
        "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    char model_path[512], error[256];
    make_qualified_model(root, "dispatch-model", source, model_path);
    h3_ane_contract contract = valid_contract(source);
    h3_gpu *gpu = h3_gpu_create("h3_shaders.metal", error, sizeof(error));
    require(gpu != NULL, error);
    float *input_values = calloc(count, sizeof(*input_values));
    require(input_values != NULL, "cannot allocate dispatch input fixture");
    input_values[0] = 4.0f;
    h3_gpu_tensor *input = h3_gpu_tensor_from_f32(gpu, input_values, count);
    require(input != NULL, "cannot create dispatch input tensor");

    fake_ane_backend fake = valid_fake_backend();
    install_fake_backend(&fake);
    h3_ane *ane = create_enabled(model_path, &contract, 0, error);
    require(ane != NULL, error);
    fake_metal_block metal = {
        .gpu = gpu, .expected_input = input, .count = count,
    };
    h3_ane_stats stats = {0};
    h3_gpu_tensor *result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result != NULL && metal.calls == 0,
            "successful non-shadow prediction did not adopt Core ML");
    float first = 0.0f, original = 0.0f;
    require(h3_gpu_tensor_read_f32_range(result, 0, &first, 1) &&
                h3_gpu_tensor_read_f32_range(input, 0, &original, 1),
            "cannot read dispatch result");
    require(first == 5.0f && original == 4.0f,
            "successful dispatch mutated input or returned wrong output");
    require(stats.predictions == 1 && stats.fallbacks == 0 &&
                stats.last_reason == H3_ANE_REASON_NONE,
            "successful dispatch stats are incorrect");
    h3_gpu_tensor_free(result);
    h3_ane_free(ane);

    struct unavailable_case {
        const char *name;
        h3_ane_reason reason;
    } unavailable_cases[] = {
        {"receipt", H3_ANE_REASON_RECEIPT},
        {"fingerprint", H3_ANE_REASON_FINGERPRINT},
        {"load", H3_ANE_REASON_LOAD},
        {"plan", H3_ANE_REASON_ELIGIBILITY},
    };
    for (size_t case_index = 0;
         case_index < sizeof(unavailable_cases) / sizeof(unavailable_cases[0]);
         case_index++) {
        fake = valid_fake_backend();
        h3_ane_contract unavailable_contract = contract;
        const char *unavailable_path = model_path;
        char case_path[512];
        if (unavailable_cases[case_index].reason == H3_ANE_REASON_RECEIPT) {
            make_directory(case_path, root, "dispatch-no-receipt");
            unavailable_path = case_path;
        } else if (unavailable_cases[case_index].reason ==
                   H3_ANE_REASON_FINGERPRINT) {
            unavailable_contract.source_sha256[0] = 'e';
        } else if (unavailable_cases[case_index].reason == H3_ANE_REASON_LOAD) {
            fake.load_result = 0;
        } else {
            fake.operations[1].supported_devices = H3_ANE_DEVICE_CPU;
        }
        install_fake_backend(&fake);
        ane = create_enabled(unavailable_path, &unavailable_contract, 0, error);
        require(ane != NULL, "cannot create unavailable dispatch handle");
        memset(&metal, 0, sizeof(metal));
        metal.gpu = gpu;
        metal.expected_input = input;
        metal.count = count;
        memset(&stats, 0, sizeof(stats));
        result = h3_ane_dispatch_gpu_block(
            ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
            sizeof(error));
        require(result == metal.returned && metal.calls == 1,
                "unavailable handle did not adopt Metal");
        require(stats.attempts == 1 && stats.fallbacks == 1 &&
                    stats.predictions == 0 &&
                    stats.last_reason == unavailable_cases[case_index].reason,
                unavailable_cases[case_index].name);
        require(h3_gpu_tensor_read_f32_range(input, 0, &original, 1) &&
                    original == 4.0f,
                "unavailable handle mutated original input");
        h3_gpu_tensor_free(result);
        h3_ane_free(ane);
    }

    for (int reason = H3_ANE_REASON_DISABLED;
         reason <= H3_ANE_REASON_NONFINITE; reason++) {
        fake = valid_fake_backend();
        if (reason == H3_ANE_REASON_NONFINITE)
            fake.emit_nonfinite = 1;
        else
            fake.predict_result = -reason;
        install_fake_backend(&fake);
        ane = create_enabled(model_path, &contract, 0, error);
        require(ane != NULL, "cannot create forced-failure dispatch handle");
        memset(&metal, 0, sizeof(metal));
        metal.gpu = gpu;
        metal.expected_input = input;
        metal.count = count;
        memset(&stats, 0, sizeof(stats));
        result = h3_ane_dispatch_gpu_block(
            ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
            sizeof(error));
        require(result == metal.returned && metal.calls == 1,
                "forced bridge failure did not adopt Metal fallback");
        require(stats.last_reason == (h3_ane_reason)reason &&
                    stats.fallbacks == 1,
                "forced bridge failure lost its stable stats reason");
        require(h3_gpu_tensor_read_f32_range(input, 0, &original, 1) &&
                    original == 4.0f,
                "forced bridge failure mutated the original input");
        h3_gpu_tensor_free(result);
        h3_ane_free(ane);
    }

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 1, error);
    require(ane != NULL && h3_ane_is_shadow(ane),
            "cannot create handle-owned shadow dispatch fixture");
    memset(&metal, 0, sizeof(metal));
    metal.gpu = gpu;
    metal.expected_input = input;
    metal.count = count;
    result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result == metal.returned && metal.calls == 1 &&
                stats.shadow == 1 && stats.predictions == 1,
            "shadow dispatch did not run both backends and adopt Metal");
    h3_gpu_tensor_free(result);
    memset(&metal, 0, sizeof(metal));
    metal.gpu = gpu;
    metal.expected_input = input;
    metal.count = count;
    result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count - 1, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result == metal.returned && stats.shadow == 1 &&
                stats.attempts == 2 && stats.fallbacks == 1 &&
                stats.last_reason == H3_ANE_REASON_SHAPE &&
                stats.load_seconds >= 0.0,
            "unsupported shadow shape lost cumulative handle stats");
    h3_gpu_tensor_free(result);
    h3_ane_free(ane);

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    memset(&metal, 0, sizeof(metal));
    metal.gpu = gpu;
    metal.expected_input = input;
    metal.count = count;
    result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count - 1, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result == metal.returned && metal.calls == 1 &&
                fake.predict_count == 0 && stats.attempts == 1 &&
                stats.fallbacks == 1 &&
                stats.last_reason == H3_ANE_REASON_SHAPE &&
                stats.load_seconds >= 0.0,
            "other-shape dispatch attempted Core ML or skipped Metal");
    h3_gpu_tensor_free(result);

    memset(&metal, 0, sizeof(metal));
    metal.gpu = gpu;
    metal.expected_input = input;
    metal.count = count;
    h3_ane_dispatch_test_fail_allocation(1);
    result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result == metal.returned && stats.attempts == 2 &&
                stats.fallbacks == 2 &&
                stats.last_reason == H3_ANE_REASON_PREDICTION,
            "allocation fallback stats were not cumulative");
    h3_gpu_tensor_free(result);

    memset(&metal, 0, sizeof(metal));
    metal.gpu = gpu;
    metal.expected_input = input;
    metal.count = count;
    h3_ane_dispatch_test_fail_host_read(1);
    result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result == metal.returned && stats.attempts == 3 &&
                stats.fallbacks == 3 &&
                stats.last_reason == H3_ANE_REASON_PREDICTION,
            "host-read fallback stats were not cumulative");
    h3_gpu_tensor_free(result);
    h3_ane_free(ane);

    fake = valid_fake_backend();
    install_fake_backend(&fake);
    ane = create_enabled(model_path, &contract, 0, error);
    memset(&metal, 0, sizeof(metal));
    metal.gpu = gpu;
    metal.expected_input = input;
    metal.count = count;
    h3_ane_dispatch_test_fail_replacement_allocation(1);
    result = h3_ane_dispatch_gpu_block(
        ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    require(result == metal.returned && metal.calls == 1 &&
                stats.attempts == 1 && stats.predictions == 1 &&
                stats.fallbacks == 1 &&
                stats.last_reason == H3_ANE_REASON_PREDICTION,
            "replacement allocation failure double-counted prediction attempt");
    h3_gpu_tensor_free(result);
    h3_ane_free(ane);

    h3_gpu_tensor_free(input);
    free(input_values);
    h3_gpu_free(gpu);
    h3_ane_test_set_backend(NULL);
    unsetenv("H3_ANE_MODEL");
}

static void test_video_encoder_ane_surface(void) {
    h3_video_latent latent = {0};
    require(latent.ane_stats.attempts == 0,
            "video latent ANE stats do not initialize to zero");
    int (*qualification)(const char *, const char *, const float *, size_t,
                         float *, float *, size_t, h3_ane_diagnostic *,
                         char *, size_t) =
        h3_video_encoder_block0_qualification;
    require(qualification != NULL,
            "video encoder qualification surface is unavailable");

    require(h3_video_encoder_test_ane_candidate(
                1, 256, 256, 0, 0, 1, 256, 256, 128, 128),
            "exact encoder candidate was rejected");
    const int variations[][10] = {
        {2, 256, 256, 0, 0, 2, 256, 256, 128, 128},
        {1, 512, 256, 0, 0, 1, 256, 256, 128, 128},
        {1, 256, 512, 0, 0, 1, 256, 256, 128, 128},
        {1, 256, 256, 1, 0, 1, 256, 256, 128, 128},
        {1, 256, 256, 0, 1, 1, 256, 256, 128, 128},
        {1, 256, 256, 0, 0, 2, 256, 256, 128, 128},
        {1, 256, 256, 0, 0, 1, 128, 256, 128, 128},
        {1, 256, 256, 0, 0, 1, 256, 128, 128, 128},
        {1, 256, 256, 0, 0, 1, 256, 256, 256, 128},
        {1, 256, 256, 0, 0, 1, 256, 256, 128, 256},
    };
    for (size_t index = 0; index < sizeof(variations) / sizeof(variations[0]);
         index++)
        require(!h3_video_encoder_test_ane_candidate(
                    variations[index][0], variations[index][1],
                    variations[index][2], variations[index][3],
                    variations[index][4], (uint32_t)variations[index][5],
                    (uint32_t)variations[index][6],
                    (uint32_t)variations[index][7],
                    (uint32_t)variations[index][8],
                    (uint32_t)variations[index][9]),
                "unsupported encoder candidate was accepted");
}

static void run_cancellation_fixture(const char *root,
                                     const char *ready_path) {
    static const char source[] =
        "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    char model_path[512], error[256];
    make_qualified_model(root, "cancel-model", source, model_path);
    h3_ane_contract contract = valid_contract(source);
    fake_ane_backend fake = valid_fake_backend();
    fake.predict_block_ready_path = ready_path;
    install_fake_backend(&fake);
    h3_ane *ane = create_enabled(model_path, &contract, 0, error);
    require(ane != NULL, error);
    h3_gpu *gpu = h3_gpu_create("h3_shaders.metal", error, sizeof(error));
    require(gpu != NULL, error);
    float *values = calloc(count, sizeof(*values));
    require(values != NULL, "cannot allocate cancellation input");
    h3_gpu_tensor *input = h3_gpu_tensor_from_f32(gpu, values, count);
    require(input != NULL, "cannot create cancellation input tensor");
    fake_metal_block metal = {
        .gpu = gpu, .expected_input = input, .count = count,
    };
    h3_ane_stats stats;
    (void)h3_ane_dispatch_gpu_block(
        ane, gpu, input, count, fake_metal_run, &metal, &stats, error,
        sizeof(error));
    die("blocking fake prediction returned unexpectedly");
}

int main(void) {
    char root[] = "/tmp/h3-ane-tests.XXXXXX";
    require(mkdtemp(root) != NULL, "cannot create temporary fixture root");
    const char *cancel_ready = getenv("H3_ANE_CANCEL_READY");
    if (cancel_ready && *cancel_ready) {
        run_cancellation_fixture(root, cancel_ready);
        return 1;
    }
    test_directory_digest(root);
    test_tensor_digest(root);
    test_receipt_load_and_validate(root);
    test_contract_is_exact();
    test_compiled_directory_receipt_integration(root);
    test_runtime_metadata();
    test_multiarray_stride_copy();
    test_first_diagnostic_is_immutable();
    test_complete_diagnostic_taxonomy();
    test_diagnostic_code_snapshots();
    test_runtime_bridge(root);
    test_dispatch_fallback(root);
    test_video_encoder_ane_surface();
    printf("PASS tests/test_ane.c\n");
    return 0;
}
