fn main() {
    println!("cargo:rerun-if-env-changed=BOLTRIG_UPDATER_ENDPOINT");
    println!("cargo:rerun-if-env-changed=BOLTRIG_UPDATER_PUBLIC_KEY");
    tauri_build::build()
}
