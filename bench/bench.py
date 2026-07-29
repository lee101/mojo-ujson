"""mojo-ujson versus upstream ujson on identical payloads."""

from __future__ import annotations

import os
import platform
import sys
import time

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python")
)

import mojo_ujson as mojo  # noqa: E402
import ujson as upstream  # noqa: E402


def best_time(function, repeats=5):
    best = float("inf")
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = function()
        best = min(best, time.perf_counter() - start)
    return best, result


def cpu_name():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown CPU"


def row(name, payload, mojo_fn, upstream_fn):
    mojo_time, mojo_result = best_time(mojo_fn)
    upstream_time, upstream_result = best_time(upstream_fn)
    if isinstance(mojo_result, str):
        assert mojo_result == upstream_result
    else:
        assert mojo_result == upstream_result
    ratio = upstream_time / mojo_time
    return (
        name,
        payload,
        f"{mojo_time * 1000:.2f} ms",
        f"{upstream_time * 1000:.2f} ms",
        f"{ratio:.2f}x",
    )


def main():
    records = [
        {
            "id": i,
            "name": f"record-{i}",
            "active": i % 3 != 0,
            "score": i * 0.125,
            "tags": ["json", "mojo", f"group-{i % 20}"],
        }
        for i in range(50_000)
    ]
    numeric = [i * 0.25 for i in range(250_000)]
    strings = ["café / <script> / \U0001f600 " * 3 for _ in range(50_000)]
    record_json = upstream.dumps(records)
    numeric_json = upstream.dumps(numeric)
    string_json = upstream.dumps(strings, ensure_ascii=False)

    rows = [
        row(
            "loads: records",
            f"{len(record_json) / 1e6:.2f} MB",
            lambda: mojo.loads(record_json),
            lambda: upstream.loads(record_json),
        ),
        row(
            "loads: numeric array",
            f"{len(numeric_json) / 1e6:.2f} MB",
            lambda: mojo.loads(numeric_json),
            lambda: upstream.loads(numeric_json),
        ),
        row(
            "loads: string array",
            f"{len(string_json.encode()) / 1e6:.2f} MB",
            lambda: mojo.loads(string_json),
            lambda: upstream.loads(string_json),
        ),
        row(
            "dumps: records",
            "50,000 objects",
            lambda: mojo.dumps(records),
            lambda: upstream.dumps(records),
        ),
        row(
            "dumps: numeric array",
            "250,000 floats",
            lambda: mojo.dumps(numeric),
            lambda: upstream.dumps(numeric),
        ),
        row(
            "dumps: strings",
            "50,000 strings",
            lambda: mojo.dumps(strings, ensure_ascii=False),
            lambda: upstream.dumps(strings, ensure_ascii=False),
        ),
    ]

    print(f"Machine: {cpu_name()} ({platform.system()} {platform.machine()})")
    print(f"Python {platform.python_version()}, ujson {upstream.__version__}")
    print()
    print("| Operation | Payload | mojo-ujson | ujson | Relative |")
    print("|---|---:|---:|---:|---:|")
    for values in rows:
        print("| " + " | ".join(values) + " |")
    print()
    print("Relative is upstream time / mojo-ujson time; above 1.00x favors mojo-ujson.")


if __name__ == "__main__":
    main()
