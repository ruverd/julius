# Native dependency compatibility

Julius supports Node.js 20 and later. Native parser updates must preserve both
native extraction and the WASM fallback; a successful fallback alone does not
prove that a native dependency upgrade works.

## Tree-sitter 0.25 and PHP 0.24

The native runtime is Tree-sitter 0.25.1. PHP 0.24.2 uses grammar ABI 15, which
the previous 0.21 runtime cannot load. Upgrade these two packages together.

Several grammar packages still declare peer ranges for Tree-sitter 0.21 or 0.22.
The scoped npm overrides select the root runtime for those packages in this
repository. They are compatibility assertions, backed by
`node scripts/verify-native-parsers.mjs` and the graph extraction tests, rather
than a blanket `--force` or `--legacy-peer-deps` install policy.

The native verification script loads all nine grammars directly and parses a
sample in each language. PHP includes an enum with an array constant, which
the previous grammar could not parse correctly. CI runs this check on Linux and
Windows with Node 20. Node 24 retains separate WASM coverage.

npm does not apply dependency packages' overrides in a consuming project.
Before releasing parser upgrades, also install the packed Julius tarball in an
empty project without peer-resolution flags and run the installed
`scripts/verify-native-parsers.mjs`. npm may report the grammars' stale peer
ranges as warnings; installation and actual native parsing must still succeed.

## Node-gyp

Keep node-gyp on 12.x while Node 20 is supported. Version 13.1.0 requires
`^22.22.2 || ^24.15.0 || >=26.0.0` and fails during native compilation on Node 20.
Changing peer overrides cannot make this engine requirement compatible.
Revisit the major upgrade only alongside an explicit minimum-Node decision.
