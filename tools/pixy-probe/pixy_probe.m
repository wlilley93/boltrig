#import <AVFoundation/AVFoundation.h>
#import <AudioToolbox/AudioToolbox.h>
#import <CoreMedia/CoreMedia.h>
#import <Foundation/Foundation.h>

#include <libusb.h>

#include <arpa/inet.h>
#include <errno.h>
#include <ifaddrs.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const uint16_t kPixyVendorID = 0x328f;
static const uint16_t kPixyProductID = 0x00c0;

static NSString *Hex(uint32_t value, NSUInteger width) {
    return [NSString stringWithFormat:@"0x%0*X", (int)width, value];
}

static NSString *FourCC(uint32_t value) {
    char chars[5] = {
        (char)((value >> 24) & 0xff),
        (char)((value >> 16) & 0xff),
        (char)((value >> 8) & 0xff),
        (char)(value & 0xff),
        '\0',
    };
    for (int i = 0; i < 4; i++) {
        if (chars[i] < 0x20 || chars[i] > 0x7e) {
            return Hex(value, 8);
        }
    }
    return [NSString stringWithUTF8String:chars];
}

static NSMutableDictionary *MutableDictionary(void) {
    return [NSMutableDictionary dictionary];
}

static NSMutableArray *MutableArray(void) {
    return [NSMutableArray array];
}

static NSString *AVFocusModeName(AVCaptureFocusMode mode) {
    switch (mode) {
        case AVCaptureFocusModeLocked: return @"locked";
        case AVCaptureFocusModeAutoFocus: return @"autofocus";
        case AVCaptureFocusModeContinuousAutoFocus: return @"continuous_autofocus";
    }
}

static NSString *AVExposureModeName(AVCaptureExposureMode mode) {
    switch (mode) {
        case AVCaptureExposureModeLocked: return @"locked";
        case AVCaptureExposureModeAutoExpose: return @"auto_expose";
        case AVCaptureExposureModeContinuousAutoExposure: return @"continuous_auto_exposure";
        case AVCaptureExposureModeCustom: return @"custom";
    }
}

static NSString *AVWhiteBalanceModeName(AVCaptureWhiteBalanceMode mode) {
    switch (mode) {
        case AVCaptureWhiteBalanceModeLocked: return @"locked";
        case AVCaptureWhiteBalanceModeAutoWhiteBalance: return @"auto_white_balance";
        case AVCaptureWhiteBalanceModeContinuousAutoWhiteBalance: return @"continuous_auto_white_balance";
    }
}

static NSDictionary *VideoReport(void) {
    NSMutableDictionary *report = MutableDictionary();
    NSMutableArray *devices = MutableArray();
    AVCaptureDeviceDiscoverySession *session =
        [AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:@[
            AVCaptureDeviceTypeExternal
        ] mediaType:AVMediaTypeVideo position:AVCaptureDevicePositionUnspecified];

    BOOL pixyFound = NO;
    for (AVCaptureDevice *device in session.devices) {
        NSString *name = device.localizedName;
        if (name == nil) name = @"";
        if ([name rangeOfString:@"EMEET" options:NSCaseInsensitiveSearch].location == NSNotFound &&
            [name rangeOfString:@"PIXY" options:NSCaseInsensitiveSearch].location == NSNotFound) {
            continue;
        }
        pixyFound = YES;
        NSMutableDictionary *deviceReport = MutableDictionary();
        deviceReport[@"name"] = name;
        deviceReport[@"media_type"] = @"video";
        deviceReport[@"position"] = @(device.position);

        NSMutableArray *formats = MutableArray();
        for (AVCaptureDeviceFormat *format in device.formats) {
            CMVideoDimensions dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription);
            NSMutableArray *rates = MutableArray();
            for (AVFrameRateRange *range in format.videoSupportedFrameRateRanges) {
                [rates addObject:@{
                    @"min_fps": @(range.minFrameRate),
                    @"max_fps": @(range.maxFrameRate),
                }];
            }
            [formats addObject:@{
                @"width": @(dimensions.width),
                @"height": @(dimensions.height),
                @"pixel_format": FourCC(CMFormatDescriptionGetMediaSubType(format.formatDescription)),
                @"frame_rates": rates,
            }];
        }
        deviceReport[@"formats"] = formats;
        deviceReport[@"controls"] = @{
            @"focus": @{
                @"readable": @YES,
                @"writable": @NO,
                @"supported_modes": @[
                    AVFocusModeName(AVCaptureFocusModeLocked),
                    AVFocusModeName(AVCaptureFocusModeAutoFocus),
                    AVFocusModeName(AVCaptureFocusModeContinuousAutoFocus),
                ],
                @"supported": @{
                    @"locked": @( [device isFocusModeSupported:AVCaptureFocusModeLocked] ),
                    @"autofocus": @( [device isFocusModeSupported:AVCaptureFocusModeAutoFocus] ),
                    @"continuous_autofocus": @( [device isFocusModeSupported:AVCaptureFocusModeContinuousAutoFocus] ),
                },
                @"current": AVFocusModeName(device.focusMode),
                @"point_of_interest": @(device.focusPointOfInterestSupported),
            },
            @"exposure": @{
                @"readable": @YES,
                @"writable": @NO,
                @"supported": @{
                    @"locked": @( [device isExposureModeSupported:AVCaptureExposureModeLocked] ),
                    @"auto_expose": @( [device isExposureModeSupported:AVCaptureExposureModeAutoExpose] ),
                    @"continuous_auto_exposure": @( [device isExposureModeSupported:AVCaptureExposureModeContinuousAutoExposure] ),
                    @"custom": @( [device isExposureModeSupported:AVCaptureExposureModeCustom] ),
                },
                @"current": AVExposureModeName(device.exposureMode),
            },
            @"white_balance": @{
                @"readable": @YES,
                @"writable": @NO,
                @"supported": @{
                    @"locked": @( [device isWhiteBalanceModeSupported:AVCaptureWhiteBalanceModeLocked] ),
                    @"auto_white_balance": @( [device isWhiteBalanceModeSupported:AVCaptureWhiteBalanceModeAutoWhiteBalance] ),
                    @"continuous_auto_white_balance": @( [device isWhiteBalanceModeSupported:AVCaptureWhiteBalanceModeContinuousAutoWhiteBalance] ),
                },
                @"current": AVWhiteBalanceModeName(device.whiteBalanceMode),
            },
        };
        [devices addObject:deviceReport];
    }
    report[@"uvc"] = @(pixyFound);
    report[@"devices"] = devices;
    return report;
}

static NSDictionary *AudioReport(void) {
    NSMutableArray *devices = MutableArray();
    AVCaptureDeviceDiscoverySession *session =
        [AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:@[
            AVCaptureDeviceTypeExternal,
            AVCaptureDeviceTypeMicrophone,
        ] mediaType:AVMediaTypeAudio position:AVCaptureDevicePositionUnspecified];
    for (AVCaptureDevice *device in session.devices) {
        NSString *name = device.localizedName;
        if (name == nil) name = @"";
        if ([name rangeOfString:@"EMEET" options:NSCaseInsensitiveSearch].location == NSNotFound &&
            [name rangeOfString:@"PIXY" options:NSCaseInsensitiveSearch].location == NSNotFound) {
            continue;
        }
        NSMutableArray *formats = MutableArray();
        for (AVCaptureDeviceFormat *format in device.formats) {
            const AudioStreamBasicDescription *description =
                CMAudioFormatDescriptionGetStreamBasicDescription(format.formatDescription);
            if (description == NULL) continue;
            [formats addObject:@{
                @"sample_rate": @(description->mSampleRate),
                @"channels": @(description->mChannelsPerFrame),
                @"format": FourCC(description->mFormatID),
                @"bits_per_channel": @(description->mBitsPerChannel),
            }];
        }
        [devices addObject:@{
            @"name": name,
            @"media_type": @"audio",
            @"formats": formats,
        }];
    }
    return @{
        @"uac": @(devices.count > 0),
        @"devices": devices,
        @"capture": @"not_performed",
    };
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

static NSString *HexBytes(const unsigned char *bytes, size_t length) {
    NSMutableString *result = [NSMutableString string];
    for (size_t i = 0; i < length; i++) {
        [result appendFormat:@"%02X", bytes[i]];
    }
    return result;
}

static NSString *InterfaceClassName(uint8_t classCode) {
    switch (classCode) {
        case 0x01: return @"audio";
        case 0x02: return @"communications";
        case 0x03: return @"hid";
        case 0x0a: return @"cdc_data";
        case 0x0e: return @"video";
        case 0xe0: return @"wireless_controller";
        case 0xef: return @"miscellaneous";
        default: return Hex(classCode, 2);
    }
}

static uint8_t *DescriptorBytes(const struct libusb_interface_descriptor *interface,
                                int *length) {
    *length = interface->extra_length;
    if (interface->extra_length <= 0 || interface->extra == NULL) {
        return NULL;
    }
    return (uint8_t *)interface->extra;
}

static void AddUVCControls(NSMutableDictionary *controls,
                           uint8_t terminalID,
                           uint8_t interfaceNumber,
                           uint32_t bits,
                           uint8_t controlSize,
                           libusb_device_handle *handle) {
    struct ControlDefinition {
        const char *name;
        uint8_t bit;
        uint8_t selector;
        uint8_t length;
        const char *unit;
    } definitions[] = {
        {"scanning_mode", 0, 0x01, 1, "boolean"},
        {"exposure_mode", 1, 0x02, 1, "bitmask"},
        {"exposure_priority", 2, 0x03, 1, "boolean"},
        {"exposure_absolute", 3, 0x04, 4, "100_microseconds"},
        {"focus_absolute", 5, 0x06, 2, "unsigned"},
        {"focus_auto", 16, 0x08, 1, "boolean"},
        {"zoom_absolute", 9, 0x0b, 2, "unsigned"},
        {"pan_tilt_absolute", 11, 0x0d, 8, "arcsecond"},
        {"privacy", 17, 0x11, 1, "boolean"},
    };
    for (size_t i = 0; i < sizeof(definitions) / sizeof(definitions[0]); i++) {
        const struct ControlDefinition definition = definitions[i];
        BOOL supported = definition.bit < 32 && ((bits >> definition.bit) & 1) != 0;
        if (!supported) {
            continue;
        }
        NSMutableDictionary *value = MutableDictionary();
        value[@"supported"] = @YES;
        value[@"unit"] = [NSString stringWithUTF8String:definition.unit];
        value[@"readable"] = [NSNull null];
        value[@"writable"] = [NSNull null];
        value[@"min"] = [NSNull null];
        value[@"max"] = [NSNull null];
        value[@"step"] = [NSNull null];
        value[@"default"] = [NSNull null];
        value[@"current"] = [NSNull null];

        if (handle != NULL) {
            NSMutableDictionary *readback = MutableDictionary();
            uint16_t wIndex = ((uint16_t)terminalID << 8) | interfaceNumber;
            unsigned char info[8] = {0};
            int infoResult = libusb_control_transfer(handle, 0xa1, 0x86,
                                                      (uint16_t)definition.selector << 8,
                                                      wIndex, info, 1, 1000);
            readback[@"get_info_result"] = @(infoResult);
            if (infoResult < 0) {
                readback[@"get_info_error"] = [NSString stringWithUTF8String:libusb_error_name(infoResult)];
            }
            if (infoResult == 1) {
                value[@"readable"] = @((info[0] & 0x01) != 0);
                value[@"writable"] = @((info[0] & 0x02) != 0);
            }
            uint16_t requestedLength = definition.length;
            unsigned char lengthBuffer[2] = {0};
            int lengthResult = libusb_control_transfer(handle, 0xa1, 0x85,
                                                        (uint16_t)definition.selector << 8,
                                                        wIndex, lengthBuffer, sizeof(lengthBuffer), 1000);
            readback[@"get_len_result"] = @(lengthResult);
            if (lengthResult < 0) {
                readback[@"get_len_error"] = [NSString stringWithUTF8String:libusb_error_name(lengthResult)];
            }
            if (lengthResult == 2) {
                uint16_t reportedLength = ReadLE16(lengthBuffer);
                readback[@"get_len_bytes"] = HexBytes(lengthBuffer, sizeof(lengthBuffer));
                // Do not trust GET_LEN for pan/tilt or privacy. The Pixy reports 3 for
                // pan/tilt, which is not even a legal width for an 8-byte control; a
                // 3-byte read then returns truncated bytes that decode to nothing, so
                // min/max/step/default/current all came back null for a camera whose
                // standard 8-byte reads succeed perfectly. That made a working PTZ
                // device look unreadable in the report used to prove support.
                //
                // This mirrors the Worker bridge (camera_uvc.m), which already excludes
                // both controls, and the declared quirk in
                // camera-profiles/emeet-pixy/profile.toml (ignore_get_len, fixed_length).
                BOOL trustGetLen = strcmp(definition.name, "pan_tilt_absolute") != 0 &&
                                   definition.selector != 0x11;
                if (reportedLength >= 1 && reportedLength <= 16 && trustGetLen) {
                    requestedLength = reportedLength;
                } else if (!trustGetLen && reportedLength != definition.length) {
                    readback[@"get_len_ignored"] = @(reportedLength);
                }
            }
            readback[@"length_used"] = @(requestedLength);
            const struct {
                uint8_t request;
                const char *key;
            } requests[] = {
                {0x82, "min"}, {0x83, "max"}, {0x84, "step"},
                {0x87, "default"}, {0x81, "current"},
            };
            if (requestedLength > 0 && requestedLength <= 16) {
                for (size_t requestIndex = 0;
                     requestIndex < sizeof(requests) / sizeof(requests[0]);
                     requestIndex++) {
                    unsigned char data[16] = {0};
                    int result = libusb_control_transfer(handle, 0xa1,
                                                          requests[requestIndex].request,
                                                          (uint16_t)definition.selector << 8,
                                                          wIndex, data, requestedLength, 1000);
                    NSString *requestKey = [NSString stringWithUTF8String:requests[requestIndex].key];
                    readback[[requestKey stringByAppendingString:@"_result"]] = @(result);
                    if (result > 0) {
                        readback[[requestKey stringByAppendingString:@"_bytes"]] = HexBytes(data, (size_t)result);
                    }
                    if (result < 0) {
                        readback[[requestKey stringByAppendingString:@"_error"]] = [NSString stringWithUTF8String:libusb_error_name(result)];
                    }
                    if (result != requestedLength) {
                        continue;
                    }
                    if (requestedLength == 1) {
                        value[requestKey] = @(data[0]);
                    } else if (requestedLength == 2) {
                        value[requestKey] = @(ReadLE16(data));
                    } else if (requestedLength == 4) {
                        value[requestKey] = @(ReadLE32Signed(data));
                    } else if (requestedLength == 8 && strcmp(definition.name, "pan_tilt_absolute") == 0) {
                        value[requestKey] = @[
                            @(ReadLE32Signed(data)), @(ReadLE32Signed(data + 4))
                        ];
                    }
                }
            }
            if (strcmp(definition.name, "pan_tilt_absolute") == 0 ||
                strcmp(definition.name, "privacy") == 0) {
                uint16_t standardLength = strcmp(definition.name, "pan_tilt_absolute") == 0 ? 8 : 1;
                for (size_t requestIndex = 0;
                     requestIndex < sizeof(requests) / sizeof(requests[0]);
                     requestIndex++) {
                    unsigned char standardData[8] = {0};
                    int standardResult = libusb_control_transfer(handle, 0xa1,
                                                                 requests[requestIndex].request,
                                                                 (uint16_t)definition.selector << 8,
                                                                 wIndex, standardData, standardLength, 1000);
                    NSString *requestKey = [NSString stringWithUTF8String:requests[requestIndex].key];
                    NSString *standardKey = [@"standard_get_" stringByAppendingString:requestKey];
                    readback[[standardKey stringByAppendingString:@"_result"]] = @(standardResult);
                    if (standardResult > 0) {
                        readback[[standardKey stringByAppendingString:@"_bytes"]] = HexBytes(standardData, (size_t)standardResult);
                    }
                }
                unsigned char standardData[8] = {0};
                int standardResult = libusb_control_transfer(handle, 0xa1, 0x81,
                                                             (uint16_t)definition.selector << 8,
                                                             wIndex, standardData, standardLength, 1000);
                readback[@"standard_get_current_length"] = @(standardLength);
                readback[@"standard_get_current_result"] = @(standardResult);
                if (standardResult > 0) {
                    readback[@"standard_get_current_bytes"] = HexBytes(standardData, (size_t)standardResult);
                }
            }
            value[@"readback"] = readback;
        }
        controls[[NSString stringWithUTF8String:definition.name]] = value;
    }
    (void)controlSize;
}

static void ParseUVCExtra(const struct libusb_interface_descriptor *interface,
                          NSMutableDictionary *video,
                          libusb_device_handle *handle) {
    int length = 0;
    uint8_t *bytes = DescriptorBytes(interface, &length);
    if (bytes == NULL) {
        return;
    }
    NSMutableArray *descriptors = MutableArray();
    NSMutableDictionary *controls = MutableDictionary();
    for (int offset = 0; offset + 2 <= length;) {
        uint8_t descriptorLength = bytes[offset];
        uint8_t descriptorType = bytes[offset + 1];
        if (descriptorLength < 2 || offset + descriptorLength > length) {
            break;
        }
        if (descriptorType == 0x24 && descriptorLength >= 3) {
            uint8_t subtype = bytes[offset + 2];
            if (subtype == 0x01 && descriptorLength >= 8) {
                video[@"uvc_version"] = Hex(ReadLE16(bytes + offset + 3), 4);
                video[@"control_interface_total_length"] = @(ReadLE16(bytes + offset + 5));
            } else if (subtype == 0x02 && descriptorLength >= 15) {
                uint16_t terminalType = ReadLE16(bytes + offset + 4);
                uint8_t controlSize = bytes[offset + 14];
                if (terminalType == 0x0201 && offset + 15 + controlSize <= length) {
                    uint32_t bits = 0;
                    for (uint8_t index = 0; index < controlSize && index < 4; index++) {
                        bits |= ((uint32_t)bytes[offset + 15 + index]) << (index * 8);
                    }
                    AddUVCControls(controls, bytes[offset + 3], interface->bInterfaceNumber,
                                   bits, controlSize, handle);
                }
            }
            [descriptors addObject:@{
                @"type": @"class_specific_video_control",
                @"subtype": @(subtype),
                @"length": @(descriptorLength),
            }];
        }
        offset += descriptorLength;
    }
    if (controls.count > 0) {
        video[@"controls"] = controls;
    }
    video[@"class_specific_descriptors"] = descriptors;
}

static void ParseHIDReportDescriptor(const unsigned char *report,
                                     int reportLength,
                                     NSMutableDictionary *hid) {
    NSMutableArray *collections = MutableArray();
    NSMutableArray *reports = MutableArray();
    uint32_t usagePage = 0;
    uint32_t usage = 0;
    uint32_t reportSize = 0;
    uint32_t reportCount = 0;
    uint32_t reportID = 0;
    for (int offset = 0; offset < reportLength;) {
        uint8_t prefix = report[offset++];
        if (prefix == 0xfe) {
            if (offset + 2 > reportLength) break;
            uint8_t dataLength = report[offset++];
            offset++;
            offset += dataLength;
            continue;
        }
        uint8_t sizeCode = prefix & 0x03;
        uint8_t size = sizeCode == 3 ? 4 : sizeCode;
        uint8_t type = (prefix >> 2) & 0x03;
        uint8_t tag = (prefix >> 4) & 0x0f;
        if (offset + size > reportLength) break;
        uint32_t value = 0;
        for (uint8_t index = 0; index < size; index++) {
            value |= ((uint32_t)report[offset + index]) << (index * 8);
        }
        offset += size;
        if (type == 1) {
            if (tag == 0x0) usagePage = value;
            else if (tag == 0x7) reportSize = value;
            else if (tag == 0x8) reportID = value;
            else if (tag == 0x9) reportCount = value;
        } else if (type == 2) {
            if (tag == 0x0) usage = value;
        } else if (type == 0) {
            if (tag == 0xa) {
                [collections addObject:@{
                    @"usage_page": Hex(usagePage, 4),
                    @"usage": Hex(usage, 4),
                }];
            } else if (tag == 0x8 || tag == 0x9 || tag == 0xb) {
                NSString *kind = tag == 0x8 ? @"input" : (tag == 0x9 ? @"output" : @"feature");
                [reports addObject:@{
                    @"kind": kind,
                    @"report_id": @(reportID),
                    @"report_size_bits": @(reportSize),
                    @"report_count": @(reportCount),
                    @"bytes": @((reportSize * reportCount + 7) / 8 + (reportID > 0 ? 1 : 0)),
                }];
            }
        }
    }
    hid[@"collections"] = collections;
    hid[@"reports"] = reports;
}

static NSDictionary *USBReport(void) {
    NSMutableDictionary *report = MutableDictionary();
    report[@"present"] = @NO;
    report[@"vendor_id"] = Hex(kPixyVendorID, 4);
    report[@"product_id"] = Hex(kPixyProductID, 4);
    report[@"manufacturer"] = [NSNull null];
    report[@"product_name"] = [NSNull null];
    report[@"interfaces"] = MutableArray();
    report[@"hid"] = @{
        @"present": @NO,
        @"collections": @[],
        @"reports": @[],
    };
    report[@"network_interface"] = @NO;
    report[@"video"] = @{
        @"uvc": @NO,
        @"controls": @{},
    };

    libusb_context *context = NULL;
    if (libusb_init(&context) != 0) {
        report[@"error"] = @"libusb_init_failed";
        return report;
    }
    libusb_device **list = NULL;
    ssize_t count = libusb_get_device_list(context, &list);
    libusb_device *pixy = NULL;
    struct libusb_device_descriptor deviceDescriptor;
    memset(&deviceDescriptor, 0, sizeof(deviceDescriptor));
    for (ssize_t index = 0; index < count; index++) {
        struct libusb_device_descriptor descriptor;
        if (libusb_get_device_descriptor(list[index], &descriptor) != 0) continue;
        if (descriptor.idVendor == kPixyVendorID && descriptor.idProduct == kPixyProductID) {
            pixy = list[index];
            deviceDescriptor = descriptor;
            break;
        }
    }
    if (pixy == NULL) {
        if (list != NULL) libusb_free_device_list(list, 1);
        libusb_exit(context);
        return report;
    }
    report[@"present"] = @YES;
    report[@"bcd_usb"] = Hex(deviceDescriptor.bcdUSB, 4);
    report[@"device_class"] = @(deviceDescriptor.bDeviceClass);
    report[@"device_subclass"] = @(deviceDescriptor.bDeviceSubClass);
    report[@"device_protocol"] = @(deviceDescriptor.bDeviceProtocol);
    report[@"max_packet_size"] = @(deviceDescriptor.bMaxPacketSize0);

    libusb_device_handle *handle = NULL;
    if (libusb_open(pixy, &handle) == 0) {
        unsigned char buffer[256] = {0};
        int length = libusb_get_string_descriptor_ascii(handle, deviceDescriptor.iManufacturer,
                                                        buffer, sizeof(buffer));
        if (length > 0) report[@"manufacturer"] = [[NSString alloc] initWithBytes:buffer length:length encoding:NSUTF8StringEncoding];
        memset(buffer, 0, sizeof(buffer));
        length = libusb_get_string_descriptor_ascii(handle, deviceDescriptor.iProduct,
                                                    buffer, sizeof(buffer));
        if (length > 0) report[@"product_name"] = [[NSString alloc] initWithBytes:buffer length:length encoding:NSUTF8StringEncoding];
    }

    struct libusb_config_descriptor *config = NULL;
    if (libusb_get_active_config_descriptor(pixy, &config) == 0 && config != NULL) {
        NSMutableDictionary *video = [report[@"video"] mutableCopy];
        NSMutableDictionary *hid = [report[@"hid"] mutableCopy];
        NSMutableArray *interfaces = report[@"interfaces"];
        BOOL network = NO;
        for (int interfaceIndex = 0; interfaceIndex < config->bNumInterfaces; interfaceIndex++) {
            const struct libusb_interface *interface = &config->interface[interfaceIndex];
            for (int alternateIndex = 0; alternateIndex < interface->num_altsetting; alternateIndex++) {
                const struct libusb_interface_descriptor *alternate = &interface->altsetting[alternateIndex];
                NSString *className = InterfaceClassName(alternate->bInterfaceClass);
                [interfaces addObject:@{
                    @"number": @(alternate->bInterfaceNumber),
                    @"alternate_setting": @(alternate->bAlternateSetting),
                    @"class": className,
                    @"class_code": Hex(alternate->bInterfaceClass, 2),
                    @"subclass": @(alternate->bInterfaceSubClass),
                    @"protocol": @(alternate->bInterfaceProtocol),
                    @"endpoints": @(alternate->bNumEndpoints),
                }];
                if (alternate->bInterfaceClass == 0x02 || alternate->bInterfaceClass == 0x0a ||
                    alternate->bInterfaceClass == 0xe0) {
                    network = YES;
                }
                if (alternate->bInterfaceClass == 0x0e) {
                    video[@"uvc"] = @YES;
                    if (alternate->bInterfaceSubClass == 0x01 && alternate->bAlternateSetting == 0) {
                        ParseUVCExtra(alternate, video, handle);
                    }
                }
                if (alternate->bInterfaceClass == 0x01) {
                    video[@"audio_interface_present"] = @YES;
                }
                if (alternate->bInterfaceClass == 0x03) {
                    hid[@"present"] = @YES;
                    int extraLength = 0;
                    uint8_t *extra = DescriptorBytes(alternate, &extraLength);
                    for (int offset = 0; extra != NULL && offset + 2 <= extraLength;) {
                        uint8_t descriptorLength = extra[offset];
                        if (descriptorLength < 2 || offset + descriptorLength > extraLength) break;
                        if (extra[offset + 1] == 0x21 && descriptorLength >= 6) {
                            hid[@"report_descriptor_bytes"] = @(ReadLE16(extra + offset + 7));
                            unsigned char reportDescriptor[4096] = {0};
                            int reportLength = -1;
                            if (handle != NULL) {
                                reportLength = libusb_control_transfer(
                                    handle, 0x81, 0x06, (uint16_t)(0x22 << 8),
                                    alternate->bInterfaceNumber, reportDescriptor,
                                    sizeof(reportDescriptor), 1000);
                            }
                            if (reportLength > 0) {
                                ParseHIDReportDescriptor(reportDescriptor, reportLength, hid);
                            }
                        }
                        offset += descriptorLength;
                    }
                }
            }
        }
        report[@"video"] = video;
        report[@"hid"] = hid;
        report[@"network_interface"] = @(network);
        libusb_free_config_descriptor(config);
    }
    if (handle != NULL) libusb_close(handle);
    libusb_free_device_list(list, 1);
    libusb_exit(context);
    return report;
}

static BOOL HasPixyNamedNetworkInterface(void) {
    struct ifaddrs *interfaces = NULL;
    BOOL found = NO;
    if (getifaddrs(&interfaces) != 0) return NO;
    for (struct ifaddrs *item = interfaces; item != NULL; item = item->ifa_next) {
        if (item->ifa_name == NULL) continue;
        NSString *name = [NSString stringWithUTF8String:item->ifa_name];
        if ([name rangeOfString:@"emeet" options:NSCaseInsensitiveSearch].location != NSNotFound ||
            [name rangeOfString:@"pixy" options:NSCaseInsensitiveSearch].location != NSNotFound) {
            found = YES;
            break;
        }
    }
    freeifaddrs(interfaces);
    return found;
}

int main(void) {
    @autoreleasepool {
        NSDictionary *usb = USBReport();
        NSMutableDictionary *root = MutableDictionary();
        root[@"schema_version"] = @1;
        root[@"device"] = @{
            @"vendor_id": usb[@"vendor_id"],
            @"product_id": usb[@"product_id"],
            @"manufacturer": usb[@"manufacturer"],
            @"product_name": usb[@"product_name"],
            @"present": usb[@"present"],
        };
        root[@"usb"] = usb;
        root[@"video"] = VideoReport();
        root[@"audio"] = AudioReport();
        root[@"network_interface"] = @([usb[@"network_interface"] boolValue] || HasPixyNamedNetworkInterface());
        root[@"writes_performed"] = @NO;
        root[@"audio_capture_performed"] = @NO;
        root[@"software"] = @{
            @"emeet_studio_used": @NO,
            @"firmware_updated": @NO,
        };

        NSError *error = nil;
        NSData *json = [NSJSONSerialization dataWithJSONObject:root options:NSJSONWritingPrettyPrinted error:&error];
        if (json == nil) {
            fprintf(stderr, "pixy-probe: failed to encode report: %s\n", error.localizedDescription.UTF8String);
            return 1;
        }
        fwrite(json.bytes, 1, json.length, stdout);
        fputc('\n', stdout);
    }
    return 0;
}
