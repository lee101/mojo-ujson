from __future__ import annotations

import io
import math
import random

import numpy as np
import pytest
import ujson as upstream

import mojo_ujson as mojo
from mojo_ujson import _input_buffer


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -17,
        10**100,
        0.0,
        -0.0,
        1e-7,
        1e20,
        1.2345678901234567,
        "",
        "plain ASCII",
        '"quotes" and \\ slashes /',
        "café",
        "supplementary: \U0001f600",
        "\b\f\n\r\t\x01",
        [],
        {},
        [1, "two", None, False],
        {"a": 1, "nested": [True, {"x": "é"}]},
        (1, 2, 3),
    ],
)
def test_dumps_exact_scalar_and_container_parity(value):
    assert mojo.dumps(value) == upstream.dumps(value)


@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("escape_forward_slashes", [True, False])
@pytest.mark.parametrize("encode_html_chars", [True, False])
def test_dumps_escape_option_parity(
    ensure_ascii, escape_forward_slashes, encode_html_chars
):
    value = {"markup": "</script>&", "unicode": "é\U0001f600"}
    options = {
        "ensure_ascii": ensure_ascii,
        "escape_forward_slashes": escape_forward_slashes,
        "encode_html_chars": encode_html_chars,
    }
    assert mojo.dumps(value, **options) == upstream.dumps(value, **options)


@pytest.mark.parametrize("indent", [0, -1, 1, 2, 4])
def test_dumps_indent_parity(indent):
    value = {"a": [1, 2, {"x": []}], "b": {}}
    assert mojo.dumps(value, indent=indent) == upstream.dumps(value, indent=indent)


def test_dumps_sort_keys_parity():
    value = {"z": 1, "a": {"y": 2, "b": 3}, "m": 4}
    assert mojo.dumps(value, sort_keys=True) == upstream.dumps(value, sort_keys=True)


def test_dumps_non_string_key_parity():
    value = {1: "int", 1.5: "float", None: "none", False: "bool", b"bytes": "key"}
    assert mojo.dumps(value) == upstream.dumps(value)


def test_dumps_bytes_value_when_allowed():
    value = "café".encode()
    assert mojo.dumps(value, reject_bytes=False) == upstream.dumps(
        value, reject_bytes=False
    )


def test_dumps_rejects_bytes_by_default():
    with pytest.raises(TypeError):
        mojo.dumps(b"value")
    with pytest.raises(TypeError):
        upstream.dumps(b"value")


def test_dumps_default_callback_parity():
    class Record:
        def __init__(self):
            self.value = 42

    callback = lambda obj: {"value": obj.value}
    assert mojo.dumps(Record(), default=callback) == upstream.dumps(
        Record(), default=callback
    )


def test_dumps_rejects_unsupported_type():
    with pytest.raises(TypeError):
        mojo.dumps({1, 2, 3})


def test_dumps_nonfinite_float_parity():
    value = [math.nan, math.inf, -math.inf]
    assert mojo.dumps(value) == upstream.dumps(value)
    with pytest.raises(OverflowError):
        mojo.dumps(value, allow_nan=False)


def test_dumps_surrogate_parity():
    value = {"single": "\ud800", "pair": "\ud83d\ude00"}
    assert mojo.dumps(value) == upstream.dumps(value)
    assert mojo.dumps(value, ensure_ascii=False) == upstream.dumps(
        value, ensure_ascii=False
    )


@pytest.mark.parametrize(
    "document",
    [
        "null",
        "true",
        "false",
        "0",
        "-42",
        "01",
        "1.",
        "6.022e23",
        "1e-400",
        '"text"',
        '"escaped\\ntext"',
        '"\\u00e9\\ud83d\\ude00"',
        "[]",
        "{}",
        "[1,true,null,\"x\"]",
        '{"a":1,"b":[2,3],"c":{"d":"four"}}',
        " \n\t {\"spaced\" : [ 1 , 2 ] } \r",
        "[NaN,Infinity,-Infinity]",
        '{"a":1,"a":2}',
    ],
)
def test_loads_behavioral_parity(document):
    got = mojo.loads(document)
    expected = upstream.loads(document)
    if document == "[NaN,Infinity,-Infinity]":
        assert math.isnan(got[0]) and math.isnan(expected[0])
        assert got[1:] == expected[1:]
    else:
        assert got == expected


def test_loads_accepts_bytes_bytearray_and_memoryview():
    document = b'{"answer":42,"items":[1,2]}'
    for value in (document, bytearray(document), memoryview(document)):
        assert mojo.loads(value) == upstream.loads(value)


def test_loads_accepts_multidimensional_contiguous_memoryview():
    array = np.frombuffer(b"[1,2] ", dtype=np.uint8).reshape(2, 3)
    value = memoryview(array)
    normalized = _input_buffer(value)
    assert isinstance(normalized, memoryview)
    assert normalized.obj is array
    assert mojo.loads(value) == upstream.loads(value) == [1, 2]


def test_loads_unpaired_surrogate_parity():
    assert mojo.loads('"\\ud800"') == upstream.loads('"\\ud800"')


def test_loads_duplicate_keys_keep_last_value():
    assert mojo.loads('{"key":1,"key":2}') == {"key": 2}


@pytest.mark.parametrize(
    "document",
    [
        "",
        "1 2",
        "[1,]",
        '{"a":1,}',
        '{"a" 1}',
        "[+1]",
        '"\\x20"',
        '"\\uZZZZ"',
        '"unterminated',
        '"nul\x00byte"',
    ],
)
def test_loads_rejects_documents_upstream_rejects(document):
    with pytest.raises(upstream.JSONDecodeError):
        upstream.loads(document)
    with pytest.raises(mojo.JSONDecodeError):
        mojo.loads(document)


def test_loads_rejects_wrong_input_type():
    with pytest.raises(TypeError):
        mojo.loads(123)


def test_dump_and_load_file_api_parity():
    value = {"name": "café", "values": [1, 2, 3]}
    mojo_file = io.StringIO()
    upstream_file = io.StringIO()
    assert mojo.dump(value, mojo_file, ensure_ascii=False, indent=2) is None
    assert upstream.dump(value, upstream_file, ensure_ascii=False, indent=2) is None
    assert mojo_file.getvalue() == upstream_file.getvalue()
    mojo_file.seek(0)
    assert mojo.load(mojo_file) == value


def test_encode_decode_aliases():
    value = {"alias": [1, 2, 3]}
    assert mojo.encode(value) == mojo.dumps(value)
    assert mojo.decode(mojo.encode(value)) == value


def test_rfc8259_interoperability_example():
    document = (
        '{"Image":{"Width":800,"Height":600,"Title":"View from 15th Floor",'
        '"Thumbnail":{"Url":"http://www.example.com/image/481989943",'
        '"Height":125,"Width":100},"Animated":false,"IDs":[116,943,234,38793]}}'
    )
    assert mojo.loads(document) == upstream.loads(document)
    assert mojo.loads(mojo.dumps(mojo.loads(document))) == upstream.loads(document)


def test_random_nested_parity():
    rng = random.Random(0)

    def make(depth):
        if depth == 0:
            return rng.choice(
                [None, True, False, rng.randint(-10**9, 10**9), rng.random(), "é/<>"]
            )
        if rng.random() < 0.5:
            return [make(depth - 1) for _ in range(rng.randrange(5))]
        return {f"k{i}": make(depth - 1) for i in range(rng.randrange(5))}

    for _ in range(100):
        value = make(4)
        encoded = mojo.dumps(value, sort_keys=True)
        assert encoded == upstream.dumps(value, sort_keys=True)
        assert mojo.loads(encoded) == upstream.loads(encoded)


def test_large_document_roundtrip():
    value = [
        {"id": i, "name": f"row-{i}", "values": [i * 0.5, i % 7, None]}
        for i in range(10_000)
    ]
    encoded = mojo.dumps(value)
    assert mojo.loads(encoded) == value
    assert encoded == upstream.dumps(value)


@pytest.mark.parametrize("length", [0, 1, 31, 32, 33, 63, 64, 65])
def test_simd_string_scan_and_copy_tails(length):
    value = {
        "plain": "a" * length,
        "escaped": "b" * length + '"\\\n',
        "raw": list(range(length)),
    }
    encoded = upstream.dumps(value)
    assert mojo.loads(encoded) == value
    assert mojo.dumps(value) == encoded


@pytest.mark.parametrize("length", [31, 32, 33, 63, 64, 65])
@pytest.mark.parametrize(
    "options",
    [
        {"ensure_ascii": False, "escape_forward_slashes": False},
        {"ensure_ascii": True, "escape_forward_slashes": False},
        {"ensure_ascii": False, "encode_html_chars": True},
    ],
)
def test_simd_encode_option_masks_and_tails(length, options):
    value = "a" * length + "é/<>" + "b" * length
    assert mojo.dumps(value, **options) == upstream.dumps(value, **options)


def test_bulk_float_and_string_array_decode_parity():
    documents = [
        "[0.0,-0.0,1.2345678901234567,1e-300,1e+300]",
        '["","ascii","café","quote: \\"","supplementary: \U0001f600"]',
    ]
    for document in documents:
        assert mojo.loads(document) == upstream.loads(document)

    repeated = ["repeated café / value"] * 2048
    document = upstream.dumps(repeated, ensure_ascii=False)
    assert mojo.loads(document) == repeated


def test_bulk_finite_float_array_encode_parity():
    value = [index * 0.25 for index in range(4096)]
    assert mojo.dumps(value) == upstream.dumps(value)


def test_large_empty_string_array_does_not_underallocate_output():
    value = [""] * 10_000
    assert mojo.dumps(value) == upstream.dumps(value)
