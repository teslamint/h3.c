#include "h3_ane_receipt.h"

#include <CommonCrypto/CommonDigest.h>

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { RECEIPT_LIMIT = 65536, HASH_BUFFER_SIZE = 65536 };

typedef struct {
    char *relative;
    char *absolute;
    off_t size;
} digest_file;

typedef struct {
    digest_file *items;
    size_t count;
    size_t capacity;
} digest_files;

typedef struct {
    const char *cursor;
    const char *end;
} json_reader;

static void fail(char *error, size_t error_size, const char *format, ...) {
    if (!error || error_size == 0) return;
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(error, error_size, format, arguments);
    va_end(arguments);
}

static char *copy_string(const char *value) {
    size_t length = strlen(value) + 1;
    char *copy = malloc(length);
    if (copy) memcpy(copy, value, length);
    return copy;
}

static int join_path(const char *left, const char *right, char **out) {
    size_t left_length = strlen(left);
    size_t right_length = strlen(right);
    if (left_length > SIZE_MAX - right_length - 2) return 0;
    char *path = malloc(left_length + right_length + 2);
    if (!path) return 0;
    snprintf(path, left_length + right_length + 2, "%s/%s", left, right);
    *out = path;
    return 1;
}

static void free_digest_files(digest_files *files) {
    for (size_t index = 0; index < files->count; index++) {
        free(files->items[index].relative);
        free(files->items[index].absolute);
    }
    free(files->items);
    memset(files, 0, sizeof(*files));
}

static int append_digest_file(digest_files *files, const char *relative,
                              const char *absolute, off_t size,
                              char *error, size_t error_size) {
    if (files->count == files->capacity) {
        size_t next = files->capacity ? files->capacity * 2 : 16;
        if (next < files->capacity || next > SIZE_MAX / sizeof(*files->items)) {
            fail(error, error_size, "compiled-model file list is too large");
            return 0;
        }
        digest_file *grown = realloc(files->items,
                                     next * sizeof(*files->items));
        if (!grown) {
            fail(error, error_size, "out of memory listing compiled model");
            return 0;
        }
        files->items = grown;
        files->capacity = next;
    }
    digest_file *item = &files->items[files->count];
    item->relative = copy_string(relative);
    item->absolute = copy_string(absolute);
    item->size = size;
    if (!item->relative || !item->absolute) {
        free(item->relative);
        free(item->absolute);
        fail(error, error_size, "out of memory recording compiled-model file");
        return 0;
    }
    files->count++;
    return 1;
}

static int collect_directory(const char *root, const char *relative,
                             digest_files *files,
                             char *error, size_t error_size) {
    char *directory = NULL;
    if (*relative) {
        if (!join_path(root, relative, &directory)) {
            fail(error, error_size, "compiled-model path is too long");
            return 0;
        }
    } else {
        directory = copy_string(root);
        if (!directory) {
            fail(error, error_size, "out of memory resolving compiled model");
            return 0;
        }
    }
    DIR *stream = opendir(directory);
    if (!stream) {
        fail(error, error_size, "cannot open compiled-model directory: %s",
             strerror(errno));
        free(directory);
        return 0;
    }
    int result = 1;
    struct dirent *entry;
    while (result && (entry = readdir(stream)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 ||
            strcmp(entry->d_name, "..") == 0) continue;
        char *child_relative = NULL;
        char *child_absolute = NULL;
        if (*relative) {
            if (!join_path(relative, entry->d_name, &child_relative)) result = 0;
        } else {
            child_relative = copy_string(entry->d_name);
            if (!child_relative) result = 0;
        }
        if (result && !join_path(root, child_relative, &child_absolute)) result = 0;
        if (!result) {
            fail(error, error_size, "out of memory resolving compiled-model path");
            free(child_relative);
            free(child_absolute);
            break;
        }
        struct stat status;
        if (lstat(child_absolute, &status) != 0) {
            fail(error, error_size, "cannot inspect compiled-model entry %s: %s",
                 child_relative, strerror(errno));
            result = 0;
        } else if (S_ISLNK(status.st_mode)) {
            fail(error, error_size,
                 "compiled-model symlink is not allowed: %s", child_relative);
            result = 0;
        } else if (S_ISDIR(status.st_mode)) {
            result = collect_directory(root, child_relative, files,
                                       error, error_size);
        } else if (S_ISREG(status.st_mode)) {
            result = append_digest_file(files, child_relative, child_absolute,
                                        status.st_size, error, error_size);
        } else {
            fail(error, error_size,
                 "unsupported compiled-model entry: %s", child_relative);
            result = 0;
        }
        free(child_relative);
        free(child_absolute);
    }
    closedir(stream);
    free(directory);
    return result;
}

static int compare_digest_files(const void *left, const void *right) {
    const digest_file *a = left;
    const digest_file *b = right;
    return strcmp(a->relative, b->relative);
}

static void hash_u64(CC_SHA256_CTX *context, uint64_t value) {
    unsigned char bytes[8];
    for (size_t index = 0; index < sizeof(bytes); index++) {
        bytes[sizeof(bytes) - index - 1] = (unsigned char)(value & 0xffU);
        value >>= 8;
    }
    CC_SHA256_Update(context, bytes, (CC_LONG)sizeof(bytes));
}

static void hash_bytes(CC_SHA256_CTX *context, const void *data, size_t size) {
    const unsigned char *cursor = data;
    while (size) {
        size_t amount = size > UINT32_MAX ? UINT32_MAX : size;
        CC_SHA256_Update(context, cursor, (CC_LONG)amount);
        cursor += amount;
        size -= amount;
    }
}

static void digest_hex(const unsigned char digest[CC_SHA256_DIGEST_LENGTH],
                       char out[65]) {
    static const char hex[] = "0123456789abcdef";
    for (size_t index = 0; index < CC_SHA256_DIGEST_LENGTH; index++) {
        out[index * 2] = hex[digest[index] >> 4];
        out[index * 2 + 1] = hex[digest[index] & 15U];
    }
    out[64] = '\0';
}

static int hash_file(CC_SHA256_CTX *context, const char *path, off_t expected,
                     char *error, size_t error_size) {
    int descriptor = open(path, O_RDONLY | O_NOFOLLOW);
    if (descriptor < 0) {
        fail(error, error_size, "cannot open compiled-model file: %s",
             strerror(errno));
        return 0;
    }
    struct stat status;
    if (fstat(descriptor, &status) != 0 || !S_ISREG(status.st_mode) ||
        status.st_size != expected) {
        fail(error, error_size, "compiled-model file changed while hashing");
        close(descriptor);
        return 0;
    }
    unsigned char buffer[HASH_BUFFER_SIZE];
    ssize_t amount;
    while ((amount = read(descriptor, buffer, sizeof(buffer))) > 0) {
        hash_bytes(context, buffer, (size_t)amount);
    }
    int result = amount == 0;
    if (!result) fail(error, error_size, "cannot read compiled-model file: %s",
                      strerror(errno));
    close(descriptor);
    return result;
}

int h3_ane_sha256_directory(const char *path, char out[65],
                            char *error, size_t error_size) {
    if (!path || !*path || !out) {
        fail(error, error_size, "compiled-model directory and digest are required");
        return 0;
    }
    struct stat root_status;
    if (lstat(path, &root_status) != 0 || !S_ISDIR(root_status.st_mode) ||
        S_ISLNK(root_status.st_mode)) {
        fail(error, error_size, "compiled-model path is not a real directory");
        return 0;
    }
    digest_files files = {0};
    if (!collect_directory(path, "", &files, error, error_size)) {
        free_digest_files(&files);
        return 0;
    }
    qsort(files.items, files.count, sizeof(*files.items), compare_digest_files);
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    static const char domain[] = "h3-ane-directory-v1";
    hash_bytes(&context, domain, sizeof(domain) - 1);
    hash_u64(&context, (uint64_t)files.count);
    int result = 1;
    for (size_t index = 0; result && index < files.count; index++) {
        size_t relative_size = strlen(files.items[index].relative);
        hash_u64(&context, (uint64_t)relative_size);
        hash_bytes(&context, files.items[index].relative, relative_size);
        hash_u64(&context, (uint64_t)files.items[index].size);
        result = hash_file(&context, files.items[index].absolute,
                           files.items[index].size, error, error_size);
    }
    if (result) {
        unsigned char digest[CC_SHA256_DIGEST_LENGTH];
        CC_SHA256_Final(digest, &context);
        digest_hex(digest, out);
    }
    free_digest_files(&files);
    return result;
}

int h3_ane_sha256_tensors(const h3_weight_store *store,
                          const char *const *names, size_t name_count,
                          char out[65], char *error, size_t error_size) {
    if (!store || !names || name_count == 0 || !out) {
        fail(error, error_size, "weight store, tensor names, and digest are required");
        return 0;
    }
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    static const char domain[] = "h3-ane-tensors-v1";
    hash_bytes(&context, domain, sizeof(domain) - 1);
    hash_u64(&context, (uint64_t)name_count);
    unsigned char buffer[HASH_BUFFER_SIZE];
    for (size_t index = 0; index < name_count; index++) {
        if (!names[index] || !*names[index]) {
            fail(error, error_size, "tensor name is required");
            return 0;
        }
        const h3_st_header *header = NULL;
        const h3_st_tensor *tensor = h3_weight_find(store, names[index], &header);
        if (!tensor || !header) {
            fail(error, error_size, "required weight is absent: %s", names[index]);
            return 0;
        }
        if (tensor->data_end < tensor->data_begin) {
            fail(error, error_size, "weight has invalid byte range: %s", names[index]);
            return 0;
        }
        size_t name_size = strlen(names[index]);
        hash_u64(&context, (uint64_t)name_size);
        hash_bytes(&context, names[index], name_size);
        hash_u64(&context, (uint64_t)tensor->dtype);
        hash_u64(&context, (uint64_t)tensor->ndim);
        for (int dimension = 0; dimension < tensor->ndim; dimension++)
            hash_u64(&context, tensor->shape[dimension]);
        uint64_t bytes = tensor->data_end - tensor->data_begin;
        hash_u64(&context, bytes);
        int descriptor = open(header->path, O_RDONLY | O_NOFOLLOW);
        if (descriptor < 0) {
            fail(error, error_size, "cannot open weight shard: %s", strerror(errno));
            return 0;
        }
        uint64_t offset = tensor->file_offset;
        uint64_t remaining = bytes;
        int result = 1;
        while (remaining) {
            size_t requested = remaining > sizeof(buffer) ? sizeof(buffer) :
                               (size_t)remaining;
            ssize_t amount = pread(descriptor, buffer, requested, (off_t)offset);
            if (amount <= 0) {
                fail(error, error_size, "cannot read weight bytes for %s",
                     names[index]);
                result = 0;
                break;
            }
            hash_bytes(&context, buffer, (size_t)amount);
            offset += (uint64_t)amount;
            remaining -= (uint64_t)amount;
        }
        close(descriptor);
        if (!result) return 0;
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest, &context);
    digest_hex(digest, out);
    return 1;
}

static void skip_space(json_reader *reader) {
    while (reader->cursor < reader->end &&
           isspace((unsigned char)*reader->cursor)) reader->cursor++;
}

static int take(json_reader *reader, char expected) {
    skip_space(reader);
    if (reader->cursor == reader->end || *reader->cursor != expected) return 0;
    reader->cursor++;
    return 1;
}

static int json_string(json_reader *reader, char *out, size_t out_size) {
    if (!take(reader, '\"') || out_size == 0) return 0;
    size_t length = 0;
    while (reader->cursor < reader->end && *reader->cursor != '\"') {
        unsigned char value = (unsigned char)*reader->cursor++;
        if (value < 0x20 || value == '\\') return 0;
        if (length + 1 >= out_size) return 0;
        out[length++] = (char)value;
    }
    if (reader->cursor == reader->end) return 0;
    reader->cursor++;
    out[length] = '\0';
    return 1;
}

static int json_double(json_reader *reader, double *out) {
    skip_space(reader);
    if (reader->cursor == reader->end) return 0;
    const char *scan = reader->cursor;
    if (*scan == '-') {
        scan++;
        if (scan == reader->end) return 0;
    }
    if (*scan == '0') {
        scan++;
        if (scan < reader->end && isdigit((unsigned char)*scan)) return 0;
    } else if (*scan >= '1' && *scan <= '9') {
        do scan++; while (scan < reader->end &&
                          isdigit((unsigned char)*scan));
    } else {
        return 0;
    }
    if (scan < reader->end && *scan == '.') {
        scan++;
        if (scan == reader->end || !isdigit((unsigned char)*scan)) return 0;
        do scan++; while (scan < reader->end &&
                          isdigit((unsigned char)*scan));
    }
    if (scan < reader->end && (*scan == 'e' || *scan == 'E')) {
        scan++;
        if (scan < reader->end && (*scan == '+' || *scan == '-')) scan++;
        if (scan == reader->end || !isdigit((unsigned char)*scan)) return 0;
        do scan++; while (scan < reader->end &&
                          isdigit((unsigned char)*scan));
    }
    errno = 0;
    char *after = NULL;
    double value = strtod(reader->cursor, &after);
    if (after != scan || errno == ERANGE ||
        !isfinite(value)) return 0;
    reader->cursor = scan;
    *out = value;
    return 1;
}

static int json_u32(json_reader *reader, uint32_t *out) {
    skip_space(reader);
    if (reader->cursor == reader->end || !isdigit((unsigned char)*reader->cursor))
        return 0;
    uint64_t value = 0;
    do {
        unsigned digit = (unsigned)(*reader->cursor - '0');
        if (value > (UINT32_MAX - digit) / 10U) return 0;
        value = value * 10U + digit;
        reader->cursor++;
    } while (reader->cursor < reader->end &&
             isdigit((unsigned char)*reader->cursor));
    *out = (uint32_t)value;
    return 1;
}

static int valid_sha256(const char value[65]) {
    if (!value || strlen(value) != 64) return 0;
    for (size_t index = 0; index < 64; index++) {
        if (!((value[index] >= '0' && value[index] <= '9') ||
              (value[index] >= 'a' && value[index] <= 'f'))) return 0;
    }
    return 1;
}

int h3_ane_receipt_load(const char *path, h3_ane_receipt *out,
                        char *error, size_t error_size) {
    if (!path || !*path || !out) {
        fail(error, error_size, "receipt path and output are required");
        return 0;
    }
    int descriptor = open(path, O_RDONLY | O_NOFOLLOW);
    if (descriptor < 0) {
        fail(error, error_size, "cannot open qualification receipt: %s",
             strerror(errno));
        return 0;
    }
    struct stat status;
    if (fstat(descriptor, &status) != 0 || !S_ISREG(status.st_mode) ||
        status.st_size <= 0 || status.st_size > RECEIPT_LIMIT) {
        fail(error, error_size, "qualification receipt has invalid size");
        close(descriptor);
        return 0;
    }
    size_t size = (size_t)status.st_size;
    char *contents = malloc(size + 1);
    if (!contents) {
        fail(error, error_size, "out of memory reading qualification receipt");
        close(descriptor);
        return 0;
    }
    size_t used = 0;
    while (used < size) {
        ssize_t amount = read(descriptor, contents + used, size - used);
        if (amount <= 0) break;
        used += (size_t)amount;
    }
    close(descriptor);
    if (used != size) {
        fail(error, error_size, "cannot read complete qualification receipt");
        free(contents);
        return 0;
    }
    contents[size] = '\0';
    json_reader reader = {.cursor = contents, .end = contents + size};
    h3_ane_receipt parsed = {0};
    unsigned fields = 0;
    int result = take(&reader, '{');
    while (result) {
        skip_space(&reader);
        if (reader.cursor < reader.end && *reader.cursor == '}') {
            reader.cursor++;
            break;
        }
        char key[32];
        if (!json_string(&reader, key, sizeof(key)) || !take(&reader, ':')) {
            result = 0;
            break;
        }
        unsigned bit = 0;
        if (strcmp(key, "version") == 0) {
            bit = 1U << 0;
            result = json_u32(&reader, &parsed.version);
        } else if (strcmp(key, "model_sha256") == 0) {
            bit = 1U << 1;
            result = json_string(&reader, parsed.model_sha256,
                                 sizeof(parsed.model_sha256));
        } else if (strcmp(key, "source_sha256") == 0) {
            bit = 1U << 2;
            result = json_string(&reader, parsed.source_sha256,
                                 sizeof(parsed.source_sha256));
        } else if (strcmp(key, "test_vector") == 0) {
            bit = 1U << 3;
            result = json_string(&reader, parsed.test_vector,
                                 sizeof(parsed.test_vector));
        } else if (strcmp(key, "qualified_at") == 0) {
            bit = 1U << 4;
            result = json_string(&reader, parsed.qualified_at,
                                 sizeof(parsed.qualified_at));
        } else if (strcmp(key, "max_abs") == 0) {
            bit = 1U << 5;
            result = json_double(&reader, &parsed.max_abs);
        } else if (strcmp(key, "relative_l2") == 0) {
            bit = 1U << 6;
            result = json_double(&reader, &parsed.relative_l2);
        } else if (strcmp(key, "status") == 0) {
            char value[16];
            bit = 1U << 7;
            result = json_string(&reader, value, sizeof(value));
            if (result && strcmp(value, "passed") == 0) parsed.passed = 1;
            else if (result && strcmp(value, "failed") == 0) parsed.passed = 0;
            else result = 0;
        } else {
            result = 0;
        }
        if (!result || (fields & bit) != 0) {
            result = 0;
            break;
        }
        fields |= bit;
        skip_space(&reader);
        if (reader.cursor < reader.end && *reader.cursor == ',') {
            reader.cursor++;
            continue;
        }
        if (reader.cursor < reader.end && *reader.cursor == '}') {
            reader.cursor++;
            break;
        }
        result = 0;
    }
    skip_space(&reader);
    if (!result || fields != 0xffU || reader.cursor != reader.end ||
        !valid_sha256(parsed.model_sha256) ||
        !valid_sha256(parsed.source_sha256) || !*parsed.test_vector ||
        !*parsed.qualified_at) {
        fail(error, error_size, "qualification receipt is malformed or incomplete");
        free(contents);
        return 0;
    }
    *out = parsed;
    free(contents);
    return 1;
}

int h3_ane_receipt_validate(const h3_ane_contract *contract,
                            const h3_ane_receipt *receipt,
                            const char model_sha256[65],
                            char *error, size_t error_size) {
    if (!contract || !receipt || !model_sha256) {
        fail(error, error_size, "ANE contract, receipt, and model digest are required");
        return 0;
    }
    if (contract->version != 1 || receipt->version != contract->version) {
        fail(error, error_size, "unsupported ANE receipt contract version");
        return 0;
    }
    if (!*contract->variant || !*contract->weight_prefix ||
        contract->boundary_dtype != H3_ANE_DTYPE_F32) {
        fail(error, error_size, "ANE model contract is incomplete");
        return 0;
    }
    for (size_t index = 0; index < 5; index++) {
        if (contract->shape[index] == 0) {
            fail(error, error_size, "ANE model contract has an empty dimension");
            return 0;
        }
    }
    if (!valid_sha256(contract->source_sha256) ||
        !valid_sha256(receipt->source_sha256) ||
        !valid_sha256(receipt->model_sha256) || !valid_sha256(model_sha256)) {
        fail(error, error_size, "ANE receipt contains a malformed SHA-256 digest");
        return 0;
    }
    if (strcmp(receipt->source_sha256, contract->source_sha256) != 0) {
        fail(error, error_size, "ANE receipt source fingerprint does not match weights");
        return 0;
    }
    if (strcmp(receipt->model_sha256, model_sha256) != 0) {
        fail(error, error_size, "ANE receipt model fingerprint does not match artifact");
        return 0;
    }
    if (receipt->passed != 1) {
        fail(error, error_size, "ANE artifact has no passing qualification");
        return 0;
    }
    if (!isfinite(receipt->max_abs) || receipt->max_abs < 0.0 ||
        receipt->max_abs >= 0.002) {
        fail(error, error_size, "ANE max-absolute error is outside qualification bound");
        return 0;
    }
    if (!isfinite(receipt->relative_l2) || receipt->relative_l2 < 0.0 ||
        receipt->relative_l2 >= 0.02) {
        fail(error, error_size, "ANE relative-L2 error is outside qualification bound");
        return 0;
    }
    return 1;
}
