# mojo-ujson

`mojo-ujson` is a standalone Mojo implementation of the compute-heavy parts of
[`ujson`](https://pypi.org/project/ujson/): JSON scanning, string decoding, and
JSON string escaping. A small Python layer constructs Python objects and exposes
the familiar `dumps`, `dump`, `loads`, `load`, `encode`, and `decode` names.

This is a real codec rather than a wrapper around `json` or `ujson`. The test
suite compares its results directly with upstream ujson 5.13.0.

## Coverage

The supported serialization types are `dict`, `list`, `tuple`, `str`, `int`,
`float`, `bool`, `None`, and `bytes` when `reject_bytes=False`. Dictionary keys
may be strings, bytes, numbers, booleans, or `None`. `dumps` supports the current
ujson options:

- `ensure_ascii`
- `encode_html_chars`
- `escape_forward_slashes`
- `sort_keys`
- `indent`
- `allow_nan`
- `reject_bytes`
- `default`

`loads` accepts `str`, `bytes`, `bytearray`, and `memoryview`. It handles nested
arrays and objects, escaped and raw UTF-8 strings, UTF-16 surrogate pairs,
arbitrary-size integers, non-finite floats, duplicate keys, and the same
leading-zero number extension accepted by ujson.

Not covered are ujson's incidental conversions for third-party extension types,
byte-for-byte matching of every error message, and its C extension's direct
construction of CPython objects. The current ujson 5.13.0 `loads` accepts only
one argument, so older `precise_float` APIs are not implemented.

## Install

The repository pins the tested Mojo nightly. Install the environment and build
the shared library:

```bash
pixi install
pixi run build
```

The build task produces `dist/libmojo-ujson.so`.

## Usage

```python
import mojo_ujson as ujson

payload = {
    "message": "café",
    "values": [1, 2.5, None],
}

encoded = ujson.dumps(payload, ensure_ascii=False, indent=2)
decoded = ujson.loads(encoded)
assert decoded == payload
```

Run the parity suite and benchmarks with:

```bash
pixi run test
pixi run bench
```

## How it works

The C ABI passes integer addresses and scalar sizes. Python owns every buffer,
keeps the GIL and buffer references alive for the synchronous native call, and
validates that each NumPy work array is non-empty, C-contiguous, and has the
expected dtype. Mojo reconstructs each address as an
`UnsafePointer[..., AnyOrigin[mut=True]]`; neither side needs a cross-language
allocator or free function.

For decoding, Mojo performs the structural scan, validates tokens and numbers,
decodes escapes, combines UTF-16 surrogate pairs, and emits a compact event
stream into caller-owned arrays. Python walks those events once to allocate the
requested lists, dictionaries, strings, integers, and floats.

For encoding, Python flattens the object graph into raw structural spans and
UTF-8 string spans. A single Mojo call copies structural data and performs JSON
escaping, ASCII conversion, HTML-character encoding, and optional forward-slash
escaping into a preallocated output buffer. All kernels live in one compilation
unit to keep Mojo build overhead fixed.

Clean string runs and raw output spans use full-width SIMD loads and stores with
scalar tail handling. The escaping mask includes quotes, backslashes, control
bytes, non-ASCII bytes when required, forward slashes, and HTML characters, so
all encoding options retain the same SIMD path. Input `bytes`, `bytearray`, and
contiguous `memoryview` objects and the flattened encoding blob stay zero-copy
across the FFI boundary; non-contiguous views are normalized to bytes. Parser
work buffers use two contiguous NumPy arenas instead of seven independent
allocations. Homogeneous top-level float and string arrays are materialized in
bulk after the Mojo parser has validated the complete document, with bounded
caches avoiding repeated UTF-8 encoding and decoding.

There is no parallel or GPU path. JSON grammar state and escaped-output offsets
are sequential, while the independent scanning and copy work has far below two
operations per byte and is memory-bound. CPU thread launch overhead would exceed
the available independent work at these payload sizes. A GPU path would add
allocation, transfer, and synchronization to a low-arithmetic-intensity kernel,
so it is intentionally skipped rather than exposing a path that loses.

## Benchmarks

Measured with `pixi run bench` on an Intel Xeon E5-2697 v4 at 2.30 GHz,
Linux x86-64, Python 3.13.14, and upstream ujson 5.13.0:

| Operation | Payload | mojo-ujson | ujson | Relative |
|---|---:|---:|---:|---:|
| loads: records | 4.92 MB | 608.76 ms | 84.78 ms | 0.14x |
| loads: numeric array | 2.08 MB | 51.78 ms | 26.17 ms | 0.51x |
| loads: string array | 4.05 MB | 43.96 ms | 22.89 ms | 0.52x |
| dumps: records | 50,000 objects | 692.19 ms | 49.93 ms | 0.07x |
| dumps: numeric array | 250,000 floats | 108.39 ms | 41.04 ms | 0.38x |
| dumps: strings | 50,000 strings | 51.36 ms | 20.30 ms | 0.40x |

Relative is upstream time divided by mojo-ujson time, so values above 1.00x
favor mojo-ujson. Mojo-ujson is slower in every end-to-end case measured here.
Upstream constructs CPython objects directly inside its mature C extension;
this port pays for NumPy work buffers and Python-level event or object traversal.
The string-heavy cases narrow that gap because a larger fraction of the work
runs inside the Mojo kernels. Against the locked baseline taken immediately
before these changes, string-array loads improved from 75.70 ms to 43.96 ms,
numeric-array dumps from 144.33 ms to 108.39 ms, and string-array dumps from
69.73 ms to 51.36 ms. Record loads regressed from 586.14 ms to 608.76 ms; their
Python object construction remains the dominant cost.
