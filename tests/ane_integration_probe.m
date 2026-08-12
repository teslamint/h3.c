#include "h3_ane_internal.h"

#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static char active_temp[4096];

static void cleanup(void) {
    if (active_temp[0]) unlink(active_temp);
    active_temp[0] = '\0';
}

static void cancelled(int signum) {
    cleanup();
    _exit(128 + signum);
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

static int parse_digest(const char *value) {
    if (strlen(value) != 64) return 0;
    for (size_t index = 0; index < 64; index++)
        if (!((value[index] >= '0' && value[index] <= '9') ||
              (value[index] >= 'a' && value[index] <= 'f'))) return 0;
    return 1;
}

static int publish(const char *path, int passed,
                   const char *model_sha256, const char *source_sha256,
                   const h3_ane_inventory_summary *inventory,
                   const h3_ane_diagnostic *diagnostic) {
    if (snprintf(active_temp, sizeof(active_temp), "%s.tmp-XXXXXX", path) >=
        (int)sizeof(active_temp)) return 0;
    int descriptor = mkstemp(active_temp);
    if (descriptor < 0) return 0;
    FILE *stream = fdopen(descriptor, "w");
    if (!stream) { close(descriptor); cleanup(); return 0; }
    fprintf(stream, "{\"schema\":\"h3-ane-integration-probe/v1\"," 
                    "\"status\":\"%s\",\"model_sha256\":\"%s\"," 
                    "\"source_sha256\":\"%s\",\"inventory\":{"
                    "\"total\":%llu,\"constant\":%llu,"
                    "\"nonconstant\":%llu,\"neural_engine_supported\":%llu,"
                    "\"cpu_only\":%llu,\"gpu_only\":%llu,"
                    "\"unknown_nonconstant\":%llu,"
                    "\"constant_nil_usage\":%llu},\"diagnostic\":",
            passed ? "passed" : "failed", model_sha256, source_sha256,
            (unsigned long long)inventory->total,
            (unsigned long long)inventory->constant,
            (unsigned long long)inventory->nonconstant,
            (unsigned long long)inventory->neural_engine_supported,
            (unsigned long long)inventory->cpu_only,
            (unsigned long long)inventory->gpu_only,
            (unsigned long long)inventory->unknown_nonconstant,
            (unsigned long long)inventory->constant_nil_usage);
    if (diagnostic->code == H3_ANE_CODE_NONE) fputs("null", stream);
    else {
        char message[161];
        snprintf(message, sizeof(message), "%s", diagnostic->message);
        fputs("{\"stage\":", stream);
        json_string(stream, h3_ane_stage_name(diagnostic->stage));
        fputs(",\"code\":", stream);
        json_string(stream, h3_ane_code_name(diagnostic->code));
        fputs(",\"message\":", stream);
        json_string(stream, message);
        fputc('}', stream);
    }
    fputs("}\n", stream);
    int ok = fflush(stream) == 0 && fsync(descriptor) == 0 && fclose(stream) == 0 &&
             rename(active_temp, path) == 0;
    if (ok) active_temp[0] = '\0'; else cleanup();
    return ok;
}

int main(int argc, char **argv) {
    const char *model = NULL, *source = NULL, *output = NULL;
    if (argc == 6) {
        model = argv[1];
        for (int index = 2; index < 6; index += 2) {
            if (!strcmp(argv[index], "--source-sha256")) source = argv[index + 1];
            else if (!strcmp(argv[index], "--output")) output = argv[index + 1];
        }
    }
    if (!model || !source || !output || !parse_digest(source)) {
        fprintf(stderr, "usage: h3_ane_integration_probe MODEL.mlmodelc "
                        "--source-sha256 HEX --output SUMMARY.json\n");
        return 2;
    }
    signal(SIGINT, cancelled);
    signal(SIGTERM, cancelled);
    h3_ane_contract contract = {
        .version = 1, .variant = "FL2VA", .block_level = 0, .block_index = 0,
        .weight_prefix = "encoder.down.0.block.0", .boundary_dtype = H3_ANE_DTYPE_F32,
        .shape = {1, 1, 256, 256, 128}
    };
    memcpy(contract.source_sha256, source, 65);
    char error[512] = "";
    char model_sha256[65] = "";
    if (!h3_ane_sha256_directory(model, model_sha256, error, sizeof(error))) {
        fprintf(stderr, "h3_ane_integration_probe: model digest failed\n");
        return 1;
    }
    h3_ane *ane = h3_ane_create_authorized(model, &contract, 1,
                                            error, sizeof(error));
    h3_ane_inventory_summary inventory = {0};
    h3_ane_diagnostic diagnostic = {0};
    h3_ane_inventory_snapshot(ane, &inventory);
    h3_ane_diagnostic_snapshot(ane, &diagnostic);
    int passed = ane && diagnostic.code == H3_ANE_CODE_NONE;
    if (!passed && diagnostic.code == H3_ANE_CODE_NONE)
        h3_ane_diagnostic_record_first(&diagnostic, H3_ANE_STAGE_LOAD,
            H3_ANE_CODE_MODEL_LOAD_FAILED, H3_ANE_REASON_LOAD,
            "production reader did not create a model handle");
    int published = publish(output, passed, model_sha256, source, &inventory,
                            &diagnostic);
    h3_ane_free(ane);
    if (!published) {
        fprintf(stderr, "h3_ane_integration_probe: result publication failed\n");
        return 2;
    }
    return passed ? 0 : 1;
}
