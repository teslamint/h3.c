#ifndef H3_VIDEO_ENCODER_H
#define H3_VIDEO_ENCODER_H

#include "h3_ane.h"
#include "h3_gpu.h"

#include <stddef.h>

typedef struct {
    int time;
    int height;
    int width;
    /* Channel-major normalized F32: [24,time,height,width]. */
    float *values;
    h3_gpu_stats gpu_stats;
    h3_ane_stats ane_stats;
} h3_video_latent;

typedef void (*h3_video_encoder_progress)(int completed_tiles,
                                          int total_tiles, void *opaque);

/* Encode channel-major RGB [3,T,H,W] pixels in [0,1]. Spatial axes must be
 * multiples of 16. The released 256px/64px overlap tiling is preserved. */
int h3_video_vae_encode(const char *weight_directory,
                        const char *shader_source_path,
                        const float *pixels, int frames, int height, int width,
                        h3_video_encoder_progress progress, void *progress_opaque,
                        h3_video_latent *output,
                        char *error, size_t error_size);
int h3_video_encoder_block0_qualification(
    const char *weight_directory, const char *model_path,
    const float *input, size_t input_count, float *metal_output,
    float *coreml_output, size_t output_count,
    h3_ane_diagnostic *diagnostic,
    char *error, size_t error_size);
#ifdef H3_ANE_TESTING
int h3_video_encoder_test_ane_candidate(
    int frames, int encoder_height, int encoder_width, int level, int block,
    uint32_t depth, uint32_t height, uint32_t width,
    uint32_t input_channels, uint32_t output_channels);
#endif
void h3_video_latent_free(h3_video_latent *latent);

#endif
