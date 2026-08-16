CC ?= clang
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic
LIBUSB_CFLAGS := $(shell pkg-config --cflags libusb-1.0)
LIBUSB_LIBS := $(shell pkg-config --libs libusb-1.0)

TARGET := build/pixy-probe
PTZ_TARGET := build/pixy-ptz-test

.PHONY: all clean

all: $(TARGET) $(PTZ_TARGET)

$(TARGET): pixy_probe.m | build
	$(CC) $(CFLAGS) -fobjc-arc $(LIBUSB_CFLAGS) \
		-framework Foundation -framework AVFoundation -framework CoreMedia \
		-framework CoreAudio -framework AudioToolbox \
		$< $(LIBUSB_LIBS) -o $@

$(PTZ_TARGET): pixy_ptz_test.m | build
	$(CC) $(CFLAGS) -fobjc-arc $(LIBUSB_CFLAGS) \
		-framework Foundation \
		$< $(LIBUSB_LIBS) -o $@

build:
	mkdir -p $@

clean:
	@rm -f $(TARGET)
