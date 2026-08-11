#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <stdlib.h>
#include <string.h>

static NSString *json_escape(NSString *value) {
    NSMutableString *escaped = [NSMutableString string];
    for (NSUInteger index = 0; index < value.length; index++) {
        unichar character = [value characterAtIndex:index];
        switch (character) {
            case '"': [escaped appendString:@"\\\""]; break;
            case '\\': [escaped appendString:@"\\\\"]; break;
            case '\b': [escaped appendString:@"\\b"]; break;
            case '\f': [escaped appendString:@"\\f"]; break;
            case '\n': [escaped appendString:@"\\n"]; break;
            case '\r': [escaped appendString:@"\\r"]; break;
            case '\t': [escaped appendString:@"\\t"]; break;
            default:
                if (character < 0x20) {
                    [escaped appendFormat:@"\\u%04x", character];
                } else {
                    [escaped appendFormat:@"%C", character];
                }
                break;
        }
    }
    return escaped;
}

static const char *permission_name(AVAuthorizationStatus status) {
    switch (status) {
        case AVAuthorizationStatusAuthorized: return "authorized";
        case AVAuthorizationStatusDenied: return "denied";
        case AVAuthorizationStatusRestricted: return "restricted";
        case AVAuthorizationStatusNotDetermined: return "not_determined";
    }
    return "unknown";
}

char *boltrig_camera_inventory_json(void) {
    @autoreleasepool {
        AVAuthorizationStatus permission =
            [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
        AVCaptureDeviceDiscoverySession *session =
            [AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:
                @[ AVCaptureDeviceTypeBuiltInWideAngleCamera, AVCaptureDeviceTypeExternal ]
                mediaType:AVMediaTypeVideo position:AVCaptureDevicePositionUnspecified];
        NSArray<AVCaptureDevice *> *devices = session.devices;
        NSMutableString *json = [NSMutableString stringWithString:
            @"{\"schema_version\":1,\"runtime\":\"avfoundation\",\"state\":\"available\",\"reason\":null,\"cameras\":["];
        for (NSUInteger index = 0; index < devices.count; index++) {
            AVCaptureDevice *device = devices[index];
            if (index > 0) [json appendString:@","];
            NSString *nativeKey = json_escape(device.uniqueID ?: @"");
            NSString *label = json_escape(device.localizedName ?: @"Camera");
            NSString *model = json_escape(device.modelID ?: @"unknown");
            [json appendFormat:
                @"{\"native_key\":\"%@\",\"label\":\"%@\",\"model\":\"%@\",\"permission\":\"%s\",\"format_count\":%lu}",
                nativeKey, label, model, permission_name(permission), (unsigned long)device.formats.count];
        }
        [json appendString:@"]}"];
        const char *bytes = json.UTF8String;
        return bytes == NULL ? NULL : strdup(bytes);
    }
}

void boltrig_camera_inventory_free(char *value) {
    free(value);
}
