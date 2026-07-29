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
scalar tail handling. Input `bytes` and `bytearray` objects and the flattened
encoding blob stay zero-copy across the FFI boundary; `memoryview` inputs are
normalized to bytes so multidimensional views have an unambiguous byte length.
Homogeneous top-level float and string arrays are materialized in bulk after the
Mojo parser has validated the complete document.

There is no parallel or GPU path. JSON grammar state and escaped-output offsets
are sequential, and the independent scanning and copy work is memory-bound.
Thread launch overhead and GPU allocation, transfer, and synchronization are
outside the scope of this port.

## Benchmarks

Measured with `pixi run bench` on an Intel Xeon E5-2697 v4 at 2.30 GHz,
Linux x86-64, Python 3.13.14, and upstream ujson 5.13.0:

| Operation | Payload | mojo-ujson | ujson | Relative |
|---|---:|---:|---:|---:|
| loads: records | 4.92 MB | 799.07 ms | 103.19 ms | 0.13x |
| loads: numeric array | 2.08 MB | 56.44 ms | 30.46 ms | 0.54x |
| loads: string array | 4.05 MB | 70.11 ms | 23.65 ms | 0.34x |
| dumps: records | 50,000 objects | 778.46 ms | 99.04 ms | 0.13x |
| dumps: numeric array | 250,000 floats | 148.20 ms | 40.97 ms | 0.28x |
| dumps: strings | 50,000 strings | 62.00 ms | 20.39 ms | 0.33x |

Relative is upstream time divided by mojo-ujson time, so values above 1.00x
favor mojo-ujson. Mojo-ujson is slower in every end-to-end case measured here.
Upstream constructs CPython objects directly inside its mature C extension;
this port pays for NumPy work buffers and Python-level event or object traversal.
The string-heavy cases narrow that gap because a larger fraction of the work
runs inside the Mojo kernels.
