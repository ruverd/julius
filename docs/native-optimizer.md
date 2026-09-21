# Native candidate reduction

The Rust optimizer recognizes exact repeated neutral lines and bounded blocks of two to eight adjacent neutral lines. A block must occur at least three times without overlap. It keeps the first copy and replaces later copies with a marker naming the first copy's original line span and the original recovery artifact. The Python optimizer requires an available artifact before calling Rust. Restoration reads that original artifact; the marker alone is not a substitute for it.

Only a candidate with fewer UTF-8 bytes is returned. Protected errors, assertions, instructions, control characters, code fences, and other guarded content remain outside the Python transform. Rust also rejects protected words in a line. A known line or block marker requires explicit recompression permission and prior-transform lineage. The receipt's token counts remain UTF-8-byte heuristics; no provider measurement or savings is inferred. The transform makes no model request.

The bounded block search is intentionally conservative: it selects one repeated block pattern per call, does not normalize whitespace, and skips structured text containing disallowed punctuation. This leaves some reducible output untouched to preserve exact evidence.
