fn main() {
    for file in ["../labcat.sh", "../labcat.ps1", "../compose.yaml"] {
        println!("cargo:rerun-if-changed={file}");
    }
    tauri_build::build()
}
