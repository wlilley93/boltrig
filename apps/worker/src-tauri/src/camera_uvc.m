#import <AVFoundation/AVFoundation.h>
#import <CommonCrypto/CommonDigest.h>
#import <Foundation/Foundation.h>

#include <CoreMedia/CoreMedia.h>
#include <CoreVideo/CoreVideo.h>
#include <dispatch/dispatch.h>

#include <libusb.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    kGetCurrent = 0x81,
    kGetMinimum = 0x82,
    kGetMaximum = 0x83,
    kGetResolution = 0x84,
    kGetLength = 0x85,
    kGetInfo = 0x86,
    kGetDefault = 0x87,
    kSetCurrent = 0x01,
};

typedef struct {
    libusb_context *context;
    libusb_device **list;
    ssize_t list_count;
    libusb_device *device;
    libusb_device_handle *handle;
    uint8_t interface_number;
    uint8_t terminal_id;
    uint16_t uvc_version;
    uint32_t control_bits;
    uint8_t control_size;
    char native_key[256];
    char descriptor_fingerprint[65];
    char manufacturer[256];
    char product[256];
} UVCConnection;

static NSMutableDictionary *Dict(void) {
    return [NSMutableDictionary dictionary];
}

static NSMutableArray *Array(void) {
    return [NSMutableArray array];
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
    uint32_t unsigned_value = (uint32_t)value;
    bytes[0] = (unsigned char)(unsigned_value & 0xff);
    bytes[1] = (unsigned char)((unsigned_value >> 8) & 0xff);
    bytes[2] = (unsigned char)((unsigned_value >> 16) & 0xff);
    bytes[3] = (unsigned char)((unsigned_value >> 24) & 0xff);
}

static NSString *HexBytes(const unsigned char *bytes, size_t length) {
    NSMutableString *result = [NSMutableString string];
    for (size_t index = 0; index < length; index++) {
        [result appendFormat:@"%02x", bytes[index]];
    }
    return result;
}

static NSString *HexDigest(const unsigned char digest[CC_SHA256_DIGEST_LENGTH]) {
    return HexBytes(digest, CC_SHA256_DIGEST_LENGTH);
}

static const char *USBError(int result) {
    const char *name = libusb_error_name(result);
    return name == NULL ? "usb_error" : name;
}

static NSDictionary *ErrorResult(int result) {
    if (result >= 0) {
        return @{ @"result": @(result), @"ok": @YES };
    }
    return @{
        @"result": @(result),
        @"ok": @NO,
        @"error": [NSString stringWithUTF8String:USBError(result)],
    };
}

static char *JSONBuffer(id object) {
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:object options:0 error:&error];
    if (data == nil || data.length == 0) return NULL;
    char *output = (char *)malloc(data.length + 1);
    if (output == NULL) return NULL;
    memcpy(output, data.bytes, data.length);
    output[data.length] = '\0';
    return output;
}

static BOOL DescriptorIsCameraTerminal(const unsigned char *bytes, int length) {
    return length >= 15 && bytes[1] == 0x24 && bytes[2] == 0x02 &&
           ReadLE16(bytes + 4) == 0x0201;
}

static BOOL FindCameraTerminal(UVCConnection *connection,
                               const struct libusb_config_descriptor *config) {
    for (uint8_t interface_index = 0;
         interface_index < config->bNumInterfaces;
         interface_index++) {
        const struct libusb_interface *interface = &config->interface[interface_index];
        for (int alternate_index = 0;
             alternate_index < interface->num_altsetting;
             alternate_index++) {
            const struct libusb_interface_descriptor *alternate =
                &interface->altsetting[alternate_index];
            if (alternate->bInterfaceClass != 0x0e ||
                alternate->bInterfaceSubClass != 0x01 ||
                alternate->bAlternateSetting != 0 || alternate->extra == NULL) {
                continue;
            }
            for (int offset = 0; offset + 2 <= alternate->extra_length;) {
                uint8_t descriptor_length = alternate->extra[offset];
                if (descriptor_length < 2 ||
                    offset + descriptor_length > alternate->extra_length) {
                    break;
                }
                const unsigned char *bytes =
                    (const unsigned char *)alternate->extra + offset;
                if (DescriptorIsCameraTerminal(bytes, descriptor_length)) {
                    uint8_t size = bytes[14];
                    if (size == 0 || size > 4 || 15 + size > descriptor_length) {
                        offset += descriptor_length;
                        continue;
                    }
                    connection->interface_number = alternate->bInterfaceNumber;
                    connection->terminal_id = bytes[3];
                    connection->control_size = size;
                    connection->control_bits = 0;
                    for (uint8_t index = 0; index < size; index++) {
                        connection->control_bits |=
                            ((uint32_t)bytes[15 + index]) << (index * 8);
                    }
                    return YES;
                }
                offset += descriptor_length;
            }
        }
    }
    return NO;
}

static uint16_t FindUVCVersion(const struct libusb_config_descriptor *config) {
    for (uint8_t interface_index = 0;
         interface_index < config->bNumInterfaces;
         interface_index++) {
        const struct libusb_interface *interface = &config->interface[interface_index];
        for (int alternate_index = 0;
             alternate_index < interface->num_altsetting;
             alternate_index++) {
            const struct libusb_interface_descriptor *alternate =
                &interface->altsetting[alternate_index];
            if (alternate->bInterfaceClass != 0x0e ||
                alternate->bInterfaceSubClass != 0x01 || alternate->extra == NULL) {
                continue;
            }
            for (int offset = 0; offset + 3 <= alternate->extra_length;) {
                uint8_t descriptor_length = alternate->extra[offset];
                if (descriptor_length < 3 ||
                    offset + descriptor_length > alternate->extra_length) {
                    break;
                }
                const unsigned char *bytes =
                    (const unsigned char *)alternate->extra + offset;
                if (bytes[1] == 0x24 && bytes[2] == 0x01 && descriptor_length >= 5) {
                    return ReadLE16(bytes + 3);
                }
                offset += descriptor_length;
            }
        }
    }
    return 0;
}

static void BuildNativeKey(UVCConnection *connection,
                           uint16_t vendor,
                           uint16_t product) {
    uint8_t ports[8] = {0};
    int port_count = libusb_get_port_numbers(
        connection->device, ports, (int)sizeof(ports));
    int offset = snprintf(connection->native_key, sizeof(connection->native_key),
                          "%04x:%04x:%u:", vendor, product,
                          (unsigned int)libusb_get_bus_number(connection->device));
    if (offset < 0) offset = 0;
    if (port_count > 0) {
        for (int index = 0; index < port_count && offset < (int)sizeof(connection->native_key); index++) {
            offset += snprintf(connection->native_key + offset,
                               sizeof(connection->native_key) - (size_t)offset,
                               "%s%u", index == 0 ? "" : ".", ports[index]);
        }
    } else {
        snprintf(connection->native_key + offset,
                 sizeof(connection->native_key) - (size_t)offset,
                 "address-%u", (unsigned int)libusb_get_device_address(connection->device));
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH] = {0};
    CC_SHA256(connection->native_key, (CC_LONG)strlen(connection->native_key), digest);
    strncpy(connection->descriptor_fingerprint, HexDigest(digest).UTF8String,
            sizeof(connection->descriptor_fingerprint) - 1);
    connection->descriptor_fingerprint[sizeof(connection->descriptor_fingerprint) - 1] = '\0';
}

static void ReadUSBStrings(UVCConnection *connection,
                           const struct libusb_device_descriptor *descriptor) {
    if (connection->handle == NULL) return;
    unsigned char buffer[256] = {0};
    int length = libusb_get_string_descriptor_ascii(
        connection->handle, descriptor->iManufacturer, buffer, sizeof(buffer));
    if (length > 0) {
        memcpy(connection->manufacturer, buffer, (size_t)length);
        connection->manufacturer[length] = '\0';
    }
    memset(buffer, 0, sizeof(buffer));
    length = libusb_get_string_descriptor_ascii(
        connection->handle, descriptor->iProduct, buffer, sizeof(buffer));
    if (length > 0) {
        memcpy(connection->product, buffer, (size_t)length);
        connection->product[length] = '\0';
    }
}

static void CloseConnection(UVCConnection *connection) {
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

static BOOL OpenMatching(UVCConnection *connection,
                         const char *fingerprint,
                         NSMutableArray *errors) {
    memset(connection, 0, sizeof(*connection));
    int result = libusb_init(&connection->context);
    if (result != 0) {
        [errors addObject:@{ @"stage": @"libusb_init", @"error": [NSString stringWithUTF8String:USBError(result)] }];
        return NO;
    }
    connection->list_count = libusb_get_device_list(connection->context, &connection->list);
    if (connection->list_count < 0) {
        [errors addObject:@{ @"stage": @"device_list", @"error": [NSString stringWithUTF8String:USBError((int)connection->list_count)] }];
        return NO;
    }
    for (ssize_t index = 0; index < connection->list_count; index++) {
        struct libusb_device_descriptor descriptor;
        if (libusb_get_device_descriptor(connection->list[index], &descriptor) != 0) continue;
        UVCConnection candidate = {0};
        candidate.device = connection->list[index];
        BuildNativeKey(&candidate, descriptor.idVendor, descriptor.idProduct);
        if (fingerprint == NULL || strcmp(candidate.descriptor_fingerprint, fingerprint) != 0) continue;
        candidate.context = connection->context;
        candidate.list = connection->list;
        candidate.list_count = connection->list_count;
        candidate.uvc_version = 0;
        int open_result = libusb_open(candidate.device, &candidate.handle);
        if (open_result != 0) {
            [errors addObject:@{ @"stage": @"open", @"error": [NSString stringWithUTF8String:USBError(open_result)] }];
            *connection = candidate;
            return NO;
        }
        ReadUSBStrings(&candidate, &descriptor);
        struct libusb_config_descriptor *config = NULL;
        int config_result = libusb_get_active_config_descriptor(candidate.device, &config);
        if (config_result != 0 || config == NULL || !FindCameraTerminal(&candidate, config)) {
            if (config != NULL) libusb_free_config_descriptor(config);
            [errors addObject:@{ @"stage": @"camera_terminal", @"error": @"uvc_camera_terminal_not_found" }];
            *connection = candidate;
            return NO;
        }
        candidate.uvc_version = FindUVCVersion(config);
        libusb_free_config_descriptor(config);
        *connection = candidate;
        return YES;
    }
    [errors addObject:@{ @"stage": @"identify", @"error": @"camera_not_found" }];
    return NO;
}

typedef struct {
    const char *name;
    uint8_t bit;
    uint8_t selector;
    uint8_t fixed_length;
    BOOL signed_value;
    BOOL pan_tilt;
    const char *unit;
} ControlDefinition;

static const ControlDefinition kControls[] = {
    { "scanning_mode", 0, 0x01, 1, NO, NO, "boolean" },
    { "exposure_mode", 1, 0x02, 1, NO, NO, "bitmask" },
    { "exposure_priority", 2, 0x03, 1, NO, NO, "boolean" },
    { "exposure_absolute", 3, 0x04, 4, YES, NO, "100_microseconds" },
    { "focus_absolute", 5, 0x06, 2, NO, NO, "unsigned" },
    { "focus_auto", 16, 0x08, 1, NO, NO, "boolean" },
    { "zoom_absolute", 9, 0x0b, 2, NO, NO, "unsigned" },
    { "pan_tilt_absolute", 11, 0x0d, 8, YES, YES, "0.01_degree" },
    { "privacy", 17, 0x11, 1, NO, NO, "boolean" },
};

static const ControlDefinition *ControlForName(const char *name) {
    for (size_t index = 0; index < sizeof(kControls) / sizeof(kControls[0]); index++) {
        if (strcmp(kControls[index].name, name) == 0) return &kControls[index];
    }
    return NULL;
}

static int UVCTransfer(UVCConnection *connection,
                       uint8_t direction,
                       uint8_t request,
                       uint8_t selector,
                       unsigned char *data,
                       uint16_t length) {
    uint16_t w_index = ((uint16_t)connection->terminal_id << 8) |
                       connection->interface_number;
    return libusb_control_transfer(connection->handle, direction, request,
                                   (uint16_t)selector << 8, w_index, data, length, 1000);
}

static id DecodeValue(const unsigned char *data,
                      uint16_t length,
                      const ControlDefinition *definition) {
    if (definition->pan_tilt && length == 8) {
        return @[ @(ReadLE32Signed(data)), @(ReadLE32Signed(data + 4)) ];
    }
    if (length == 1) return @(data[0]);
    if (length == 2) return @(ReadLE16(data));
    if (length == 4) {
        return definition->signed_value ? @(ReadLE32Signed(data)) : @((uint32_t)ReadLE32Signed(data));
    }
    return [NSNull null];
}

static NSDictionary *ReadControl(UVCConnection *connection,
                                 const ControlDefinition *definition) {
    NSMutableDictionary *value = Dict();
    value[@"supported"] = @YES;
    value[@"selector"] = @(definition->selector);
    value[@"unit"] = [NSString stringWithUTF8String:definition->unit];
    value[@"readable"] = [NSNull null];
    value[@"writable"] = [NSNull null];
    value[@"min"] = [NSNull null];
    value[@"max"] = [NSNull null];
    value[@"step"] = [NSNull null];
    value[@"default"] = [NSNull null];
    value[@"current"] = [NSNull null];
    NSMutableDictionary *readback = Dict();
    if (connection->handle == NULL) {
        value[@"readback"] = readback;
        return value;
    }
    unsigned char info[1] = {0};
    int info_result = UVCTransfer(connection, 0xa1, kGetInfo,
                                  definition->selector, info, sizeof(info));
    readback[@"get_info_result"] = @(info_result);
    if (info_result < 0) readback[@"get_info_error"] = [NSString stringWithUTF8String:USBError(info_result)];
    if (info_result == 1) {
        value[@"readable"] = @((info[0] & 0x01) != 0);
        value[@"writable"] = @((info[0] & 0x02) != 0);
    }
    uint16_t length = definition->fixed_length;
    unsigned char length_data[2] = {0};
    int length_result = UVCTransfer(connection, 0xa1, kGetLength,
                                    definition->selector, length_data, sizeof(length_data));
    readback[@"get_len_result"] = @(length_result);
    if (length_result == 2) {
        uint16_t reported = ReadLE16(length_data);
        readback[@"get_len_bytes"] = HexBytes(length_data, sizeof(length_data));
        if (reported >= 1 && reported <= 16 && !definition->pan_tilt && definition->selector != 0x11) {
            length = reported;
        }
    } else if (length_result < 0) {
        readback[@"get_len_error"] = [NSString stringWithUTF8String:USBError(length_result)];
    }
    readback[@"length_used"] = @(length);
    const struct { uint8_t request; const char *key; } requests[] = {
        { kGetMinimum, "min" }, { kGetMaximum, "max" },
        { kGetResolution, "step" }, { kGetDefault, "default" },
        { kGetCurrent, "current" },
    };
    for (size_t index = 0; index < sizeof(requests) / sizeof(requests[0]); index++) {
        unsigned char data[16] = {0};
        int result = UVCTransfer(connection, 0xa1, requests[index].request,
                                 definition->selector, data, length);
        NSString *key = [NSString stringWithUTF8String:requests[index].key];
        readback[[key stringByAppendingString:@"_result"]] = @(result);
        if (result > 0) readback[[key stringByAppendingString:@"_bytes"]] = HexBytes(data, (size_t)result);
        if (result < 0) readback[[key stringByAppendingString:@"_error"]] = [NSString stringWithUTF8String:USBError(result)];
        if (result == length) value[key] = DecodeValue(data, length, definition);
    }
    value[@"readback"] = readback;
    return value;
}

static NSDictionary *AVInfoForProduct(const char *product) {
    AVCaptureDeviceDiscoverySession *session =
        [AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:@[ AVCaptureDeviceTypeExternal ]
                                                                mediaType:AVMediaTypeVideo
                                                                 position:AVCaptureDevicePositionUnspecified];
    AVAuthorizationStatus permission =
        [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
    for (AVCaptureDevice *device in session.devices) {
        NSString *name = device.localizedName ?: @"";
        NSString *needle = product == NULL ? @"" : [NSString stringWithUTF8String:product];
        if (needle.length == 0 || [name localizedCaseInsensitiveCompare:needle] == NSOrderedSame ||
            [name rangeOfString:needle options:NSCaseInsensitiveSearch].location != NSNotFound) {
            NSString *permission_name = @"unknown";
            switch (permission) {
                case AVAuthorizationStatusAuthorized: permission_name = @"authorized"; break;
                case AVAuthorizationStatusDenied: permission_name = @"denied"; break;
                case AVAuthorizationStatusRestricted: permission_name = @"restricted"; break;
                case AVAuthorizationStatusNotDetermined: permission_name = @"not_determined"; break;
            }
            return @{
                @"label": name,
                @"model": device.modelID ?: @"unknown",
                @"permission": permission_name,
                @"format_count": @(device.formats.count),
            };
        }
    }
    return @{
        @"label": product == NULL ? @"UVC camera" : [NSString stringWithUTF8String:product],
        @"model": @"unknown",
        @"permission": @"not_enumerated",
        @"format_count": @0,
    };
}

@interface BoltrigFrameSink : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
@property(nonatomic) dispatch_semaphore_t semaphore;
@property(nonatomic) NSString *digest;
@property(nonatomic) size_t sampled_bytes;
@property(nonatomic) size_t width;
@property(nonatomic) size_t height;
@property(nonatomic) OSType pixel_format;
@property(nonatomic) BOOL received;
@end

@implementation BoltrigFrameSink

- (instancetype)init {
    self = [super init];
    if (self != nil) {
        _semaphore = dispatch_semaphore_create(0);
    }
    return self;
}

- (void)captureOutput:(AVCaptureOutput *)output
    didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
           fromConnection:(AVCaptureConnection *)connection {
    (void)output;
    (void)connection;
    if (self.received) return;
    CVImageBufferRef image = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (image == NULL || CVPixelBufferLockBaseAddress(image, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) {
        dispatch_semaphore_signal(self.semaphore);
        return;
    }
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    size_t bytes = 0;
    size_t plane_count = CVPixelBufferGetPlaneCount(image);
    if (plane_count == 0) {
        void *base = CVPixelBufferGetBaseAddress(image);
        size_t length = CVPixelBufferGetDataSize(image);
        if (base != NULL && length > 0) {
            CC_SHA256_Update(&context, base, (CC_LONG)length);
            bytes = length;
        }
    } else {
        for (size_t plane = 0; plane < plane_count; plane++) {
            void *base = CVPixelBufferGetBaseAddressOfPlane(image, plane);
            size_t length = CVPixelBufferGetBytesPerRowOfPlane(image, plane) *
                            CVPixelBufferGetHeightOfPlane(image, plane);
            if (base != NULL && length > 0) {
                CC_SHA256_Update(&context, base, (CC_LONG)length);
                bytes += length;
            }
        }
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH] = {0};
    CC_SHA256_Final(digest, &context);
    self.digest = HexDigest(digest);
    self.sampled_bytes = bytes;
    self.width = CVPixelBufferGetWidth(image);
    self.height = CVPixelBufferGetHeight(image);
    self.pixel_format = CVPixelBufferGetPixelFormatType(image);
    self.received = bytes > 0;
    CVPixelBufferUnlockBaseAddress(image, kCVPixelBufferLock_ReadOnly);
    dispatch_semaphore_signal(self.semaphore);
}

@end

static AVCaptureDevice *FindAVDevice(const char *product) {
    AVCaptureDeviceDiscoverySession *session =
        [AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:@[
            AVCaptureDeviceTypeExternal,
            AVCaptureDeviceTypeBuiltInWideAngleCamera,
            AVCaptureDeviceTypeContinuityCamera,
        ]
                                                                mediaType:AVMediaTypeVideo
                                                                 position:AVCaptureDevicePositionUnspecified];
    NSString *needle = product == NULL ? @"" : [NSString stringWithUTF8String:product];
    for (AVCaptureDevice *device in session.devices) {
        NSString *name = device.localizedName ?: @"";
        if (needle.length == 0 || [name localizedCaseInsensitiveCompare:needle] == NSOrderedSame ||
            [name rangeOfString:needle options:NSCaseInsensitiveSearch].location != NSNotFound) {
            return device;
        }
    }
    return nil;
}

static NSDictionary *CaptureOneFrame(const char *product, NSMutableArray *errors) {
    AVAuthorizationStatus permission =
        [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
    if (permission != AVAuthorizationStatusAuthorized) {
        [errors addObject:@{ @"stage": @"permission", @"error": @"camera_permission_not_authorized" }];
        return @{ @"ok": @NO, @"capture_attempted": @NO };
    }
    AVCaptureDevice *device = FindAVDevice(product);
    if (device == nil) {
        [errors addObject:@{ @"stage": @"device", @"error": @"avfoundation_camera_not_found" }];
        return @{ @"ok": @NO, @"capture_attempted": @NO };
    }
    NSError *input_error = nil;
    AVCaptureDeviceInput *input = [AVCaptureDeviceInput deviceInputWithDevice:device error:&input_error];
    if (input == nil) {
        [errors addObject:@{ @"stage": @"input", @"error": input_error.localizedDescription ?: @"capture_input_failed" }];
        return @{ @"ok": @NO, @"capture_attempted": @NO };
    }
    AVCaptureVideoDataOutput *output = [[AVCaptureVideoDataOutput alloc] init];
    output.alwaysDiscardsLateVideoFrames = YES;
    AVCaptureSession *session = [[AVCaptureSession alloc] init];
    if ([session canSetSessionPreset:AVCaptureSessionPreset640x480]) {
        session.sessionPreset = AVCaptureSessionPreset640x480;
    }
    if (![session canAddInput:input] || ![session canAddOutput:output]) {
        [errors addObject:@{ @"stage": @"session", @"error": @"capture_session_configuration_failed" }];
        return @{ @"ok": @NO, @"capture_attempted": @NO };
    }
    [session addInput:input];
    [session addOutput:output];
    BoltrigFrameSink *sink = [[BoltrigFrameSink alloc] init];
    dispatch_queue_t queue = dispatch_queue_create("io.boltrig.camera.frame", DISPATCH_QUEUE_SERIAL);
    [output setSampleBufferDelegate:sink queue:queue];
    [session startRunning];
    BOOL received = dispatch_semaphore_wait(sink.semaphore, dispatch_time(DISPATCH_TIME_NOW, 3 * NSEC_PER_SEC)) == 0 && sink.received;
    [session stopRunning];
    [output setSampleBufferDelegate:nil queue:NULL];
    if (!received) {
        [errors addObject:@{ @"stage": @"frame", @"error": @"bounded_one_frame_timeout" }];
        return @{ @"ok": @NO, @"capture_attempted": @YES };
    }
    return @{
        @"ok": @YES,
        @"capture_attempted": @YES,
        @"frame_digest": sink.digest ?: @"",
        @"sampled_bytes": @(sink.sampled_bytes),
        @"width": @(sink.width),
        @"height": @(sink.height),
        @"pixel_format": [NSString stringWithFormat:@"0x%08X", (unsigned int)sink.pixel_format],
    };
}

static NSDictionary *CameraRecord(UVCConnection *connection,
                                  uint16_t vendor,
                                  uint16_t product) {
    NSMutableDictionary *record = Dict();
    NSDictionary *av = AVInfoForProduct(connection->product);
    record[@"native_key"] = [NSString stringWithUTF8String:connection->native_key];
    record[@"descriptor_fingerprint"] = [NSString stringWithUTF8String:connection->descriptor_fingerprint];
    record[@"label"] = av[@"label"];
    record[@"model"] = av[@"model"];
    record[@"manufacturer"] = [NSString stringWithUTF8String:connection->manufacturer];
    record[@"permission"] = connection->handle == NULL ? @"permission_required" : av[@"permission"];
    record[@"format_count"] = av[@"format_count"];
    record[@"vid"] = @(vendor);
    record[@"pid"] = @(product);
    record[@"uvc_interface"] = @(connection->interface_number);
    record[@"terminal_id"] = @(connection->terminal_id);
    record[@"uvc_version"] = [NSString stringWithFormat:@"0x%04X", connection->uvc_version];
    NSMutableDictionary *controls = Dict();
    for (size_t index = 0; index < sizeof(kControls) / sizeof(kControls[0]); index++) {
        const ControlDefinition *definition = &kControls[index];
        if (definition->bit >= 32 || ((connection->control_bits >> definition->bit) & 1u) == 0) continue;
        controls[[NSString stringWithUTF8String:definition->name]] = ReadControl(connection, definition);
    }
    record[@"controls"] = controls;
    record[@"transport"] = @"uvc_libusb";
    return record;
}

static NSDictionary *Inventory(void) {
    NSMutableDictionary *report = Dict();
    report[@"schema_version"] = @1;
    report[@"runtime"] = @"libusb_uvc";
    report[@"state"] = @"available";
    report[@"reason"] = [NSNull null];
    NSMutableArray *cameras = Array();
    libusb_context *context = NULL;
    int init_result = libusb_init(&context);
    if (init_result != 0) {
        report[@"state"] = @"unavailable";
        report[@"reason"] = [NSString stringWithUTF8String:USBError(init_result)];
        report[@"cameras"] = cameras;
        return report;
    }
    libusb_device **list = NULL;
    ssize_t count = libusb_get_device_list(context, &list);
    if (count < 0) {
        report[@"state"] = @"unavailable";
        report[@"reason"] = [NSString stringWithUTF8String:USBError((int)count)];
        report[@"cameras"] = cameras;
        libusb_exit(context);
        return report;
    }
    for (ssize_t index = 0; index < count; index++) {
        struct libusb_device_descriptor descriptor;
        if (libusb_get_device_descriptor(list[index], &descriptor) != 0) continue;
        UVCConnection connection = {0};
        connection.context = context;
        connection.list = list;
        connection.list_count = count;
        connection.device = list[index];
        BuildNativeKey(&connection, descriptor.idVendor, descriptor.idProduct);
        struct libusb_config_descriptor *config = NULL;
        if (libusb_get_active_config_descriptor(connection.device, &config) != 0 || config == NULL || !FindCameraTerminal(&connection, config)) {
            if (config != NULL) libusb_free_config_descriptor(config);
            continue;
        }
        connection.uvc_version = FindUVCVersion(config);
        libusb_free_config_descriptor(config);
        int open_result = libusb_open(connection.device, &connection.handle);
        if (open_result == 0 && connection.handle != NULL) ReadUSBStrings(&connection, &descriptor);
        [cameras addObject:CameraRecord(&connection, descriptor.idVendor, descriptor.idProduct)];
        if (connection.handle != NULL) libusb_close(connection.handle);
    }
    libusb_free_device_list(list, 1);
    libusb_exit(context);
    report[@"cameras"] = cameras;
    return report;
}

static NSDictionary *PTZ(UVCConnection *connection,
                         const char *operation,
                         int64_t requested_pan,
                         int64_t requested_tilt,
                         NSMutableArray *errors) {
    const ControlDefinition *definition = ControlForName("pan_tilt_absolute");
    NSDictionary *control = ReadControl(connection, definition);
    NSMutableDictionary *result = [@{
        @"control_mechanism": @"standard_uvc_camera_terminal_pan_tilt_absolute",
        @"hid_reports_sent": @NO,
        @"zoom_or_focus_writes": @NO,
        @"advertised": control,
    } mutableCopy];
    id current_value = control[@"current"];
    id minimum_value = control[@"min"];
    id maximum_value = control[@"max"];
    id step_value = control[@"step"];
    NSArray *current = [current_value isKindOfClass:[NSArray class]] ? current_value : nil;
    NSArray *minimum = [minimum_value isKindOfClass:[NSArray class]] ? minimum_value : nil;
    NSArray *maximum = [maximum_value isKindOfClass:[NSArray class]] ? maximum_value : nil;
    NSArray *step = [step_value isKindOfClass:[NSArray class]] ? step_value : nil;
    if (current == nil || minimum == nil || maximum == nil || step == nil ||
        current.count != 2 || minimum.count != 2 || maximum.count != 2 || step.count != 2) {
        [errors addObject:@{ @"stage": @"read_ptz", @"error": @"complete_standard_ptz_readback_required" }];
        return result;
    }
    result[@"starting"] = current;
    if (operation == NULL) {
        [errors addObject:@{ @"stage": @"validate_action", @"error": @"missing_ptz_operation" }];
        return result;
    }
    if (strcmp(operation, "get") == 0) {
        result[@"observed_readback"] = current;
        result[@"ok"] = @YES;
        return result;
    }
    if (strcmp(operation, "set") != 0 || requested_pan < INT32_MIN || requested_pan > INT32_MAX ||
        requested_tilt < INT32_MIN || requested_tilt > INT32_MAX) {
        [errors addObject:@{ @"stage": @"validate_action", @"error": @"invalid_ptz_operation_or_target" }];
        return result;
    }
    int64_t targets[2] = { requested_pan, requested_tilt };
    for (NSUInteger index = 0; index < 2; index++) {
        int64_t min_value = [minimum[index] longLongValue];
        int64_t max_value = [maximum[index] longLongValue];
        int64_t step_value = llabs([step[index] longLongValue]);
        if (step_value == 0 || targets[index] < min_value + step_value ||
            targets[index] > max_value - step_value ||
            ((targets[index] - min_value) % step_value) != 0) {
            [errors addObject:@{
                @"stage": @"validate_target",
                @"axis": index == 0 ? @"pan" : @"tilt",
                @"error": @"target_outside_safe_quantized_range",
            }];
            return result;
        }
    }
    unsigned char bytes[8] = {0};
    WriteLE32(bytes, (int32_t)requested_pan);
    WriteLE32(bytes + 4, (int32_t)requested_tilt);
    int transfer_result = UVCTransfer(connection, 0x21, kSetCurrent,
                                      definition->selector, bytes, sizeof(bytes));
    result[@"requested"] = @[ @(requested_pan), @(requested_tilt) ];
    result[@"write"] = ErrorResult(transfer_result);
    if (transfer_result != 8) {
        [errors addObject:@{ @"stage": @"set_ptz", @"error": transfer_result < 0 ? [NSString stringWithUTF8String:USBError(transfer_result)] : @"short_uvc_write" }];
        return result;
    }
    NSDictionary *after = ReadControl(connection, definition);
    result[@"observed_readback"] = after[@"current"] ?: [NSNull null];
    id observed_value = after[@"current"];
    NSArray *observed = [observed_value isKindOfClass:[NSArray class]] ? observed_value : nil;
    BOOL match = observed != nil && observed.count == 2 &&
                 [observed[0] longLongValue] == requested_pan &&
                 [observed[1] longLongValue] == requested_tilt;
    result[@"readback_match"] = @(match);
    result[@"ok"] = @(match);
    if (!match) [errors addObject:@{ @"stage": @"readback", @"error": @"ptz_readback_mismatch" }];
    return result;
}

char *boltrig_uvc_inventory_json(void) {
    @autoreleasepool {
        return JSONBuffer(Inventory());
    }
}

char *boltrig_uvc_ptz_json(const char *descriptor_fingerprint,
                           const char *operation,
                           int64_t pan,
                           int64_t tilt) {
    @autoreleasepool {
        NSMutableArray *errors = Array();
        UVCConnection connection;
        NSMutableDictionary *report = Dict();
        BOOL opened = OpenMatching(&connection, descriptor_fingerprint, errors);
        report[@"descriptor_fingerprint"] = descriptor_fingerprint == NULL ? @"" : [NSString stringWithUTF8String:descriptor_fingerprint];
        report[@"reidentified"] = @(opened);
        if (!opened) {
            report[@"errors"] = errors;
            CloseConnection(&connection);
            return JSONBuffer(report);
        }
        report[@"vid_pid"] = @{
            @"manufacturer": [NSString stringWithUTF8String:connection.manufacturer],
            @"product": [NSString stringWithUTF8String:connection.product],
        };
        report[@"uvc_interface"] = @(connection.interface_number);
        report[@"camera_terminal_id"] = @(connection.terminal_id);
        NSDictionary *operation_result = PTZ(&connection, operation, pan, tilt, errors);
        [report addEntriesFromDictionary:operation_result];
        report[@"errors"] = errors;
        CloseConnection(&connection);
        report[@"handles_closed"] = @YES;
        return JSONBuffer(report);
    }
}

char *boltrig_uvc_capture_json(const char *descriptor_fingerprint) {
    @autoreleasepool {
        NSMutableArray *errors = Array();
        UVCConnection connection;
        NSMutableDictionary *report = Dict();
        BOOL opened = OpenMatching(&connection, descriptor_fingerprint, errors);
        report[@"descriptor_fingerprint"] = descriptor_fingerprint == NULL ? @"" : [NSString stringWithUTF8String:descriptor_fingerprint];
        report[@"reidentified"] = @(opened);
        if (!opened) {
            report[@"errors"] = errors;
            CloseConnection(&connection);
            return JSONBuffer(report);
        }
        NSDictionary *capture = CaptureOneFrame(connection.product, errors);
        [report addEntriesFromDictionary:capture];
        report[@"errors"] = errors;
        CloseConnection(&connection);
        report[@"handles_closed"] = @YES;
        return JSONBuffer(report);
    }
}

void boltrig_uvc_json_free(char *value) {
    free(value);
}
