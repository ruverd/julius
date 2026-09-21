# Native text operation measurement

This is a local operation timing sample, not an agent benchmark or a claim of advantage over another implementation. The input was 100 identical neutral lines (9,599 UTF-8 bytes). The version-2 PyO3 extension returned 2,287 UTF-8 bytes using exact repeated-block markers. The original remains necessary for recovery. No model request was made.

Environment: macOS arm64, Python 3.12.10, release-built `julius._native`, September 21, 2026. One Python process called `compress_repeated_lines` 1,000 times in a loop and measured the whole loop with `time.perf_counter()`. Elapsed time was 0.126847 seconds, or 126.847 microseconds per call in that sample. `tracemalloc` reported a 4,728-byte Python allocation peak; it does not measure all Rust allocations. The process high-water RSS was 21,102,592 bytes and includes the Python interpreter and imported extension. No baseline, confidence interval, concurrent load, or quality evaluation was measured.

Reproduction command:

```sh
.venv/bin/python -c 'import platform,resource,time,tracemalloc; from julius._native import compress_repeated_lines; line="neutral status line with enough characters to reduce and some additional ordinary status detail"; content="\n".join([line]*100); artifact="12345678-1234-1234-1234-123456789abc"; n=1000; tracemalloc.start(); start=time.perf_counter(); output=None
for _ in range(n): output=compress_repeated_lines(content,artifact)
elapsed=time.perf_counter()-start; current,peak=tracemalloc.get_traced_memory(); print({"python":platform.python_version(),"system":platform.system(),"machine":platform.machine(),"iterations":n,"input_bytes":len(content.encode()),"output_bytes":len(output.encode()),"elapsed_seconds":round(elapsed,6),"per_call_microseconds":round(elapsed*1e6/n,3),"tracemalloc_peak_bytes":peak,"process_maxrss":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})'
```
