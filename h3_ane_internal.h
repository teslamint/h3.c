#ifndef H3_ANE_INTERNAL_H
#define H3_ANE_INTERNAL_H

#include "h3_ane.h"

typedef struct {
    size_t (*root_count)(void *context);
    void *(*root_at)(void *context, size_t index);
    size_t (*child_count)(void *context, void *node);
    void *(*child_at)(void *context, void *node, size_t index);
    void (*usage)(void *context, void *node, h3_ane_operation_usage *usage);
} h3_ane_plan_tree_adapter;

int h3_ane_collect_plan_tree(const h3_ane_plan_tree_adapter *adapter,
                             void *context,
                             h3_ane_operation_usage **operations,
                             size_t *operation_count,
                             h3_ane_inventory_summary *summary,
                             h3_ane_diagnostic *diagnostic);
int h3_ane_reduce_inventory(const h3_ane_operation_usage *operations,
                            size_t operation_count,
                            h3_ane_inventory_summary *summary,
                            uint32_t *preferred_devices,
                            h3_ane_diagnostic *diagnostic);

h3_ane *h3_ane_create_authorized(const char *model_path,
                                 const h3_ane_contract *contract, int shadow,
                                 char *error, size_t error_size);
void h3_ane_stats_snapshot(h3_ane *ane, h3_ane_stats *stats);
void h3_ane_record_fallback(h3_ane *ane, h3_ane_reason reason,
                            h3_ane_stats *stats);
void h3_ane_record_current_attempt_fallback(h3_ane *ane,
                                            h3_ane_reason reason,
                                            h3_ane_stats *stats);

#endif
