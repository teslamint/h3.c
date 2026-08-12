#import <Foundation/Foundation.h>
#import <CoreML/CoreML.h>

static NSString *device_name(id<MLComputeDeviceProtocol> device) {
    if ([device isKindOfClass:[MLCPUComputeDevice class]]) return @"cpu";
    if ([device isKindOfClass:[MLGPUComputeDevice class]]) return @"gpu";
    if ([device isKindOfClass:[MLNeuralEngineComputeDevice class]])
        return @"neural-engine";
    return nil;
}

static void walk(MLComputePlan *plan,
                 NSArray<MLModelStructureProgramOperation *> *operations,
                 NSUInteger *total, NSUInteger *nonconstant,
                 NSUInteger *nonconstant_with_ane,
                 NSUInteger *unknown_nonconstant,
                 NSUInteger *constant_nil_usage) API_AVAILABLE(macos(14.4)) {
    for (MLModelStructureProgramOperation *operation in operations) {
        (*total)++;
        BOOL constant = [operation.operatorName isEqualToString:@"const"];
        if (!constant) (*nonconstant)++;
        MLComputePlanDeviceUsage *usage =
            [plan computeDeviceUsageForMLProgramOperation:operation];
        if (constant && !usage) (*constant_nil_usage)++;
        BOOL supports_ane = NO;
        NSMutableArray<NSString *> *supported = [NSMutableArray array];
        for (id<MLComputeDeviceProtocol> device in usage.supportedComputeDevices) {
            NSString *name = device_name(device);
            if (name) [supported addObject:name];
            if ([device isKindOfClass:[MLNeuralEngineComputeDevice class]])
                supports_ane = YES;
        }
        NSString *preferred = device_name(usage.preferredComputeDevice);
        if (!constant && (!usage || !preferred || supported.count == 0))
            (*unknown_nonconstant)++;
        if (!constant && supports_ane) (*nonconstant_with_ane)++;
        printf("operation name=%s constant=%d supported=%s preferred=%s\n",
               operation.operatorName.UTF8String ?: "unknown", constant,
               [[supported componentsJoinedByString:@","] UTF8String] ?: "unknown",
               preferred.UTF8String ?: "unknown");
        for (MLModelStructureProgramBlock *block in operation.blocks)
            walk(plan, block.operations, total, nonconstant,
                 nonconstant_with_ane, unknown_nonconstant,
                 constant_nil_usage);
    }
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 64;
        if (!@available(macOS 14.4, *)) return 2;
        NSURL *url = [NSURL fileURLWithPath:
            [NSString stringWithUTF8String:argv[1]]];
        MLModelConfiguration *configuration = [[MLModelConfiguration alloc] init];
        configuration.computeUnits = MLComputeUnitsCPUAndNeuralEngine;
        __block MLComputePlan *loaded = nil;
        dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
        [MLComputePlan loadContentsOfURL:url configuration:configuration
                      completionHandler:^(MLComputePlan *plan, NSError *error) {
            (void)error;
            loaded = plan;
            dispatch_semaphore_signal(semaphore);
        }];
        if (dispatch_semaphore_wait(
                semaphore, dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC)) ||
            !loaded) return 3;
        MLModelStructureProgramFunction *main =
            loaded.modelStructure.program.functions[@"main"];
        if (!main) return 4;
        NSUInteger total = 0, nonconstant = 0, with_ane = 0;
        NSUInteger unknown = 0, constant_nil = 0;
        walk(loaded, main.block.operations, &total, &nonconstant, &with_ane,
             &unknown, &constant_nil);
        printf("summary total=%lu nonconstant=%lu nonconstant-with-ane=%lu "
               "unknown-nonconstant=%lu constant-nil-usage=%lu\n",
               (unsigned long)total, (unsigned long)nonconstant,
               (unsigned long)with_ane, (unsigned long)unknown,
               (unsigned long)constant_nil);
        return 0;
    }
}
