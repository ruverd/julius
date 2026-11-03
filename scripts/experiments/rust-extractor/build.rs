use std::{env, path::PathBuf};

fn main() {
    let root = PathBuf::from(env::var("JULIUS_NODE_MODULES").expect("Set JULIUS_NODE_MODULES to installed npm dependencies"));
    let core = root.join("tree-sitter/vendor/tree-sitter/lib");
    let grammar = root.join("tree-sitter-typescript");
    cc::Build::new().include(core.join("src")).include(core.join("include"))
        .file(core.join("src/lib.c")).flag_if_supported("-std=c11").warnings(false).compile("julius_ts_core");
    for name in ["typescript", "tsx"] {
        let dir = grammar.join(name).join("src");
        cc::Build::new().include(&dir).file(dir.join("parser.c")).file(dir.join("scanner.c"))
            .flag_if_supported("-std=c11").warnings(false).compile(&format!("julius_ts_{name}"));
    }
    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-link-arg=-undefined");
        println!("cargo:rustc-link-arg=dynamic_lookup");
    }
    println!("cargo:rerun-if-env-changed=JULIUS_NODE_MODULES");
    println!("cargo:rerun-if-changed={}", core.display());
    println!("cargo:rerun-if-changed={}", grammar.display());
}
