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
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static char active_temp[4096];
#ifdef H3_ANE_TOOL_TESTING
static int atomic_finish_count;
#endif

static void cleanup_temp(void) {
    if (active_temp[0]) unlink(active_temp);
    active_temp[0] = '\0';
}

static void cancelled(int signal_number) {
    cleanup_temp();
    _exit(128 + signal_number);
}

static void pause_during_invalidation_if_requested(void) {
#ifdef H3_ANE_TOOL_TESTING
    const char *marker_path = getenv("H3_ANE_TEST_PAUSE_DURING_INVALIDATION");
    const char *release_path = getenv("H3_ANE_TEST_RELEASE_INVALIDATION");
    if (!marker_path || !*marker_path || !release_path || !*release_path) return;
    FILE *stream = fopen(marker_path, "w");
    if (stream) { fputs("signals blocked\n", stream); fclose(stream); }
    struct timespec delay = {.tv_sec = 0, .tv_nsec = 1000000};
    while (access(release_path, F_OK) != 0) nanosleep(&delay, NULL);
#endif
}

static void usage(FILE *stream) {
    fprintf(stream, "usage: h3_ane_qualification [--shadow-only] --model WEIGHT_DIR "
                    "--coreml-model MODEL.mlmodelc --output RESULT.json\n");
}

static int parse_args(int argc, char **argv, const char **weights,
                      const char **model, const char **output,
                      int *shadow_only) {
    for (int index = 1; index < argc; index++) {
        if (!strcmp(argv[index], "--help")) {
            usage(stdout);
            exit(0);
        }
        if (!strcmp(argv[index], "--shadow-only")) {
            *shadow_only = 1;
            continue;
        }
        if (index + 1 >= argc) return 0;
        if (!strcmp(argv[index], "--model")) *weights = argv[++index];
        else if (!strcmp(argv[index], "--coreml-model")) *model = argv[++index];
        else if (!strcmp(argv[index], "--output")) *output = argv[++index];
        else return 0;
    }
    return *weights && *model && *output;
}

static void json_number_or_null(FILE *stream, double value) {
    if (isfinite(value)) fprintf(stream, "%.17g", value);
    else fputs("null", stream);
}

static int atomic_open(const char *path) {
    if (snprintf(active_temp, sizeof(active_temp), "%s.tmp-XXXXXX", path) >=
        (int)sizeof(active_temp)) return -1;
    return mkstemp(active_temp);
}

static int atomic_finish(FILE *stream, const char *path) {
    int descriptor = fileno(stream);
    int ok = fflush(stream) == 0;
    if (fsync(descriptor) != 0) ok = 0;
    if (fclose(stream) != 0) ok = 0;
#ifdef H3_ANE_TOOL_TESTING
    atomic_finish_count++;
    const char *pause_marker = getenv("H3_ANE_TEST_PAUSE_BEFORE_RENAME");
    const char *pause_suffix = getenv("H3_ANE_TEST_PAUSE_SUFFIX");
    const char *pause_occurrence = getenv("H3_ANE_TEST_PAUSE_OCCURRENCE");
    int expected_occurrence = pause_occurrence ? atoi(pause_occurrence) : 0;
    size_t path_size = strlen(path);
    size_t suffix_size = pause_suffix ? strlen(pause_suffix) : 0;
    if (ok && pause_marker && *pause_marker && pause_suffix &&
        (!expected_occurrence || expected_occurrence == atomic_finish_count) &&
        path_size >= suffix_size &&
        strcmp(path + path_size - suffix_size, pause_suffix) == 0) {
        FILE *marker = fopen(pause_marker, "w");
        if (marker) { fputs("temporary file synced\n", marker); fclose(marker); }
        for (;;) pause();
    }
#endif
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
                         char *error, size_t error_size,
                         h3_ane_diagnostic *diagnostic) {
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
    if (!store) {
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_ARTIFACT,
            H3_ANE_CODE_SOURCE_WEIGHTS_UNREADABLE, H3_ANE_REASON_FINGERPRINT,
            "source weights are unreadable");
        return 0;
    }
    int ok = h3_ane_sha256_tensors(
        store, names, sizeof(names) / sizeof(*names), digest, error, error_size);
    if (!ok)
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_ARTIFACT,
            H3_ANE_CODE_SOURCE_TENSOR_DIGEST_FAILED,
            H3_ANE_REASON_FINGERPRINT, "source tensor digest failed");
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
                   size_t error_size, h3_ane_diagnostic *diagnostic) {
#ifdef H3_ANE_TOOL_TESTING
    const char *measurement_marker = getenv("H3_ANE_TEST_MEASUREMENT_MARKER");
    if (measurement_marker && *measurement_marker) {
        FILE *stream = fopen(measurement_marker, "w");
        if (stream) { fputs("measurement started\n", stream); fclose(stream); }
    }
#endif
    if (parse_test_metrics(max_abs, relative_l2, source)) return 1;
    if (!source_digest(weights, source, error, error_size, diagnostic)) return 0;
    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    float *input = malloc(count * sizeof(*input));
    float *metal = malloc(count * sizeof(*metal));
    float *coreml = malloc(count * sizeof(*coreml));
    if (!input || !metal || !coreml) {
        h3_ane_diagnostic_record_first(diagnostic, H3_ANE_STAGE_SETUP,
            H3_ANE_CODE_ALLOCATION_FAILED, H3_ANE_REASON_LOAD,
            "qualification vector allocation failed");
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
        weights, model, input, count, metal, coreml, count, diagnostic,
        error, error_size);
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
#ifdef H3_ANE_TOOL_TESTING
    const char *fail_write = getenv("H3_ANE_TEST_FAIL_RECEIPT_WRITE");
    if (fail_write && strcmp(fail_write, "1") == 0) {
        errno = EIO;
        return 0;
    }
#endif
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

#ifdef H3_ANE_TOOL_TESTING
static int result_write_count;
#endif

static void write_diagnostic_fields(FILE *stream, const char *failure,
                                    const h3_ane_diagnostic *diagnostic);

static int write_result(const char *path, int passed, const char *model_sha,
                        const char *source_sha, const char *qualified_at,
                        double max_abs, double relative_l2,
                        const char *failure,
                        const h3_ane_diagnostic *diagnostic) {
#ifdef H3_ANE_TOOL_TESTING
    result_write_count++;
    const char *fail_rewrite = getenv("H3_ANE_TEST_FAIL_RESULT_REWRITE");
    if (result_write_count > 1 && fail_rewrite &&
        strcmp(fail_rewrite, "1") == 0) {
        errno = EIO;
        return 0;
    }
#endif
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
    if (passed) json_string(stream, "compiled-model.qualification.json");
    else fputs("null", stream);
    write_diagnostic_fields(stream, failure, diagnostic);
    fputs("}\n", stream);
    return atomic_finish(stream, path);
}

static void write_diagnostic_fields(FILE *stream, const char *failure,
                                    const h3_ane_diagnostic *diagnostic) {
    fputs(",\"failure_reason\":", stream);
    if (diagnostic && diagnostic->code != H3_ANE_CODE_NONE)
        json_string(stream, diagnostic->message);
    else if (failure) json_string(stream, failure);
    else fputs("null", stream);
    fputs(",\"failure_stage\":", stream);
    if (diagnostic && diagnostic->code != H3_ANE_CODE_NONE) {
        json_string(stream, h3_ane_stage_name(diagnostic->stage));
    } else fputs("null", stream);
    fputs(",\"failure_code\":", stream);
    if (diagnostic && diagnostic->code != H3_ANE_CODE_NONE) {
        json_string(stream, h3_ane_code_name(diagnostic->code));
    } else fputs("null", stream);
    fputs(",\"failure_operation\":", stream);
    if (diagnostic && diagnostic->has_operation)
        json_string(stream, diagnostic->operation);
    else fputs("null", stream);
    fputs(",\"supported_devices\":", stream);
    if (diagnostic && diagnostic->has_supported_devices) {
        fputc('[', stream);
        int separator = 0;
        if (diagnostic->supported_devices & H3_ANE_DEVICE_CPU) {
            json_string(stream, "cpu"); separator = 1;
        }
        if (diagnostic->supported_devices & H3_ANE_DEVICE_GPU) {
            if (separator) fputc(',', stream); json_string(stream, "gpu"); separator = 1;
        }
        if (diagnostic->supported_devices & H3_ANE_DEVICE_NEURAL_ENGINE) {
            if (separator) fputc(',', stream); json_string(stream, "neural-engine");
        }
        fputc(']', stream);
    } else fputs("null", stream);
    fputs(",\"preferred_device\":", stream);
    if (diagnostic && diagnostic->has_preferred_device) {
        const char *device = diagnostic->preferred_device == H3_ANE_DEVICE_CPU ?
            "cpu" : diagnostic->preferred_device == H3_ANE_DEVICE_GPU ? "gpu" :
            diagnostic->preferred_device == H3_ANE_DEVICE_NEURAL_ENGINE ?
            "neural-engine" : NULL;
        if (device) json_string(stream, device); else fputs("null", stream);
    } else fputs("null", stream);
    fputs(",\"observed_count\":", stream);
    if (diagnostic && diagnostic->has_count)
        fprintf(stream, "%llu", (unsigned long long)diagnostic->observed_count);
    else fputs("null", stream);
    fputs(",\"limit\":", stream);
    if (diagnostic && diagnostic->has_count)
        fprintf(stream, "%llu", (unsigned long long)diagnostic->limit);
    else fputs("null", stream);
}

static int invalidate_receipt(const char *receipt, char *invalid) {
    struct stat status;
    if (lstat(receipt, &status) != 0) return errno == ENOENT;
    if (snprintf(invalid, strlen(receipt) + sizeof(".invalid-XXXXXX"),
                 "%s.invalid-XXXXXX", receipt) < 0) return 0;
    int quarantine = mkstemp(invalid);
    if (quarantine < 0) return 0;
    if (close(quarantine) != 0) { unlink(invalid); return 0; }
    pause_during_invalidation_if_requested();
    if (rename(receipt, invalid) == 0) return 1;
    int rename_error = errno;
    unlink(invalid);
    if (unlink(receipt) == 0) return 1;
    fprintf(stderr, "h3_ane_qualification: cannot invalidate old receipt: %s\n",
            strerror(rename_error));
    return 0;
}

static int receipt_preflight(const char *receipt) {
    char source[4096], target[4096];
    if (snprintf(source, sizeof(source), "%s.preflight-source-XXXXXX", receipt) >=
            (int)sizeof(source) ||
        snprintf(target, sizeof(target), "%s.preflight-target-XXXXXX", receipt) >=
            (int)sizeof(target)) return 0;
    int source_descriptor = mkstemp(source);
    if (source_descriptor < 0) return 0;
    int target_descriptor = mkstemp(target);
    if (target_descriptor < 0) {
        close(source_descriptor); unlink(source); return 0;
    }
    int ok = close(source_descriptor) == 0;
    if (close(target_descriptor) != 0) ok = 0;
    if (ok) ok = rename(source, target) == 0;
    unlink(source);
    if (unlink(target) != 0) ok = 0;
    return ok;
}

static void pause_after_preflight_if_requested(void) {
#ifdef H3_ANE_TOOL_TESTING
    const char *marker = getenv("H3_ANE_TEST_PAUSE_AFTER_PREFLIGHT");
    const char *release = getenv("H3_ANE_TEST_RELEASE_PREFLIGHT");
    if (!marker || !*marker || !release || !*release) return;
    FILE *stream = fopen(marker, "w");
    if (stream) { fputs("preflight complete\n", stream); fclose(stream); }
    struct timespec delay = {.tv_sec = 0, .tv_nsec = 1000000};
    while (access(release, F_OK) != 0) nanosleep(&delay, NULL);
#endif
}

static int write_shadow_preflight_failure(const char *path) {
    int descriptor = atomic_open(path);
    if (descriptor < 0) return 0;
    FILE *stream = fdopen(descriptor, "w");
    if (!stream) { close(descriptor); cleanup_temp(); return 0; }
    fputs("{\"schema\":\"h3-ane-qualification/v1\","
          "\"profile\":\"shadow-measurement-v1\",\"status\":\"failed\","
          "\"authority\":false,\"measurement_started\":false,"
          "\"authority_state\":\"unchanged\",\"model_sha256\":\"\","
          "\"source_sha256\":\"\",\"test_vector\":\"xorshift32-v1\","
          "\"qualified_at\":\"\",\"max_abs\":null,\"relative_l2\":null,"
          "\"bounds\":{\"max_abs\":0.25,\"relative_l2\":0.05},"
          "\"threshold_outcome\":false,\"receipt_path\":null,"
          "\"failure_reason\":\"receipt quarantine preflight failed\","
          "\"failure_stage\":\"receipt\",\"failure_code\":\"receipt_invalid\","
          "\"failure_operation\":null,\"supported_devices\":null,"
          "\"preferred_device\":null,\"observed_count\":null,"
          "\"limit\":null}\n", stream);
    return atomic_finish(stream, path);
}

static int write_shadow_result(const char *path, int passed,
                               const char *model_sha, const char *source_sha,
                               const char *qualified_at, double max_abs,
                               double relative_l2, const char *failure,
                               const h3_ane_diagnostic *diagnostic) {
    int descriptor = atomic_open(path);
    if (descriptor < 0) return 0;
    FILE *stream = fdopen(descriptor, "w");
    if (!stream) { close(descriptor); cleanup_temp(); return 0; }
    fprintf(stream, "{\"schema\":\"h3-ane-qualification/v1\","
                    "\"profile\":\"shadow-measurement-v1\","
                    "\"status\":\"%s\",\"authority\":false,"
                    "\"model_sha256\":\"%s\",\"source_sha256\":\"%s\","
                    "\"test_vector\":\"xorshift32-v1\","
                    "\"qualified_at\":\"%s\",\"max_abs\":",
            passed ? "passed" : "failed", model_sha, source_sha, qualified_at);
    json_number_or_null(stream, max_abs);
    fputs(",\"relative_l2\":", stream);
    json_number_or_null(stream, relative_l2);
    fputs(",\"bounds\":{\"max_abs\":0.25,\"relative_l2\":0.05},"
          "\"threshold_outcome\":", stream);
    fputs(passed ? "true" : "false", stream);
    fputs(",\"receipt_path\":null", stream);
    write_diagnostic_fields(stream, failure, diagnostic);
    fputs(",\"measurement_started\":true,"
          "\"authority_state\":\"invalidated\"", stream);
    fputs("}\n", stream);
    return atomic_finish(stream, path);
}

static void pause_after_receipt_if_requested(void) {
#ifdef H3_ANE_TOOL_TESTING
    const char *path = getenv("H3_ANE_TEST_PAUSE_AFTER_RECEIPT");
    if (!path || !*path) return;
    FILE *stream = fopen(path, "w");
    if (stream) {
        fputs("receipt committed\n", stream);
        fclose(stream);
    }
    for (;;) pause();
#endif
}

static void pause_after_invalidation_if_requested(void) {
#ifdef H3_ANE_TOOL_TESTING
    const char *path = getenv("H3_ANE_TEST_PAUSE_AFTER_INVALIDATION");
    if (!path || !*path) return;
    FILE *stream = fopen(path, "w");
    if (stream) {
        fputs("receipt invalidated\n", stream);
        fclose(stream);
    }
    for (;;) pause();
#endif
}

int main(int argc, char **argv) {
    const char *weights = NULL, *model = NULL, *output = NULL;
    int shadow_only = 0;
    if (!parse_args(argc, argv, &weights, &model, &output, &shadow_only)) {
        usage(stderr); return 2;
    }
    signal(SIGINT, cancelled); signal(SIGTERM, cancelled);
    size_t receipt_size = strlen(model) + sizeof(".qualification.json");
    char *receipt = malloc(receipt_size);
    char *invalid = malloc(receipt_size + sizeof(".invalid-XXXXXX"));
    if (!receipt || !invalid) return 2;
    snprintf(receipt, receipt_size, "%s.qualification.json", model);
    invalid[0] = '\0';
    if (shadow_only && !receipt_preflight(receipt)) {
        int published = write_shadow_preflight_failure(output);
        if (!published)
            fprintf(stderr, "h3_ane_qualification: receipt/preflight_failed\n");
        free(receipt); free(invalid); return 2;
    }
    if (shadow_only) pause_after_preflight_if_requested();
    sigset_t invalidation_signals, previous_signals;
    sigemptyset(&invalidation_signals);
    sigaddset(&invalidation_signals, SIGINT);
    sigaddset(&invalidation_signals, SIGTERM);
    if (sigprocmask(SIG_BLOCK, &invalidation_signals, &previous_signals) != 0) {
        free(receipt); free(invalid); return 2;
    }
    if (!invalidate_receipt(receipt, invalid)) {
        sigprocmask(SIG_SETMASK, &previous_signals, NULL);
        free(receipt); free(invalid); return 2;
    }
    if (sigprocmask(SIG_SETMASK, &previous_signals, NULL) != 0) {
        unlink(receipt); free(receipt); free(invalid); return 2;
    }
    pause_after_invalidation_if_requested();

    char model_sha[65] = "", source_sha[65] = "", at[32] = "";
    char error[512] = "";
    h3_ane_diagnostic diagnostic = {0};
    double max_abs = 0.0, relative_l2 = 0.0;
    int measured = h3_ane_sha256_directory(model, model_sha, error, sizeof(error));
    if (!measured)
        h3_ane_diagnostic_record_first(&diagnostic, H3_ANE_STAGE_ARTIFACT,
            H3_ANE_CODE_COMPILED_MODEL_DIGEST_FAILED,
            H3_ANE_REASON_FINGERPRINT, "compiled model digest failed");
    if (measured && !timestamp(at)) {
        measured = 0;
        h3_ane_diagnostic_record_first(&diagnostic, H3_ANE_STAGE_SETUP,
            H3_ANE_CODE_ALLOCATION_FAILED, H3_ANE_REASON_LOAD,
            "qualification timestamp failed");
    }
    if (measured)
        measured = qualify(weights, model, &max_abs, &relative_l2,
                           source_sha, error, sizeof(error), &diagnostic);
    double max_abs_bound = shadow_only ? 0.25 : 0.002;
    double relative_l2_bound = shadow_only ? 0.05 : 0.02;
    int passed = measured && isfinite(max_abs) && isfinite(relative_l2) &&
                 max_abs >= 0.0 && relative_l2 >= 0.0 &&
                 max_abs < max_abs_bound && relative_l2 < relative_l2_bound;
    const char *failure = NULL;
    if (!measured) failure = error[0] ? error : "qualification execution failed";
    else if (!passed) {
        failure = "parity bounds failed";
        h3_ane_diagnostic_record_first(&diagnostic, H3_ANE_STAGE_PARITY,
            (!isfinite(max_abs) || !isfinite(relative_l2)) ?
                H3_ANE_CODE_PARITY_METRICS_NONFINITE :
                H3_ANE_CODE_PARITY_BOUNDS_FAILED,
            H3_ANE_REASON_PREDICTION, "parity qualification failed");
        diagnostic.max_abs = max_abs;
        diagnostic.relative_l2 = relative_l2;
        diagnostic.has_metrics = 1;
    }
    int result_written = shadow_only ?
        write_shadow_result(output, passed, model_sha, source_sha, at, max_abs,
                            relative_l2, failure, &diagnostic) :
        write_result(output, passed, model_sha, source_sha, at, max_abs,
                     relative_l2, failure, &diagnostic);
    if (!result_written) {
        fprintf(stderr, "h3_ane_qualification: publication/result_write_failed\n");
        unlink(receipt); free(receipt); free(invalid); return 2;
    }
    if (!shadow_only && passed && !write_receipt(receipt, model_sha, source_sha, at,
                                 max_abs, relative_l2)) {
        passed = 0; failure = "cannot atomically write passing receipt";
        memset(&diagnostic, 0, sizeof(diagnostic));
        h3_ane_diagnostic_record_first(&diagnostic, H3_ANE_STAGE_PUBLICATION,
            H3_ANE_CODE_RECEIPT_WRITE_FAILED, H3_ANE_REASON_RECEIPT,
            "qualification receipt publication failed");
        unlink(receipt);
        if (!write_result(output, 0, model_sha, source_sha, at, max_abs,
                          relative_l2, failure, &diagnostic)) {
            fprintf(stderr,
                    "h3_ane_qualification: publication/receipt_write_failed; publication/result_write_failed\n");
            free(receipt); free(invalid); return 2;
        }
    }
    if (!shadow_only && passed) pause_after_receipt_if_requested();
    else unlink(receipt);
    free(receipt); free(invalid);
    return passed ? 0 : 1;
}
