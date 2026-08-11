#include "h3_ane_receipt.h"
#include "h3_ane.h"
#include "h3_ane_internal.h"
#include "h3_gpu.h"
#include "h3_video_encoder.h"
#include "h3_weights.h"

#include <errno.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

typedef enum { MODE_METAL, MODE_COREML, MODE_AB } bench_mode;
typedef struct {
    h3_gpu *gpu;
    h3_weight_store *store;
    h3_gpu_tensor *norm1_weight, *norm1_bias, *conv1_weight, *conv1_bias;
    h3_gpu_tensor *norm2_weight, *norm2_bias, *conv2_weight, *conv2_bias;
    h3_gpu_tensor *norm1, *pad1, *hidden, *norm2, *pad2, *output;
    h3_ane *ane;
} bench_context;
static char active_temp[4096];

static void cleanup(int signal_number) {
    if (active_temp[0]) unlink(active_temp);
    if (signal_number) _exit(128 + signal_number);
}

static void usage(FILE *stream) {
    fprintf(stream, "usage: h3_ane_bench --backend metal|coreml|ab "
                    "[--coreml-model PATH] [--warmup N] [--pairs N] "
                    "--output PATH\n");
}

static int integer(const char *text, int *value) {
    char *end = NULL;
    long parsed = strtol(text, &end, 10);
    if (!*text || *end || parsed < 0 || parsed > 100000) return 0;
    *value = (int)parsed; return 1;
}

static double seconds(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0.0;
    return (double)value.tv_sec + (double)value.tv_nsec * 1e-9;
}

static int fake_seconds(bench_mode mode, double *elapsed) {
#ifdef H3_ANE_TOOL_TESTING
    const char *name = mode == MODE_METAL ? "H3_ANE_TEST_METAL_SECONDS" :
                                           "H3_ANE_TEST_COREML_SECONDS";
    const char *text = getenv(name);
    char *end = NULL;
    if (text) {
        double value = strtod(text, &end);
        if (*text && !*end && isfinite(value) && value >= 0.0) {
            *elapsed = value; return 1;
        }
    }
#else
    (void)mode; (void)elapsed;
#endif
    return 0;
}

static int test_mode_enabled(void) {
#ifdef H3_ANE_TOOL_TESTING
    return getenv("H3_ANE_TEST_METAL_SECONDS") != NULL &&
           getenv("H3_ANE_TEST_COREML_SECONDS") != NULL;
#else
    return 0;
#endif
}

static void placement_summary(uint32_t devices, bench_mode mode,
                              char output[96]) {
    if (mode == MODE_METAL) {
        snprintf(output, 96, "observed:metal-only");
        return;
    }
    snprintf(output, 96, "observed:%s%s%s",
             devices & H3_ANE_DEVICE_CPU ? "cpu" : "",
             devices & H3_ANE_DEVICE_GPU ?
                 (devices & H3_ANE_DEVICE_CPU ? "+gpu" : "gpu") : "",
             devices & H3_ANE_DEVICE_NEURAL_ENGINE ?
                 (devices & (H3_ANE_DEVICE_CPU | H3_ANE_DEVICE_GPU) ?
                    "+neural-engine" : "neural-engine") : "");
}

static void destroy_context(bench_context *context) {
    h3_ane_free(context->ane);
    h3_gpu_tensor_free(context->norm1_weight);
    h3_gpu_tensor_free(context->norm1_bias);
    h3_gpu_tensor_free(context->conv1_weight);
    h3_gpu_tensor_free(context->conv1_bias);
    h3_gpu_tensor_free(context->norm2_weight);
    h3_gpu_tensor_free(context->norm2_bias);
    h3_gpu_tensor_free(context->conv2_weight);
    h3_gpu_tensor_free(context->conv2_bias);
    h3_gpu_tensor_free(context->norm1);
    h3_gpu_tensor_free(context->pad1);
    h3_gpu_tensor_free(context->hidden);
    h3_gpu_tensor_free(context->norm2);
    h3_gpu_tensor_free(context->pad2);
    h3_gpu_tensor_free(context->output);
    h3_weight_store_free(context->store);
    h3_gpu_free(context->gpu);
    memset(context, 0, sizeof(*context));
}

static int initialize_context(bench_context *context, const char *weights,
                              const char *model, int need_coreml,
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
    const uint64_t vector_shape[] = {128};
    const uint64_t kernel_shape[] = {128, 128, 3, 3, 3};
    context->gpu = h3_gpu_create("h3_shaders.metal", error, error_size);
    if (context->gpu) context->store = h3_weight_store_open(weights, error, error_size);
#define LOAD_VECTOR(field, index) context->field = h3_weight_load_bf16( \
    context->store, context->gpu, names[index], 1, vector_shape, error, error_size)
#define LOAD_KERNEL(field, index) context->field = h3_weight_load_bf16( \
    context->store, context->gpu, names[index], 5, kernel_shape, error, error_size)
    if (context->store) {
        LOAD_VECTOR(norm1_weight, 0); LOAD_VECTOR(norm1_bias, 1);
        LOAD_KERNEL(conv1_weight, 2); LOAD_VECTOR(conv1_bias, 3);
        LOAD_VECTOR(norm2_weight, 4); LOAD_VECTOR(norm2_bias, 5);
        LOAD_KERNEL(conv2_weight, 6); LOAD_VECTOR(conv2_bias, 7);
    }
#undef LOAD_VECTOR
#undef LOAD_KERNEL
    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    const size_t padded = (size_t)1 * 3 * 258 * 258 * 128;
    if (context->conv2_bias) {
        context->norm1 = h3_gpu_tensor_new_f32(context->gpu, count);
        context->pad1 = h3_gpu_tensor_new_f32(context->gpu, padded);
        context->hidden = h3_gpu_tensor_new_f32(context->gpu, count);
        context->norm2 = h3_gpu_tensor_new_f32(context->gpu, count);
        context->pad2 = h3_gpu_tensor_new_f32(context->gpu, padded);
        context->output = h3_gpu_tensor_new_f32(context->gpu, count);
    }
    if (!context->output) {
        if (!error[0]) snprintf(error, error_size, "cannot initialize Metal benchmark block");
        return 0;
    }
    if (need_coreml) {
        h3_ane_contract contract = {0};
        contract.version = 1;
        snprintf(contract.variant, sizeof(contract.variant), "FL2VA");
        snprintf(contract.weight_prefix, sizeof(contract.weight_prefix),
                 "encoder.down.0.block.0");
        contract.boundary_dtype = H3_ANE_DTYPE_F32;
        const uint32_t shape[5] = {1, 1, 256, 256, 128};
        memcpy(contract.shape, shape, sizeof(shape));
        if (!h3_ane_sha256_tensors(context->store, names,
                                   sizeof(names) / sizeof(*names),
                                   contract.source_sha256, error, error_size)) return 0;
        context->ane = h3_ane_create(model, &contract, 0, error, error_size);
        if (!context->ane) return 0;
    }
    return 1;
}

static int run_metal(bench_context *context, const float *input, float *output,
                     size_t count, char *error, size_t error_size) {
    h3_gpu_tensor *source = h3_gpu_tensor_from_f32(context->gpu, input, count);
    int ok = source && h3_gpu_begin(context->gpu) &&
        h3_gpu_vae_encoder_group_norm_silu_f32(
            context->gpu, context->norm1, source, context->norm1_weight,
            context->norm1_bias, 1, 1, 256, 256, 128, 32, 1e-6f) &&
        h3_gpu_vae_encoder_pad_f32(context->gpu, context->pad1, context->norm1,
            1, 1, 256, 256, 128, 2, 1, 1, 1, 1) &&
        h3_gpu_conv3d_f32(context->gpu, context->hidden, context->pad1,
            context->conv1_weight, context->conv1_bias, 1, 3, 258, 258,
            128, 128, 3, 3, 3, 1, 1, 1) &&
        h3_gpu_vae_encoder_group_norm_silu_f32(
            context->gpu, context->norm2, context->hidden, context->norm2_weight,
            context->norm2_bias, 1, 1, 256, 256, 128, 32, 1e-6f) &&
        h3_gpu_vae_encoder_pad_f32(context->gpu, context->pad2, context->norm2,
            1, 1, 256, 256, 128, 2, 1, 1, 1, 1) &&
        h3_gpu_conv3d_f32(context->gpu, context->output, context->pad2,
            context->conv2_weight, context->conv2_bias, 1, 3, 258, 258,
            128, 128, 3, 3, 3, 1, 1, 1) &&
        h3_gpu_add_scaled_f32(context->gpu, context->output, source,
            context->output, 1.0f, 1.0f, (uint32_t)count) &&
        h3_gpu_submit(context->gpu) &&
        h3_gpu_tensor_read_f32(context->output, output, count);
    if (!ok) snprintf(error, error_size, "Metal benchmark block failed: %s",
                      h3_gpu_error(context->gpu));
    h3_gpu_tensor_free(source);
    return ok;
}

static int run_once(bench_context *context, bench_mode selected,
                    const float *input, const float *metal_oracle,
                    float *scratch, size_t count, double *elapsed,
                    double phases[3], double *max_abs, double *relative_l2,
                    uint32_t *observed_devices,
                    char *error, size_t error_size) {
    if (fake_seconds(selected, elapsed)) {
        phases[0] = 0.0; phases[1] = *elapsed; phases[2] = 0.0;
        if (selected == MODE_COREML)
            *observed_devices |= H3_ANE_DEVICE_CPU | H3_ANE_DEVICE_NEURAL_ENGINE;
        *max_abs = 0.001; *relative_l2 = 0.01; return 1;
    }
    double start = seconds();
    h3_ane_stats stats = {0};
    int ok = selected == MODE_METAL ?
        run_metal(context, input, scratch, count, error, error_size) :
        h3_ane_predict(context->ane, input, count, scratch, count, &stats,
                       error, error_size);
    if (!ok) return 0;
    *elapsed = seconds() - start;
    phases[0] = stats.input_seconds;
    phases[1] = stats.prediction_seconds;
    phases[2] = stats.output_seconds;
    if (selected == MODE_COREML) *observed_devices |= stats.preferred_device;
    if (selected == MODE_METAL) {
        *max_abs = 0.0; *relative_l2 = 0.0; return 1;
    }
    double maximum = 0.0, squared_error = 0.0, squared_reference = 0.0;
    for (size_t index = 0; index < count; index++) {
        double difference = (double)metal_oracle[index] - scratch[index];
        if (fabs(difference) > maximum) maximum = fabs(difference);
        squared_error += difference * difference;
        squared_reference += (double)metal_oracle[index] * metal_oracle[index];
    }
    *max_abs = maximum;
    *relative_l2 = sqrt(squared_error) /
        (sqrt(squared_reference) > 1e-30 ? sqrt(squared_reference) : 1e-30);
    return 1;
}

static void sample(FILE *stream, int *first, int pair, const char *order,
                   bench_mode selected, double elapsed, const double phases[3], double max_abs,
                   double relative_l2) {
    if (!*first) fputc(',', stream); *first = 0;
    fprintf(stream, "{\"pair\":%d,\"order\":\"%s\","
                    "\"selected_backend\":\"%s\",",
            pair, order, selected == MODE_METAL ? "metal" : "coreml");
    if (selected == MODE_METAL) {
        fprintf(stream, "\"metal_seconds\":%.17g,"
                        "\"coreml_input_seconds\":null,"
                        "\"coreml_prediction_seconds\":null,"
                        "\"coreml_output_seconds\":null,"
                        "\"coreml_total_seconds\":null,"
                        "\"max_abs\":null,\"relative_l2\":null}", elapsed);
    } else {
        double total = phases[0] + phases[1] + phases[2];
        fprintf(stream, "\"metal_seconds\":null,"
                        "\"coreml_input_seconds\":%.17g,"
                        "\"coreml_prediction_seconds\":%.17g,"
                        "\"coreml_output_seconds\":%.17g,"
                        "\"coreml_total_seconds\":%.17g,"
                        "\"max_abs\":%.17g,\"relative_l2\":%.17g}",
                phases[0], phases[1], phases[2], total, max_abs, relative_l2);
    }
}

int main(int argc, char **argv) {
    bench_mode mode = MODE_AB;
    const char *mode_name = NULL, *model = NULL, *output = NULL;
    int warmup = 2, pairs = 20;
    for (int index = 1; index < argc; index++) {
        if (!strcmp(argv[index], "--help")) { usage(stdout); return 0; }
        if (index + 1 >= argc) { usage(stderr); return 2; }
        if (!strcmp(argv[index], "--backend")) mode_name = argv[++index];
        else if (!strcmp(argv[index], "--coreml-model")) model = argv[++index];
        else if (!strcmp(argv[index], "--warmup") && integer(argv[++index], &warmup)) {}
        else if (!strcmp(argv[index], "--pairs") && integer(argv[++index], &pairs)) {}
        else if (!strcmp(argv[index], "--output")) output = argv[++index];
        else { usage(stderr); return 2; }
    }
    if (!mode_name || !output || pairs < 1) { usage(stderr); return 2; }
    if (!strcmp(mode_name, "metal")) mode = MODE_METAL;
    else if (!strcmp(mode_name, "coreml")) mode = MODE_COREML;
    else if (!strcmp(mode_name, "ab")) mode = MODE_AB;
    else { usage(stderr); return 2; }
    if (mode != MODE_METAL && !model) { usage(stderr); return 2; }
    if (!model) model = "";
    const char *weights = getenv("H3_ANE_WEIGHT_DIR");
    if (!weights) weights = "MiniMax-H3/FL2VA/video_vae/source";
    signal(SIGINT, cleanup); signal(SIGTERM, cleanup);

    const size_t count = (size_t)1 * 1 * 256 * 256 * 128;
    float *input = NULL, *metal = NULL, *scratch = NULL;
    bench_context context = {0};
    int testing = test_mode_enabled();
    if (!testing) {
        input = malloc(count * sizeof(*input)); metal = malloc(count * sizeof(*metal));
        scratch = malloc(count * sizeof(*scratch));
        if (!input || !metal || !scratch) return 2;
        uint32_t state = UINT32_C(0x4833414e);
        for (size_t index = 0; index < count; index++) {
            state ^= state << 13; state ^= state >> 17; state ^= state << 5;
            input[index] = ((float)(state & UINT32_C(0xffff)) / 32767.5f) - 1.0f;
        }
    }
    char error[512] = "";
    if (!testing && !initialize_context(&context, weights, model,
                                        mode != MODE_METAL, error, sizeof(error))) {
        fprintf(stderr, "h3_ane_bench: %s\n", error);
        destroy_context(&context); return 1;
    }
    if (!testing && mode != MODE_METAL &&
        !run_metal(&context, input, metal, count, error, sizeof(error))) {
        fprintf(stderr, "h3_ane_bench: oracle failed: %s\n", error);
        destroy_context(&context); return 1;
    }
    uint32_t observed_devices = 0;
    if (!testing && context.ane) {
        h3_ane_stats initial_stats;
        h3_ane_stats_snapshot(context.ane, &initial_stats);
        observed_devices = initial_stats.preferred_device;
    }
    for (int iteration = 0; iteration < warmup; iteration++) {
        int first_backend = mode == MODE_AB ? 0 : (int)mode;
        int last_backend = mode == MODE_AB ? 1 : (int)mode;
        for (int backend = first_backend; backend <= last_backend; backend++) {
            double elapsed, phases[3], max_abs, relative_l2;
            if (!run_once(&context, (bench_mode)backend, input, metal, scratch,
                          count, &elapsed, phases, &max_abs, &relative_l2,
                          &observed_devices,
                          error, sizeof(error))) {
                fprintf(stderr, "h3_ane_bench: warmup failed: %s\n", error); return 1;
            }
        }
    }
    if (snprintf(active_temp, sizeof(active_temp), "%s.tmp-XXXXXX", output) >=
        (int)sizeof(active_temp)) return 2;
    int descriptor = mkstemp(active_temp);
    FILE *stream = descriptor >= 0 ? fdopen(descriptor, "w") : NULL;
    if (!stream) { cleanup(0); return 2; }
    char observed_summary[96];
    placement_summary(observed_devices, mode, observed_summary);
    fprintf(stream, "{\"schema\":\"h3-ane-benchmark/v1\",\"mode\":\"%s\","
                    "\"warmup\":%d,\"pairs\":%d,"
                    "\"placement_summary\":\"%s\","
                    "\"samples\":[", mode_name, warmup, pairs,
            observed_summary);
    int first = 1, completed = 0;
    for (int pair = 0; pair < pairs; pair++) {
        bench_mode order[2]; int samples = mode == MODE_AB ? 2 : 1;
        if (mode == MODE_AB && pair % 2 == 0) { order[0] = MODE_METAL; order[1] = MODE_COREML; }
        else if (mode == MODE_AB) { order[0] = MODE_COREML; order[1] = MODE_METAL; }
        else order[0] = mode;
        const char *order_name = mode == MODE_AB ? (pair % 2 == 0 ? "AB" : "BA") :
                                 (mode == MODE_METAL ? "A" : "B");
        for (int index = 0; index < samples; index++, completed++) {
            double elapsed, phases[3], max_abs, relative_l2;
            if (!run_once(&context, order[index], input, metal, scratch, count,
                          &elapsed, phases, &max_abs, &relative_l2,
                          &observed_devices, error, sizeof(error))) {
                fprintf(stderr, "h3_ane_bench: sample failed: %s\n", error);
                fclose(stream); cleanup(0); return 1;
            }
            sample(stream, &first, pair, order_name, order[index], elapsed, phases,
                   max_abs, relative_l2);
#ifdef H3_ANE_TOOL_TESTING
            const char *abort_after = getenv("H3_ANE_TEST_ABORT_AFTER");
            if (abort_after && completed + 1 == atoi(abort_after)) {
                fclose(stream); cleanup(0); return 130;
            }
#endif
            fprintf(stderr, "pair %d %s complete\n", pair, order[index] == MODE_METAL ? "metal" : "coreml");
        }
    }
    struct rusage usage_value;
    long long peak = getrusage(RUSAGE_SELF, &usage_value) == 0 ?
                     (long long)usage_value.ru_maxrss : 0;
    fprintf(stream, "],\"peak_rss_bytes\":%lld}\n", peak);
    int ok = fflush(stream) == 0 && fsync(descriptor) == 0 && fclose(stream) == 0 &&
             rename(active_temp, output) == 0;
    if (ok) active_temp[0] = '\0'; else cleanup(0);
    destroy_context(&context);
    free(input); free(metal); free(scratch);
    return ok ? 0 : 2;
}
