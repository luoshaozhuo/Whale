# OPC UA Profiling Guide

Whale's production OPC UA reader path does not keep invasive profiling code.
Fine-grained timing splits such as internal decode/check/build breakdowns
should be collected with external profilers, not hard-coded into production
or load-test paths.

The OPC UA backends do not expose diagnostic-only read APIs. Start from
business-level load-test results first, then attach an external profiler to
the Python process. For the open62541 runner itself, use system/native tools
separately when needed.

### Recommended workflow

1. Run the existing load test first and check business-level outcomes:
   - `ach`
   - `miss_pct`
   - `j95` / `jmax`
   - `raw95` / `rawmax`
   - `t95` / `tmax`
   - `min_p`
2. If those metrics look abnormal, use `py-spy` to find hot paths.
3. If the hotspot is in Python call stacks, use `pyinstrument`.
4. If you suspect memory allocation pressure or Python-vs-native CPU split,
   use `scalene`.

### py-spy

Use `py-spy` when you want non-intrusive sampling against a running process or
to record one whole pytest run.

Find the target PID first, then:

```bash
py-spy top --pid <PID>
py-spy record -o profile.svg --pid <PID>
```

Or record one direct test invocation:

```bash
py-spy record -o profile.svg -- python -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

### pyinstrument

Use `pyinstrument` for one-shot async call-stack analysis around a single test
or script.

```bash
pyinstrument -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

This is useful when you want a readable hierarchical view of Python-side time.

### scalene

Use `scalene` when you need CPU and memory attribution, including Python time
vs native time.

```bash
python -m scalene -m pytest tools/source_lab/tests/test_source_simulation_multi_server_bottleneck.py -s -v
```

This is helpful for spotting:
- Python allocation pressure
- native-library hot spots
- Python-vs-native CPU split

### Notes

- `py-spy` is usually the best first step because it is the least intrusive.
- `pyinstrument` is better for understanding Python call-tree structure.
- `scalene` is better for CPU-type and memory attribution.
- Keep production code clean; prefer tooling over embedded timing probes.
- If `min_p` is low, first suspect event-loop scheduling, client decode work,
  or process-level scheduling pressure.
- For open62541 investigations, profile both:
  - the Python reader process
  - the C runner process with native/system tooling such as `top`, `perf`, or
    flamegraph tooling
