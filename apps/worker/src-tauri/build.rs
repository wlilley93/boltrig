fn main() {
    println!("cargo:rerun-if-env-changed=BOLTRIG_UPDATER_ENDPOINT");
    println!("cargo:rerun-if-env-changed=BOLTRIG_UPDATER_PUBLIC_KEY");
    #[cfg(target_os = "macos")]
    {
        println!("cargo:rerun-if-changed=src/camera_discovery.m");
        println!("cargo:rerun-if-changed=src/camera_uvc.m");
        let libusb = pkg_config::Config::new()
            .atleast_version("1.0")
            .probe("libusb-1.0")
            .expect("libusb-1.0 is required for native UVC camera control");
        let mut build = cc::Build::new();
        build
            .file("src/camera_discovery.m")
            .file("src/camera_uvc.m")
            .flag("-fobjc-arc")
            .include("src");
        for path in libusb.include_paths {
            build.include(path);
        }
        build.compile("boltrig_camera_native");
        for framework in ["AVFoundation", "Foundation"] {
            println!("cargo:rustc-link-lib=framework={framework}");
        }
    }
    tauri_build::build()
}
