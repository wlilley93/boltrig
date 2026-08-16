#import <Foundation/Foundation.h>

#include <libusb.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const uint16_t kPixyVendorID = 0x328f;
static const uint16_t kPixyProductID = 0x00c0;
static const uint8_t kUVCGetCurrent = 0x81;
static const uint8_t kUVCGetMinimum = 0x82;
static const uint8_t kUVCGetMaximum = 0x83;
static const uint8_t kUVCGetResolution = 0x84;
static const uint8_t kUVCGetLength = 0x85;
static const uint8_t kUVCGetInfo = 0x86;
static const uint8_t kUVCGetDefault = 0x87;
static const uint8_t kUVCSetCurrent = 0x01;
static const uint8_t kPanTiltSelector = 0x0d;
static const uint8_t kPrivacySelector = 0x11;

typedef struct {
    int32_t pan;
    int32_t tilt;
} PTZState;

typedef struct {
    libusb_context *context;
    libusb_device **list;
    ssize_t listCount;
    libusb_device *device;
    libusb_device_handle *handle;
    uint8_t interfaceNumber;
    uint8_t terminalID;
    uint8_t controlBits[4];
    uint8_t controlSize;
    char manufacturer[256];
    char product[256];
} PixyConnection;

static NSMutableDictionary *Dict(void) {
    return [NSMutableDictionary dictionary];
}

static NSMutableArray *Array(void) {
    return [NSMutableArray array];
}

static NSString *HexBytes(const unsigned char *bytes, size_t length) {
    NSMutableString *result = [NSMutableString string];
    for (size_t index = 0; index < length; index++) {
        [result appendFormat:@"%02X", bytes[index]];
    }
    return result;
}

static uint16_t ReadLE16(const unsigned char *bytes) {
    return (uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8);
}

static int32_t ReadLE32Signed(const unsigned char *bytes) {
    uint32_t value = (uint32_t)bytes[0] |
                     ((uint32_t)bytes[1] << 8) |
                     ((uint32_t)bytes[2] << 16) |
                     ((uint32_t)bytes[3] << 24);
    return (int32_t)value;
}

static void WriteLE32(unsigned char *bytes, int32_t value) {
    uint32_t unsignedValue = (uint32_t)value;
    bytes[0] = (unsigned char)(unsignedValue & 0xff);
    bytes[1] = (unsigned char)((unsignedValue >> 8) & 0xff);
    bytes[2] = (unsigned char)((unsignedValue >> 16) & 0xff);
    bytes[3] = (unsigned char)((unsignedValue >> 24) & 0xff);
}

static NSDictionary *ErrorResult(int result) {
    if (result >= 0) {
        return @{
            @"result": @(result),
            @"ok": @YES,
        };
    }
    return @{
        @"result": @(result),
        @"ok": @NO,
        @"error": [NSString stringWithUTF8String:libusb_error_name(result)],
    };
}

static int UVCTransfer(PixyConnection *connection,
                       uint8_t direction,
                       uint8_t request,
                       uint8_t selector,
                       unsigned char *data,
                       uint16_t length) {
    uint16_t wIndex = ((uint16_t)connection->terminalID << 8) | connection->interfaceNumber;
    return libusb_control_transfer(connection->handle, direction, request,
                                   (uint16_t)selector << 8, wIndex,
                                   data, length, 1000);
}

static NSDictionary *ReadControl(PixyConnection *connection,
                                  uint8_t selector,
                                  uint16_t length,
                                  BOOL signedValue,
                                  BOOL panTilt) {
    NSMutableDictionary *result = Dict();
    const struct {
        uint8_t request;
        NSString *name;
    } requests[] = {
        {kUVCGetMinimum, @"min"},
        {kUVCGetMaximum, @"max"},
        {kUVCGetResolution, @"step"},
        {kUVCGetDefault, @"default"},
        {kUVCGetCurrent, @"current"},
    };
    for (size_t index = 0; index < sizeof(requests) / sizeof(requests[0]); index++) {
        unsigned char data[8] = {0};
        int transferResult = UVCTransfer(connection, 0xa1, requests[index].request,
                                         selector, data, length);
        NSMutableDictionary *entry = [ErrorResult(transferResult) mutableCopy];
        if (transferResult > 0) {
            entry[@"bytes"] = HexBytes(data, (size_t)transferResult);
        }
        if (transferResult == length) {
            if (panTilt) {
                entry[@"value"] = @[
                    @(ReadLE32Signed(data)), @(ReadLE32Signed(data + 4))
                ];
            } else if (length == 4 && signedValue) {
                entry[@"value"] = @(ReadLE32Signed(data));
            } else if (length == 4) {
                entry[@"value"] = @((uint32_t)ReadLE32Signed(data));
            } else if (length == 2) {
                entry[@"value"] = @(ReadLE16(data));
            } else if (length == 1) {
                entry[@"value"] = @(data[0]);
            }
        }
        result[requests[index].name] = entry;
    }
    return result;
}

static BOOL ReadPTZ(PixyConnection *connection,
                    PTZState *state,
                    NSDictionary **ranges,
                    NSMutableArray *errors) {
    NSDictionary *values = ReadControl(connection, kPanTiltSelector, 8, YES, YES);
    NSDictionary *current = values[@"current"];
    NSDictionary *minimum = values[@"min"];
    NSDictionary *maximum = values[@"max"];
    NSDictionary *step = values[@"step"];
    BOOL valid = current[@"value"] != nil && minimum[@"value"] != nil &&
                 maximum[@"value"] != nil && step[@"value"] != nil;
    if (!valid) {
        [errors addObject:@{
            @"stage": @"read_ptz",
            @"control": values,
        }];
        if (ranges != NULL) *ranges = values;
        return NO;
    }
    NSArray *currentValues = current[@"value"];
    NSArray *minimumValues = minimum[@"value"];
    NSArray *maximumValues = maximum[@"value"];
    NSArray *stepValues = step[@"value"];
    if (currentValues.count != 2 || minimumValues.count != 2 ||
        maximumValues.count != 2 || stepValues.count != 2) {
        [errors addObject:@{
            @"stage": @"read_ptz",
            @"error": @"unexpected_pan_tilt_shape",
            @"control": values,
        }];
        if (ranges != NULL) *ranges = values;
        return NO;
    }
    state->pan = [currentValues[0] intValue];
    state->tilt = [currentValues[1] intValue];
    for (NSUInteger index = 0; index < 2; index++) {
        if ([stepValues[index] intValue] <= 0 ||
            [currentValues[index] intValue] < [minimumValues[index] intValue] ||
            [currentValues[index] intValue] > [maximumValues[index] intValue]) {
            [errors addObject:@{
                @"stage": @"validate_ptz",
                @"axis": index == 0 ? @"pan" : @"tilt",
                @"error": @"invalid_current_or_step",
                @"control": values,
            }];
            valid = NO;
        }
    }
    if (ranges != NULL) *ranges = values;
    return valid;
}

static NSDictionary *WritePTZ(PixyConnection *connection, PTZState target) {
    unsigned char data[8] = {0};
    WriteLE32(data, target.pan);
    WriteLE32(data + 4, target.tilt);
    int transferResult = UVCTransfer(connection, 0x21, kUVCSetCurrent,
                                     kPanTiltSelector, data, sizeof(data));
    NSMutableDictionary *result = [ErrorResult(transferResult) mutableCopy];
    result[@"requested"] = @[@(target.pan), @(target.tilt)];
    result[@"bytes"] = HexBytes(data, sizeof(data));
    return result;
}

static BOOL FindCameraTerminal(PixyConnection *connection, struct libusb_config_descriptor *config) {
    for (uint8_t interfaceIndex = 0; interfaceIndex < config->bNumInterfaces; interfaceIndex++) {
        const struct libusb_interface *interface = &config->interface[interfaceIndex];
        for (int alternateIndex = 0; alternateIndex < interface->num_altsetting; alternateIndex++) {
            const struct libusb_interface_descriptor *alternate = &interface->altsetting[alternateIndex];
            if (alternate->bInterfaceClass != 0x0e || alternate->bInterfaceSubClass != 0x01 ||
                alternate->bAlternateSetting != 0 || alternate->extra == NULL) {
                continue;
            }
            for (int offset = 0; offset + 2 <= alternate->extra_length;) {
                uint8_t descriptorLength = alternate->extra[offset];
                if (descriptorLength < 2 || offset + descriptorLength > alternate->extra_length) break;
                const unsigned char *bytes = (const unsigned char *)alternate->extra + offset;
                if (bytes[1] == 0x24 && descriptorLength >= 15 && bytes[2] == 0x02 &&
                    ReadLE16(bytes + 4) == 0x0201) {
                    connection->interfaceNumber = alternate->bInterfaceNumber;
                    connection->terminalID = bytes[3];
                    connection->controlSize = bytes[14];
                    memset(connection->controlBits, 0, sizeof(connection->controlBits));
                    for (uint8_t index = 0; index < connection->controlSize && index < 4; index++) {
                        if (15 + index < descriptorLength) connection->controlBits[index] = bytes[15 + index];
                    }
                    return ((connection->controlBits[1] & (1u << (11 - 8))) != 0) &&
                           ((connection->controlBits[2] & (1u << (17 - 16))) != 0);
                }
                offset += descriptorLength;
            }
        }
    }
    return NO;
}

static BOOL OpenPixy(PixyConnection *connection, NSMutableArray *errors) {
    memset(connection, 0, sizeof(*connection));
    int initResult = libusb_init(&connection->context);
    if (initResult != 0) {
        [errors addObject:@{ @"stage": @"libusb_init", @"error": [NSString stringWithUTF8String:libusb_error_name(initResult)] }];
        return NO;
    }
    connection->listCount = libusb_get_device_list(connection->context, &connection->list);
    if (connection->listCount < 0) {
        [errors addObject:@{ @"stage": @"get_device_list", @"error": [NSString stringWithUTF8String:libusb_error_name((int)connection->listCount)] }];
        return NO;
    }
    struct libusb_device_descriptor descriptor;
    memset(&descriptor, 0, sizeof(descriptor));
    for (ssize_t index = 0; index < connection->listCount; index++) {
        struct libusb_device_descriptor candidate;
        if (libusb_get_device_descriptor(connection->list[index], &candidate) != 0) continue;
        if (candidate.idVendor == kPixyVendorID && candidate.idProduct == kPixyProductID) {
            connection->device = connection->list[index];
            descriptor = candidate;
            break;
        }
    }
    if (connection->device == NULL) {
        [errors addObject:@{ @"stage": @"identify", @"error": @"exact_vid_pid_not_present" }];
        return NO;
    }
    int openResult = libusb_open(connection->device, &connection->handle);
    if (openResult != 0 || connection->handle == NULL) {
        [errors addObject:@{ @"stage": @"open", @"error": [NSString stringWithUTF8String:libusb_error_name(openResult)] }];
        return NO;
    }
    unsigned char buffer[256] = {0};
    int length = libusb_get_string_descriptor_ascii(connection->handle, descriptor.iManufacturer, buffer, sizeof(buffer));
    if (length > 0) {
        memcpy(connection->manufacturer, buffer, (size_t)length);
        connection->manufacturer[length] = '\0';
    }
    memset(buffer, 0, sizeof(buffer));
    length = libusb_get_string_descriptor_ascii(connection->handle, descriptor.iProduct, buffer, sizeof(buffer));
    if (length > 0) {
        memcpy(connection->product, buffer, (size_t)length);
        connection->product[length] = '\0';
    }
    if (strcmp(connection->manufacturer, "EMEET") != 0 || strcmp(connection->product, "EMEET PIXY") != 0) {
        [errors addObject:@{
            @"stage": @"identify",
            @"error": @"vid_pid_string_mismatch",
            @"manufacturer": [NSString stringWithUTF8String:connection->manufacturer],
            @"product": [NSString stringWithUTF8String:connection->product],
        }];
        return NO;
    }
    struct libusb_config_descriptor *config = NULL;
    int configResult = libusb_get_active_config_descriptor(connection->device, &config);
    if (configResult != 0 || config == NULL) {
        [errors addObject:@{ @"stage": @"configuration", @"error": [NSString stringWithUTF8String:libusb_error_name(configResult)] }];
        return NO;
    }
    BOOL terminalFound = FindCameraTerminal(connection, config);
    libusb_free_config_descriptor(config);
    if (!terminalFound) {
        [errors addObject:@{ @"stage": @"configuration", @"error": @"camera_terminal_or_controls_not_found" }];
        return NO;
    }
    return YES;
}

static void ClosePixy(PixyConnection *connection) {
    if (connection->handle != NULL) {
        libusb_close(connection->handle);
        connection->handle = NULL;
    }
    if (connection->list != NULL) {
        libusb_free_device_list(connection->list, 1);
        connection->list = NULL;
    }
    if (connection->context != NULL) {
        libusb_exit(connection->context);
        connection->context = NULL;
    }
}

static NSDictionary *RunPTZTest(NSString *axis, unsigned int holdMilliseconds) {
    NSMutableDictionary *report = Dict();
    report[@"control_mechanism"] = @"standard_uvc_camera_terminal_pan_tilt_absolute";
    report[@"hid_reports_sent"] = @NO;
    report[@"zoom_or_focus_writes"] = @NO;
    report[@"axis"] = axis;
    report[@"hold_milliseconds"] = @(holdMilliseconds);
    NSMutableArray *errors = Array();
    PixyConnection connection;
    BOOL opened = OpenPixy(&connection, errors);
    report[@"reidentification"] = @{
        @"vid": @"0x328F",
        @"pid": @"0x00C0",
        @"manufacturer": opened ? [NSString stringWithUTF8String:connection.manufacturer] : [NSNull null],
        @"product": opened ? [NSString stringWithUTF8String:connection.product] : [NSNull null],
        @"exact_match": @(opened),
        @"previous_probe_match": @(opened),
    };
    if (!opened) {
        report[@"errors"] = errors;
        ClosePixy(&connection);
        return report;
    }
    report[@"uvc_interface"] = @(connection.interfaceNumber);
    report[@"camera_terminal_id"] = @(connection.terminalID);
    report[@"control_size"] = @(connection.controlSize);

    PTZState original = {0, 0};
    NSDictionary *ranges = nil;
    BOOL readOK = ReadPTZ(&connection, &original, &ranges, errors);
    report[@"starting_ptz"] = @[@(original.pan), @(original.tilt)];
    report[@"advertised"] = ranges != nil ? ranges : @{};
    if (!readOK) {
        report[@"errors"] = errors;
        ClosePixy(&connection);
        return report;
    }
    NSArray *minValues = ranges[@"min"][@"value"];
    NSArray *maxValues = ranges[@"max"][@"value"];
    NSArray *stepValues = ranges[@"step"][@"value"];
    NSUInteger axisIndex = [axis isEqualToString:@"pan"] ? 0 : 1;
    int32_t requestedDelta = [stepValues[axisIndex] intValue];
    int32_t currentValue = axisIndex == 0 ? original.pan : original.tilt;
    int32_t maximumValue = [maxValues[axisIndex] intValue];
    int32_t minimumValue = [minValues[axisIndex] intValue];
    BOOL positiveSafe = requestedDelta > 0 && currentValue <= maximumValue - requestedDelta;
    BOOL insideRange = currentValue >= minimumValue && currentValue <= maximumValue;
    report[@"requested_delta"] = @(requestedDelta);
    report[@"limit_check"] = @{
        @"positive_step_within_advertised_limits": @(positiveSafe),
        @"starting_value_inside_limits": @(insideRange),
        @"limits_approached": @NO,
    };
    if (!positiveSafe || !insideRange) {
        [errors addObject:@{ @"stage": @"validate_target", @"error": @"no_safe_one_step_target" }];
        report[@"errors"] = errors;
        ClosePixy(&connection);
        return report;
    }

    PTZState target = original;
    if (axisIndex == 0) target.pan += requestedDelta;
    else target.tilt += requestedDelta;
    report[@"requested_position"] = @[@(target.pan), @(target.tilt)];
    report[@"move"] = WritePTZ(&connection, target);
    if ([report[@"move"][@"result"] intValue] == 8) {
        usleep(holdMilliseconds * 1000u);
        PTZState observed = {0, 0};
        NSDictionary *observedRanges = nil;
        if (ReadPTZ(&connection, &observed, &observedRanges, errors)) {
            report[@"observed_readback"] = @[@(observed.pan), @(observed.tilt)];
        } else {
            report[@"observed_readback"] = [NSNull null];
        }
    } else {
        report[@"observed_readback"] = [NSNull null];
    }
    report[@"restore"] = WritePTZ(&connection, original);
    PTZState restored = {0, 0};
    NSDictionary *restoredRanges = nil;
    if (ReadPTZ(&connection, &restored, &restoredRanges, errors)) {
        report[@"restored_readback"] = @[@(restored.pan), @(restored.tilt)];
        report[@"restoration_succeeded"] = @(restored.pan == original.pan && restored.tilt == original.tilt);
    } else {
        report[@"restored_readback"] = [NSNull null];
        report[@"restoration_succeeded"] = @NO;
    }
    report[@"final_ptz"] = report[@"restored_readback"];
    report[@"errors"] = errors;
    ClosePixy(&connection);
    report[@"handles_closed"] = @YES;
    return report;
}

static NSDictionary *ReadPrivacy(void) {
    NSMutableDictionary *report = Dict();
    report[@"control_mechanism"] = @"standard_uvc_camera_terminal_privacy";
    report[@"write_performed"] = @NO;
    report[@"hid_reports_sent"] = @NO;
    NSMutableArray *errors = Array();
    PixyConnection connection;
    BOOL opened = OpenPixy(&connection, errors);
    report[@"reidentification"] = @{
        @"vid": @"0x328F",
        @"pid": @"0x00C0",
        @"manufacturer": opened ? [NSString stringWithUTF8String:connection.manufacturer] : [NSNull null],
        @"product": opened ? [NSString stringWithUTF8String:connection.product] : [NSNull null],
        @"exact_match": @(opened),
        @"previous_probe_match": @(opened),
    };
    if (!opened) {
        report[@"errors"] = errors;
        ClosePixy(&connection);
        return report;
    }
    report[@"uvc_interface"] = @(connection.interfaceNumber);
    report[@"camera_terminal_id"] = @(connection.terminalID);
    unsigned char info[1] = {0};
    int infoResult = UVCTransfer(&connection, 0xa1, kUVCGetInfo, kPrivacySelector, info, sizeof(info));
    report[@"get_info"] = ErrorResult(infoResult);
    if (infoResult == 1) report[@"get_info"] = @{ @"result": @(infoResult), @"ok": @YES, @"readable": @((info[0] & 1) != 0), @"writable": @((info[0] & 2) != 0), @"bytes": HexBytes(info, 1) };
    unsigned char lengthData[2] = {0};
    int lengthResult = UVCTransfer(&connection, 0xa1, kUVCGetLength, kPrivacySelector, lengthData, sizeof(lengthData));
    report[@"get_len"] = ErrorResult(lengthResult);
    report[@"get_len_bytes"] = lengthResult > 0 ? HexBytes(lengthData, (size_t)lengthResult) : @"";
    report[@"standard_boolean_reads"] = ReadControl(&connection, kPrivacySelector, 1, NO, NO);
    NSDictionary *reads = report[@"standard_boolean_reads"];
    BOOL booleanDomain = YES;
    for (NSString *key in @[@"min", @"max", @"step", @"default", @"current"]) {
        NSDictionary *entry = reads[key];
        NSNumber *value = entry[@"value"];
        if (value == nil || value.intValue > 1) booleanDomain = NO;
    }
    report[@"standard_boolean_semantics_clear"] = @(booleanDomain);
    if (!booleanDomain) {
        [errors addObject:@{
            @"stage": @"privacy_semantics",
            @"error": @"advertised_boolean_returns_value_outside_0_or_1",
        }];
    }
    report[@"privacy_write_policy"] = booleanDomain ? @"not_attempted_in_this_read_only_phase" : @"not_safe_to_write";
    report[@"errors"] = errors;
    ClosePixy(&connection);
    report[@"handles_closed"] = @YES;
    return report;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 2 || (strcmp(argv[1], "pan") != 0 && strcmp(argv[1], "tilt") != 0 && strcmp(argv[1], "privacy") != 0)) {
            fprintf(stderr, "usage: pixy-ptz-test pan|tilt|privacy [hold_milliseconds]\n");
            return 2;
        }
        NSDictionary *report = nil;
        if (strcmp(argv[1], "privacy") == 0) {
            report = ReadPrivacy();
        } else {
            unsigned int holdMilliseconds = 3000;
            if (argc >= 3) {
                char *end = NULL;
                unsigned long parsed = strtoul(argv[2], &end, 10);
                if (end == argv[2] || *end != '\0' || parsed > 10000) {
                    fprintf(stderr, "hold_milliseconds must be 0..10000\n");
                    return 2;
                }
                holdMilliseconds = (unsigned int)parsed;
            }
            report = RunPTZTest([NSString stringWithUTF8String:argv[1]], holdMilliseconds);
        }
        NSError *error = nil;
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:&error];
        if (json == nil) {
            fprintf(stderr, "pixy-ptz-test: failed to encode JSON: %s\n", error.localizedDescription.UTF8String);
            return 1;
        }
        fwrite(json.bytes, 1, json.length, stdout);
        fputc('\n', stdout);
        return [report[@"errors"] count] == 0 ? 0 : 1;
    }
}
