#ifndef H3_ANE_RECEIPT_H
#define H3_ANE_RECEIPT_H

#include "h3_weights.h"

#include <stddef.h>
#include <stdint.h>

typedef enum {
    H3_ANE_DTYPE_F32 = 1
} h3_ane_dtype;

typedef struct {
    uint32_t version;
    char variant[16];
    uint32_t block_level;
    uint32_t block_index;
    char weight_prefix[64];
    h3_ane_dtype boundary_dtype;
    uint32_t shape[5];
    char source_sha256[65];
} h3_ane_contract;

typedef struct {
    uint32_t version;
    char model_sha256[65];
    char source_sha256[65];
    char test_vector[32];
    char qualified_at[32];
    double max_abs;
    double relative_l2;
    int passed;
} h3_ane_receipt;

int h3_ane_sha256_directory(const char *path, char out[65],
                            char *error, size_t error_size);
int h3_ane_sha256_tensors(const h3_weight_store *store,
                          const char *const *names, size_t name_count,
                          char out[65], char *error, size_t error_size);
int h3_ane_receipt_load(const char *path, h3_ane_receipt *out,
                        char *error, size_t error_size);
int h3_ane_receipt_validate(const h3_ane_contract *contract,
                            const h3_ane_receipt *receipt,
                            const char model_sha256[65],
                            char *error, size_t error_size);

#endif
