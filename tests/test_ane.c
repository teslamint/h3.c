#include "h3_ane_receipt.h"

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void die(const char *message) {
    fprintf(stderr, "FAIL tests/test_ane.c: %s\n", message);
    exit(1);
}

static void require(int condition, const char *message) {
    if (!condition) die(message);
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

int main(void) {
    char root[] = "/tmp/h3-ane-tests.XXXXXX";
    require(mkdtemp(root) != NULL, "cannot create temporary fixture root");
    test_directory_digest(root);
    test_tensor_digest(root);
    test_receipt_load_and_validate(root);
    test_compiled_directory_receipt_integration(root);
    printf("PASS tests/test_ane.c\n");
    return 0;
}
