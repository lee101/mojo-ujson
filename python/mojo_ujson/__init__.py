"""A ujson-compatible JSON codec accelerated by Mojo."""

from __future__ import annotations

import math
import operator
from typing import Any

import numpy as np

from ._lib import lib

__version__ = "0.1.0"
version_info = (0, 1, 0)

K_NULL = 1
K_FALSE = 2
K_TRUE = 3
K_INT = 4
K_FLOAT = 5
K_STRING = 6
K_KEY = 7
K_ARRAY_START = 8
K_ARRAY_END = 9
K_OBJECT_START = 10
K_OBJECT_END = 11


class JSONDecodeError(ValueError):
    pass


def _addr(array: np.ndarray, dtype: np.dtype[Any]) -> int:
    if array.dtype != dtype or not array.flags.c_contiguous or array.size == 0:
        raise RuntimeError("invalid native-call buffer")
    address = int(array.ctypes.data)
    if address == 0:
        raise RuntimeError("null native-call buffer")
    return address


def _input_buffer(obj: Any) -> bytes | bytearray | memoryview:
    if isinstance(obj, str):
        return obj.encode("utf-8", "surrogatepass")
    if isinstance(obj, (bytes, bytearray)):
        return obj
    if isinstance(obj, memoryview):
        if obj.c_contiguous:
            return obj.cast("B")
        return obj.tobytes()
    raise TypeError(f"Expected string or C-contiguous bytes-like object")


def loads(obj: Any) -> Any:
    source = _input_buffer(obj)
    n = len(source)
    src = np.frombuffer(source, dtype=np.uint8)
    if not n:
        src = np.zeros(1, dtype=np.uint8)
    capacity = n + 1
    byte_work = np.empty(4 * capacity + 2, dtype=np.uint8)
    kinds = byte_work[:capacity]
    strings = byte_work[capacity : 2 * capacity]
    stack_type = byte_work[2 * capacity : 3 * capacity + 1]
    stack_state = byte_work[3 * capacity + 1 :]
    int_work = np.empty(2 * capacity + 3, dtype=np.int64)
    starts = int_work[:capacity]
    ends = int_work[capacity : 2 * capacity]
    errors = int_work[2 * capacity :]

    count = lib().mujson_parse(
        _addr(src, np.dtype(np.uint8)),
        n,
        _addr(kinds, np.dtype(np.uint8)),
        _addr(starts, np.dtype(np.int64)),
        _addr(ends, np.dtype(np.int64)),
        _addr(strings, np.dtype(np.uint8)),
        _addr(stack_type, np.dtype(np.uint8)),
        _addr(stack_state, np.dtype(np.uint8)),
        _addr(errors, np.dtype(np.int64)),
    )
    if count < 0:
        messages = {
            1: "Expected object or value",
            2: "Trailing data",
            3: "Unexpected character in container",
            4: "Expected ':' after object key",
            5: "Object keys must be strings",
            6: "Unmatched '\"' when decoding 'string'",
            7: "Unexpected character in unicode escape sequence when decoding 'string'",
            8: "Unrecognized escape sequence when decoding 'string'",
            9: "Invalid number",
            10: "Expected object or value",
        }
        code, pos = int(errors[0]), int(errors[1])
        raise JSONDecodeError(f"{messages.get(code, 'Invalid JSON')} at character {pos}")

    source_view = memoryview(source)
    string_view = memoryview(strings)
    kinds_view = memoryview(kinds)
    starts_view = memoryview(starts)
    ends_view = memoryview(ends)
    if (
        count > 2
        and kinds_view[0] == K_ARRAY_START
        and kinds_view[count - 1] == K_ARRAY_END
    ):
        inner_kinds = kinds[1 : count - 1]
        if np.all(inner_kinds == K_FLOAT):
            inner_start = ends_view[0]
            inner_end = starts_view[count - 1]
            numeric_text = bytes(source_view[inner_start:inner_end])
            numeric_values = list(map(float, numeric_text.split(b",")))
            if len(numeric_values) == count - 2:
                return numeric_values
        if np.all(inner_kinds == K_STRING):
            try:
                decoded: list[str] = []
                decoded_cache: dict[bytes, str] = {}
                for event in range(1, count - 1):
                    encoded = bytes(
                        string_view[starts_view[event] : ends_view[event]]
                    )
                    value = decoded_cache.get(encoded)
                    if value is None:
                        value = encoded.decode("utf-8", "surrogatepass")
                        if len(decoded_cache) < 1024:
                            decoded_cache[encoded] = value
                    decoded.append(value)
                return decoded
            except UnicodeError as exc:
                raise JSONDecodeError(str(exc)) from None
    containers: list[Any] = []
    pending_keys: list[str | None] = []
    container_is_list: list[bool] = []
    key_cache: dict[bytes, str] = {}
    root: Any = None
    have_root = False

    try:
        for event in range(count):
            kind = kinds_view[event]
            start, end = starts_view[event], ends_view[event]
            if kind == K_NULL:
                value = None
            elif kind == K_FALSE:
                value = False
            elif kind == K_TRUE:
                value = True
            elif kind == K_INT:
                value = int(source_view[start:end])
            elif kind == K_FLOAT:
                value = float(source_view[start:end])
            elif kind in (K_STRING, K_KEY):
                encoded = bytes(string_view[start:end])
                if kind == K_KEY:
                    value = key_cache.get(encoded)
                    if value is None:
                        value = encoded.decode("utf-8", "surrogatepass")
                        if len(key_cache) < 1024:
                            key_cache[encoded] = value
                    pending_keys[-1] = value
                    continue
                value = encoded.decode("utf-8", "surrogatepass")
            elif kind == K_ARRAY_START:
                value = []
            elif kind == K_OBJECT_START:
                value = {}
            elif kind in (K_ARRAY_END, K_OBJECT_END):
                containers.pop()
                pending_keys.pop()
                container_is_list.pop()
                continue

            if not containers:
                root = value
                have_root = True
            elif container_is_list[-1]:
                containers[-1].append(value)
            else:
                containers[-1][pending_keys[-1]] = value
                pending_keys[-1] = None

            if kind == K_ARRAY_START:
                containers.append(value)
                pending_keys.append(None)
                container_is_list.append(True)
            elif kind == K_OBJECT_START:
                containers.append(value)
                pending_keys.append(None)
                container_is_list.append(False)
    except (UnicodeError, ValueError, OverflowError) as exc:
        raise JSONDecodeError(str(exc)) from None
    if not have_root:
        raise JSONDecodeError("Expected object or value")
    return root


decode = loads


class _TokenWriter:
    __slots__ = ("blob", "kinds", "starts", "ends", "key_data", "long_strings")

    def __init__(self) -> None:
        self.blob = bytearray()
        self.kinds: list[int] = []
        self.starts: list[int] = []
        self.ends: list[int] = []
        self.key_data: dict[str, bytes] = {}
        self.long_strings: dict[str, bytes] = {}

    def raw(self, value: str) -> None:
        start = len(self.blob)
        if len(value) == 1:
            self.blob.append(ord(value))
        else:
            self.blob.extend(value.encode("ascii"))
        if self.kinds and self.kinds[-1] == 0 and self.ends[-1] == start:
            self.ends[-1] = len(self.blob)
        else:
            self.kinds.append(0)
            self.starts.append(start)
            self.ends.append(len(self.blob))

    def string(self, value: str, kind: int = 1) -> None:
        if len(value) >= 32:
            data = self.long_strings.get(value)
            if data is None:
                data = value.encode("utf-8", "surrogatepass")
                if len(self.long_strings) < 64:
                    self.long_strings[value] = data
        else:
            data = value.encode("utf-8", "surrogatepass")
        start = len(self.blob)
        self.blob.extend(data)
        self.kinds.append(kind)
        self.starts.append(start)
        self.ends.append(len(self.blob))

    def key(self, value: str, leading_comma: bool) -> None:
        data = self.key_data.get(value)
        if data is None:
            data = value.encode("utf-8", "surrogatepass")
            if len(self.key_data) < 1024:
                self.key_data[value] = data
        start = len(self.blob)
        self.blob.extend(data)
        self.kinds.append(4 if leading_comma else 3)
        self.starts.append(start)
        self.ends.append(len(self.blob))


def _float_text(value: float, allow_nan: bool) -> str:
    if not math.isfinite(value):
        if not allow_nan:
            raise OverflowError("Invalid value when encoding double")
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    text = repr(value)
    if "e" in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}e{int(exponent):+d}"
    return text


def _key_text(key: Any) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, bytes):
        return key.decode("utf-8")
    if key is None:
        return "null"
    if key is True:
        return "true"
    if key is False:
        return "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, float):
        return _float_text(key, True)
    raise TypeError(f"{key!r} is not JSON serializable")


def dumps(
    obj: Any,
    ensure_ascii: bool = True,
    encode_html_chars: bool = False,
    escape_forward_slashes: bool = True,
    sort_keys: bool = False,
    indent: int = 0,
    allow_nan: bool = True,
    reject_bytes: bool = True,
    default: Any = None,
) -> str:
    indent_width = operator.index(indent)
    writer = _TokenWriter()
    active: set[int] = set()

    def newline(depth: int) -> None:
        writer.raw("\n" + " " * (indent_width * depth))

    def write(value: Any, depth: int) -> None:
        if value is None:
            writer.raw("null")
        elif value is True:
            writer.raw("true")
        elif value is False:
            writer.raw("false")
        elif isinstance(value, str):
            writer.string(value)
        elif isinstance(value, bytes):
            if reject_bytes:
                text = value.decode(errors="replace")
                raise TypeError(f"reject_bytes is on and {text!r} is bytes")
            writer.string(value.decode("utf-8"))
        elif isinstance(value, int):
            writer.raw(str(value))
        elif isinstance(value, float):
            writer.raw(_float_text(value, bool(allow_nan)))
        elif isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in active:
                raise OverflowError("Maximum recursion level reached")
            active.add(identity)
            if indent_width == 0 and value:
                first_type = type(value[0])
                if first_type is float and all(type(item) is float for item in value):
                    body = ",".join(map(repr, value))
                    if "e" in body or "nan" in body or "inf" in body:
                        body = ",".join(
                            _float_text(item, bool(allow_nan)) for item in value
                        )
                    writer.raw("[" + body + "]")
                    active.remove(identity)
                    return
                if first_type is str and all(type(item) is str for item in value):
                    writer.raw("[")
                    writer.string(value[0])
                    for index in range(1, len(value)):
                        writer.string(value[index], 2)
                    writer.raw("]")
                    active.remove(identity)
                    return
            writer.raw("[")
            for index, item in enumerate(value):
                if index:
                    writer.raw(",")
                if indent_width > 0:
                    newline(depth + 1)
                item_type = type(item)
                if item is None:
                    writer.raw("null")
                elif item is True:
                    writer.raw("true")
                elif item is False:
                    writer.raw("false")
                elif item_type is str:
                    writer.string(item)
                elif item_type is int:
                    writer.raw(str(item))
                elif item_type is float:
                    writer.raw(_float_text(item, bool(allow_nan)))
                else:
                    write(item, depth + 1)
            if value and indent_width > 0:
                newline(depth)
            writer.raw("]")
            active.remove(identity)
        elif isinstance(value, dict):
            identity = id(value)
            if identity in active:
                raise OverflowError("Maximum recursion level reached")
            active.add(identity)
            items = sorted(value.items()) if sort_keys else value.items()
            writer.raw("{")
            for index, (key, item) in enumerate(items):
                if index and indent_width != 0:
                    writer.raw(",")
                if indent_width > 0:
                    newline(depth + 1)
                key_value = key if isinstance(key, str) else _key_text(key)
                if indent_width == 0:
                    writer.key(key_value, index != 0)
                else:
                    writer.string(key_value)
                    writer.raw(": ")
                item_type = type(item)
                if item is None:
                    writer.raw("null")
                elif item is True:
                    writer.raw("true")
                elif item is False:
                    writer.raw("false")
                elif item_type is str:
                    writer.string(item)
                elif item_type is int:
                    writer.raw(str(item))
                elif item_type is float:
                    writer.raw(_float_text(item, bool(allow_nan)))
                else:
                    write(item, depth + 1)
            if value and indent_width > 0:
                newline(depth)
            writer.raw("}")
            active.remove(identity)
        elif default is not None:
            write(default(value), depth)
        else:
            raise TypeError(f"{value!r} is not JSON serializable")

    write(obj, 0)
    blob = np.frombuffer(writer.blob, dtype=np.uint8)
    if not len(blob):
        blob = np.zeros(1, dtype=np.uint8)
    kinds = np.asarray(writer.kinds, dtype=np.uint8)
    starts = np.asarray(writer.starts, dtype=np.int64)
    ends = np.asarray(writer.ends, dtype=np.int64)
    # Six bytes cover the worst escape of each input byte.  A token can add a
    # comma, two quotes, and a colon even when its string span is empty.
    # The kernel reserves up to 12 bytes before processing each source byte.
    capacity = max(1, 6 * len(writer.blob) + 4 * len(kinds) + 12)
    output = np.empty(capacity, dtype=np.uint8)
    size = lib().mujson_encode(
        _addr(kinds, np.dtype(np.uint8)),
        _addr(starts, np.dtype(np.int64)),
        _addr(ends, np.dtype(np.int64)),
        len(kinds),
        _addr(blob, np.dtype(np.uint8)),
        _addr(output, np.dtype(np.uint8)),
        capacity,
        int(bool(ensure_ascii)),
        int(bool(escape_forward_slashes)),
        int(bool(encode_html_chars)),
    )
    if size == -2:
        raise UnicodeEncodeError("utf-8", "", 0, 1, "invalid UTF-8")
    if size < 0:
        raise MemoryError("JSON output buffer was too small")
    return bytes(output[:size]).decode("utf-8", "surrogatepass")


encode = dumps


def dump(obj: Any, fp: Any, *args: Any, **kwargs: Any) -> None:
    fp.write(dumps(obj, *args, **kwargs))


def load(fp: Any, *args: Any, **kwargs: Any) -> Any:
    if args or kwargs:
        return loads(fp.read(), *args, **kwargs)
    return loads(fp.read())


__all__ = [
    "JSONDecodeError",
    "decode",
    "dump",
    "dumps",
    "encode",
    "load",
    "loads",
]
