#include "h3_ane_receipt.h"
#include "h3_video_encoder.h"
#include "h3_weights.h"

#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static char active_temp[4096];

static void cleanup_temp(void) {
    if (active_temp[0]) unlink(active_temp);
    active_temp[0] = '\0';
}

static void cancelled(int signal_number) {
    cleanup_temp();
    _exit(128 + signal_number);
}

static void usage(FILE *stream) {
    fprintf(stream, "usage: h3_ane_qualification --model WEIGHT_DIR "
                    "--coreml-model MODEL.mlmodelc --output RESULT.json\n");
}

static int parse_args(int argc, char **argv, const char **weights,
                      const char **model, const char **output) {
    for (int index = 1; index < argc; index++) {
        if (!strcmp(argv[index], "--help")) {
            usage(stdout);
            exit(0);
        }
        if (index + 1 >= argc) return 0;
        if (!strcmp(argv[index], "--model")) *weights = argv[++index];
        else if (!strcmp(argv[index], "--coreml-model")) *model = argv[++index];
        else if (!strcmp(argv[index], "--output")) *output = argv[++index];
        else return 0;
    }
    return *weights && *model && *output;
}

static int atomic_open(const char *path) {
    if (snprintf(active_temp, sizeof(active_temp), "%s.tmp-XXXXXX", path) >=
        (int)sizeof(active_temp)) return -1;
    return mkstemp(active_temp);
}

static int atomic_finish(FILE *stream, const char *path) {
    int descriptor = fileno(stream);
    int ok = fflush(stream) == 0 && fsync(descriptor) == 0 && fclose(stream) == 0;
    if (ok) ok = rename(active_temp, path) == 0;
    if (!ok) cleanup_temp();
    else active_temp[0] = '\0';
    return ok;
}

static void json_string(FILE *stream, const char *value) {
    fputc('"', stream);
    for (const unsigned char *at = (const unsigned char *)value; *at; at++) {
        if (*at == '"' || *at == '\\') fprintf(stream, "\\%c", *at);
        else if (*at < 0x20) fprintf(stream, "\\u%04x", *at);
        else fputc(*at, stream);
    }
    fputc('"', stream);
}

static int timestamp(char value[32]) {
    time_t now = time(NULL);
    struct tm utc;
    return now != (time_t)-1 && gmtime_r(&now, &utc) &&
           strftime(value, 32, "%Y-%m-%dT%H:%M:%SZ", &utc) > 0;
}

static int source_digest(const char *directory, char digest[65],
                         char *error, size_t error_size) {
    static const char *const names[] = {
        "encoder.down.0.block.0.norm1.weight",
        "encoder.down.0.block.0.norm1.bias",
        "encoder.down.0.block.0.conv1.weight",
        "encoder.down.0.block.0.conv1.bias",
        "encoder.down.0.block.0.norm2.weight",
        "encoder.down.0.block.0.norm2.bias",
        "encoder.down.0.block.0.conv2.weight",
        "encoder.down.0.block.0.conv2.bias",
    };
    h3_weight_store *store = h3_weight_store_open(directory, error, error_size);
    int ok = store && h3_ane_sha256_tensors(
        store, names, sizeof(names) / sizeof(*names), digest, error, error_size);
    h3_weight_store_free(store);
    return ok;
}

static int parse_test_metrics(double *max_abs, double *relative_l2,
                              char source[65]) {
#ifdef H3_ANE_TOOL_TESTING
    const char *metrics = getenv("H3_ANE_TEST_METRICS");
    const char *digest = getenv("H3_ANE_TEST_SOURCE_SHA256");
    char tail = '\0';
    if (metrics && digest && strlen(digest) == 64 &&
        sscanf(metrics, "%lf,%lf%c", max_abs, relative_l2, &tail) == 2) {
        memcpy(source, digest, 65);
        return 1;
    }
#else
    (void)max_abs;
    (void)relative_l2;
    (void)source;
#endif
    return 0;
}

static int qualify(const char *weights, const char *model, double *max_abs,
                   double *relative_l2, char source[65], char *error,
                   size_t error_size) {
    if (parse_test_metrics(max_abs, relative_l2, source)) return 1;
    if (!source_digest(weights, source, error, error_size)) return 0;
    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    float *input = malloc(count * sizeof(*input));
    float *metal = malloc(count * sizeof(*metal));
    float *coreml = malloc(count * sizeof(*coreml));
    if (!input || !metal || !coreml) {
        snprintf(error, error_size, "out of memory allocating qualification vectors");
        free(input); free(metal); free(coreml);
        return 0;
    }
    uint32_t state = UINT32_C(0x4833414e);
    for (size_t index = 0; index < count; index++) {
        state ^= state << 13; state ^= state >> 17; state ^= state << 5;
        input[index] = ((float)(state & UINT32_C(0xffff)) / 32767.5f) - 1.0f;
    }
    int ok = h3_video_encoder_block0_qualification(
        weights, model, input, count, metal, coreml, count, error, error_size);
    double maximum = 0.0, squared_error = 0.0, squared_reference = 0.0;
    for (size_t index = 0; ok && index < count; index++) {
        double difference = (double)metal[index] - coreml[index];
        double absolute = fabs(difference);
        if (absolute > maximum) maximum = absolute;
        squared_error += difference * difference;
        squared_reference += (double)metal[index] * metal[index];
    }
    if (ok) {
        *max_abs = maximum;
        *relative_l2 = sqrt(squared_error) /
            (sqrt(squared_reference) > 1e-30 ? sqrt(squared_reference) : 1e-30);
    }
    free(input); free(metal); free(coreml);
    return ok;
}

static int write_receipt(const char *path, const char *model_sha,
                         const char *source_sha, const char *qualified_at,
                         double max_abs, double relative_l2) {
    int descriptor = atomic_open(path);
    if (descriptor < 0) return 0;
    FILE *stream = fdopen(descriptor, "w");
    if (!stream) { close(descriptor); cleanup_temp(); return 0; }
    fprintf(stream, "{\"version\":1,\"model_sha256\":\"%s\","
                    "\"source_sha256\":\"%s\","
                    "\"test_vector\":\"xorshift32-v1\","
                    "\"qualified_at\":\"%s\",\"max_abs\":%.17g,"
                    "\"relative_l2\":%.17g,\"status\":\"passed\"}\n",
            model_sha, source_sha, qualified_at, max_abs, relative_l2);
    return atomic_finish(stream, path);
}

static int write_result(const char *path, int passed, const char *model_sha,
                        const char *source_sha, const char *qualified_at,
                        double max_abs, double relative_l2,
                        const char *receipt_path, const char *failure) {
    int descriptor = atomic_open(path);
    if (descriptor < 0) return 0;
    FILE *stream = fdopen(descriptor, "w");
    if (!stream) { close(descriptor); cleanup_temp(); return 0; }
    fprintf(stream, "{\"schema\":\"h3-ane-qualification/v1\",\"status\":\"%s\","
                    "\"model_sha256\":\"%s\",\"source_sha256\":\"%s\","
                    "\"test_vector\":\"xorshift32-v1\",\"qualified_at\":\"%s\","
                    "\"max_abs\":%.17g,\"relative_l2\":%.17g,\"receipt_path\":",
            passed ? "passed" : "failed", model_sha, source_sha, qualified_at,
            max_abs, relative_l2);
    json_string(stream, receipt_path);
    fputs(",\"failure_reason\":", stream);
    if (failure) json_string(stream, failure); else fputs("null", stream);
    fputs("}\n", stream);
    return atomic_finish(stream, path);
}

int main(int argc, char **argv) {
    const char *weights = NULL, *model = NULL, *output = NULL;
    if (!parse_args(argc, argv, &weights, &model, &output)) {
        usage(stderr); return 2;
    }
    signal(SIGINT, cancelled); signal(SIGTERM, cancelled);
    size_t receipt_size = strlen(model) + sizeof(".qualification.json");
    char *receipt = malloc(receipt_size);
    char *invalid = malloc(receipt_size + sizeof(".invalid"));
    if (!receipt || !invalid) return 2;
    snprintf(receipt, receipt_size, "%s.qualification.json", model);
    snprintf(invalid, receipt_size + sizeof(".invalid"), "%s.invalid", receipt);
    if (access(receipt, F_OK) == 0) {
        unlink(invalid);
        if (rename(receipt, invalid) != 0) {
            fprintf(stderr, "h3_ane_qualification: cannot invalidate old receipt: %s\n",
                    strerror(errno));
            free(receipt); free(invalid); return 2;
        }
    }

    char model_sha[65] = "", source_sha[65] = "", at[32] = "";
    char error[512] = "";
    double max_abs = 0.0, relative_l2 = 0.0;
    int measured = h3_ane_sha256_directory(model, model_sha, error, sizeof(error)) &&
                   timestamp(at) && qualify(weights, model, &max_abs, &relative_l2,
                                            source_sha, error, sizeof(error));
    int passed = measured && isfinite(max_abs) && isfinite(relative_l2) &&
                 max_abs < 0.002 && relative_l2 < 0.02;
    const char *failure = NULL;
    if (!measured) failure = error[0] ? error : "qualification execution failed";
    else if (!passed) failure = "parity bounds failed";
    if (passed && !write_receipt(receipt, model_sha, source_sha, at,
                                 max_abs, relative_l2)) {
        passed = 0; failure = "cannot atomically write passing receipt";
    }
    if (!write_result(output, passed, model_sha, source_sha, at, max_abs,
                      relative_l2, receipt, failure)) {
        fprintf(stderr, "h3_ane_qualification: cannot write result: %s\n",
                strerror(errno));
        unlink(receipt); free(receipt); free(invalid); return 2;
    }
    if (!passed) unlink(receipt);
    free(receipt); free(invalid);
    return passed ? 0 : 1;
}
