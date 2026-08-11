#ifndef H3_ANE_INTERNAL_H
#define H3_ANE_INTERNAL_H

#include "h3_ane.h"

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
