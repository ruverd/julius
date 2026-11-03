use std::{env, path::PathBuf};

fn main() {
    let core = PathBuf::from(
        env::var("JULIUS_TREE_SITTER")
            .expect("Set JULIUS_TREE_SITTER to the installed tree-sitter package"),
    )
    .join("vendor/tree-sitter/lib");
    let grammar = PathBuf::from(
        env::var("JULIUS_TS_GRAMMAR")
            .expect("Set JULIUS_TS_GRAMMAR to the installed TypeScript grammar package"),
    );
    cc::Build::new()
        .define("_POSIX_C_SOURCE", "200112L")
        .define("_DEFAULT_SOURCE", None)
        .include(core.join("src"))
        .include(core.join("include"))
        .file(core.join("src/lib.c"))
        .flag_if_supported("-std=c11")
        .warnings(false)
        .compile("julius_ts_core");
    for name in ["typescript", "tsx"] {
        let dir = grammar.join(name).join("src");
        cc::Build::new()
            .include(&dir)
            .file(dir.join("parser.c"))
            .file(dir.join("scanner.c"))
            .flag_if_supported("-std=c11")
            .warnings(false)
            .compile(&format!("julius_ts_{name}"));
    }
    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-link-arg=-undefined");
        println!("cargo:rustc-link-arg=dynamic_lookup");
    }
    println!("cargo:rerun-if-env-changed=JULIUS_TREE_SITTER");
    println!("cargo:rerun-if-env-changed=JULIUS_TS_GRAMMAR");
    println!("cargo:rerun-if-changed={}", core.display());
    println!("cargo:rerun-if-changed={}", grammar.display());
}
