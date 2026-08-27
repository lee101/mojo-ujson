"""JSON scanning, string decoding, and string encoding kernels."""

from std.sys import simd_width_of as simdwidthof

comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int, AnyOrigin[mut=True]]

comptime K_NULL = 1
comptime K_FALSE = 2
comptime K_TRUE = 3
comptime K_INT = 4
comptime K_FLOAT = 5
comptime K_STRING = 6
comptime K_KEY = 7
comptime K_ARRAY_START = 8
comptime K_ARRAY_END = 9
comptime K_OBJECT_START = 10
comptime K_OBJECT_END = 11


def hex_value(c: UInt8) -> Int:
    var v = Int(c)
    if v >= 48 and v <= 57:
        return v - 48
    if v >= 65 and v <= 70:
        return v - 55
    if v >= 97 and v <= 102:
        return v - 87
    return -1


def put_utf8(cp: Int, dst: BPtr, pos: Int) -> Int:
    var p = pos
    if cp <= 0x7F:
        dst[p] = UInt8(cp)
        return p + 1
    if cp <= 0x7FF:
        dst[p] = UInt8(0xC0 | (cp >> 6))
        dst[p + 1] = UInt8(0x80 | (cp & 0x3F))
        return p + 2
    if cp <= 0xFFFF:
        dst[p] = UInt8(0xE0 | (cp >> 12))
        dst[p + 1] = UInt8(0x80 | ((cp >> 6) & 0x3F))
        dst[p + 2] = UInt8(0x80 | (cp & 0x3F))
        return p + 3
    dst[p] = UInt8(0xF0 | (cp >> 18))
    dst[p + 1] = UInt8(0x80 | ((cp >> 12) & 0x3F))
    dst[p + 2] = UInt8(0x80 | ((cp >> 6) & 0x3F))
    dst[p + 3] = UInt8(0x80 | (cp & 0x3F))
    return p + 4


def set_error(errors: IPtr, code: Int, pos: Int) -> Int:
    errors[0] = code
    errors[1] = pos
    return -code


def copy_bytes(src: BPtr, src_start: Int, dst: BPtr, dst_start: Int, count: Int):
    comptime W = simdwidthof[DType.float64]()
    comptime BYTE_W = W * 8
    var offset = 0
    while offset + BYTE_W <= count:
        var values = src.load[width=BYTE_W](src_start + offset)
        dst.store(dst_start + offset, values)
        offset += BYTE_W
    while offset < count:
        dst[dst_start + offset] = src[src_start + offset]
        offset += 1


@export("mujson_parse")
def mujson_parse(
    src_addr: Int,
    n: Int,
    kinds_addr: Int,
    starts_addr: Int,
    ends_addr: Int,
    strings_addr: Int,
    stack_type_addr: Int,
    stack_state_addr: Int,
    errors_addr: Int,
) abi("C") -> Int:
    var src = BPtr(unsafe_from_address=src_addr)
    var kinds = BPtr(unsafe_from_address=kinds_addr)
    var starts = IPtr(unsafe_from_address=starts_addr)
    var ends = IPtr(unsafe_from_address=ends_addr)
    var strings = BPtr(unsafe_from_address=strings_addr)
    var stack_type = BPtr(unsafe_from_address=stack_type_addr)
    var stack_state = BPtr(unsafe_from_address=stack_state_addr)
    var errors = IPtr(unsafe_from_address=errors_addr)

    var i = 0
    var event_count = 0
    var string_pos = 0
    var depth = 0
    stack_type[0] = UInt8(0)
    stack_state[0] = UInt8(0)

    while True:
        while i < n and (
            src[i] == UInt8(32) or src[i] == UInt8(9)
            or src[i] == UInt8(10) or src[i] == UInt8(13)
        ):
            i += 1

        var typ = Int(stack_type[depth])
        var state = Int(stack_state[depth])

        if typ == 0 and state == 1:
            if i == n:
                errors[0] = 0
                errors[1] = i
                errors[2] = string_pos
                return event_count
            return set_error(errors, 2, i)
        if i >= n:
            return set_error(errors, 1, i)

        var is_key = False
        if typ == 1:
            if state == 1:
                if src[i] == UInt8(44):
                    stack_state[depth] = UInt8(2)
                    i += 1
                    continue
                if src[i] == UInt8(93):
                    kinds[event_count] = UInt8(K_ARRAY_END)
                    starts[event_count] = i
                    ends[event_count] = i + 1
                    event_count += 1
                    i += 1
                    depth -= 1
                    typ = Int(stack_type[depth])
                    if typ == 0:
                        stack_state[depth] = UInt8(1)
                    elif typ == 1:
                        stack_state[depth] = UInt8(1)
                    else:
                        stack_state[depth] = UInt8(3)
                    continue
                return set_error(errors, 3, i)
            if state == 0 and src[i] == UInt8(93):
                kinds[event_count] = UInt8(K_ARRAY_END)
                starts[event_count] = i
                ends[event_count] = i + 1
                event_count += 1
                i += 1
                depth -= 1
                typ = Int(stack_type[depth])
                if typ == 0:
                    stack_state[depth] = UInt8(1)
                elif typ == 1:
                    stack_state[depth] = UInt8(1)
                else:
                    stack_state[depth] = UInt8(3)
                continue
        elif typ == 2:
            if state == 1:
                if src[i] != UInt8(58):
                    return set_error(errors, 4, i)
                stack_state[depth] = UInt8(2)
                i += 1
                continue
            if state == 3:
                if src[i] == UInt8(44):
                    stack_state[depth] = UInt8(4)
                    i += 1
                    continue
                if src[i] == UInt8(125):
                    kinds[event_count] = UInt8(K_OBJECT_END)
                    starts[event_count] = i
                    ends[event_count] = i + 1
                    event_count += 1
                    i += 1
                    depth -= 1
                    typ = Int(stack_type[depth])
                    if typ == 0:
                        stack_state[depth] = UInt8(1)
                    elif typ == 1:
                        stack_state[depth] = UInt8(1)
                    else:
                        stack_state[depth] = UInt8(3)
                    continue
                return set_error(errors, 3, i)
            if state == 0 and src[i] == UInt8(125):
                kinds[event_count] = UInt8(K_OBJECT_END)
                starts[event_count] = i
                ends[event_count] = i + 1
                event_count += 1
                i += 1
                depth -= 1
                typ = Int(stack_type[depth])
                if typ == 0:
                    stack_state[depth] = UInt8(1)
                elif typ == 1:
                    stack_state[depth] = UInt8(1)
                else:
                    stack_state[depth] = UInt8(3)
                continue
            if state == 0 or state == 4:
                if src[i] != UInt8(34):
                    return set_error(errors, 5, i)
                is_key = True

        var c = src[i]
        if c == UInt8(34):
            var decoded_start = string_pos
            i += 1
            var closed = False
            comptime W = simdwidthof[DType.float64]()
            comptime BYTE_W = W * 8
            while i < n:
                while i + BYTE_W <= n:
                    var values = src.load[width=BYTE_W](i)
                    var special = (
                        values.eq(UInt8(34))
                        | values.eq(UInt8(92))
                        | values.eq(UInt8(0))
                    )
                    if Int(special.cast[DType.uint8]().reduce_add()) != 0:
                        break
                    strings.store(string_pos, values)
                    i += BYTE_W
                    string_pos += BYTE_W
                if i >= n:
                    break
                c = src[i]
                i += 1
                if c == UInt8(34):
                    closed = True
                    break
                if c != UInt8(92):
                    if c == UInt8(0):
                        return set_error(errors, 6, i - 1)
                    strings[string_pos] = c
                    string_pos += 1
                    continue
                if i >= n:
                    return set_error(errors, 6, i)
                c = src[i]
                i += 1
                if c == UInt8(34) or c == UInt8(92) or c == UInt8(47):
                    strings[string_pos] = c
                    string_pos += 1
                elif c == UInt8(98):
                    strings[string_pos] = UInt8(8)
                    string_pos += 1
                elif c == UInt8(102):
                    strings[string_pos] = UInt8(12)
                    string_pos += 1
                elif c == UInt8(110):
                    strings[string_pos] = UInt8(10)
                    string_pos += 1
                elif c == UInt8(114):
                    strings[string_pos] = UInt8(13)
                    string_pos += 1
                elif c == UInt8(116):
                    strings[string_pos] = UInt8(9)
                    string_pos += 1
                elif c == UInt8(117):
                    if i + 4 > n:
                        return set_error(errors, 7, i)
                    var cp = 0
                    for _ in range(4):
                        var h = hex_value(src[i])
                        if h < 0:
                            return set_error(errors, 7, i)
                        cp = (cp << 4) | h
                        i += 1
                    if cp >= 0xD800 and cp <= 0xDBFF and i + 6 <= n:
                        if src[i] == UInt8(92) and src[i + 1] == UInt8(117):
                            var low = 0
                            var valid_low = True
                            for j in range(4):
                                var h = hex_value(src[i + 2 + j])
                                if h < 0:
                                    valid_low = False
                                else:
                                    low = (low << 4) | h
                            if valid_low and low >= 0xDC00 and low <= 0xDFFF:
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00)
                                i += 6
                    string_pos = put_utf8(cp, strings, string_pos)
                else:
                    return set_error(errors, 8, i - 1)
            if not closed:
                return set_error(errors, 6, i)
            kinds[event_count] = UInt8(K_KEY if is_key else K_STRING)
            starts[event_count] = decoded_start
            ends[event_count] = string_pos
            event_count += 1
            if is_key:
                stack_state[depth] = UInt8(1)
            elif typ == 0:
                stack_state[depth] = UInt8(1)
            elif typ == 1:
                stack_state[depth] = UInt8(1)
            else:
                stack_state[depth] = UInt8(3)
            continue

        if is_key:
            return set_error(errors, 5, i)

        if c == UInt8(91):
            kinds[event_count] = UInt8(K_ARRAY_START)
            starts[event_count] = i
            ends[event_count] = i + 1
            event_count += 1
            i += 1
            depth += 1
            stack_type[depth] = UInt8(1)
            stack_state[depth] = UInt8(0)
            continue
        if c == UInt8(123):
            kinds[event_count] = UInt8(K_OBJECT_START)
            starts[event_count] = i
            ends[event_count] = i + 1
            event_count += 1
            i += 1
            depth += 1
            stack_type[depth] = UInt8(2)
            stack_state[depth] = UInt8(0)
            continue

        var token_kind = 0
        var token_start = i
        if i + 4 <= n and src[i] == UInt8(110) and src[i + 1] == UInt8(117) and src[i + 2] == UInt8(108) and src[i + 3] == UInt8(108):
            token_kind = K_NULL
            i += 4
        elif i + 4 <= n and src[i] == UInt8(116) and src[i + 1] == UInt8(114) and src[i + 2] == UInt8(117) and src[i + 3] == UInt8(101):
            token_kind = K_TRUE
            i += 4
        elif i + 5 <= n and src[i] == UInt8(102) and src[i + 1] == UInt8(97) and src[i + 2] == UInt8(108) and src[i + 3] == UInt8(115) and src[i + 4] == UInt8(101):
            token_kind = K_FALSE
            i += 5
        elif i + 3 <= n and src[i] == UInt8(78) and src[i + 1] == UInt8(97) and src[i + 2] == UInt8(78):
            token_kind = K_FLOAT
            i += 3
        elif i + 8 <= n and src[i] == UInt8(73) and src[i + 1] == UInt8(110) and src[i + 2] == UInt8(102) and src[i + 3] == UInt8(105) and src[i + 4] == UInt8(110) and src[i + 5] == UInt8(105) and src[i + 6] == UInt8(116) and src[i + 7] == UInt8(121):
            token_kind = K_FLOAT
            i += 8
        elif i + 9 <= n and src[i] == UInt8(45) and src[i + 1] == UInt8(73) and src[i + 2] == UInt8(110) and src[i + 3] == UInt8(102) and src[i + 4] == UInt8(105) and src[i + 5] == UInt8(110) and src[i + 6] == UInt8(105) and src[i + 7] == UInt8(116) and src[i + 8] == UInt8(121):
            token_kind = K_FLOAT
            i += 9
        elif (c >= UInt8(48) and c <= UInt8(57)) or c == UInt8(45):
            token_kind = K_INT
            if c == UInt8(45):
                i += 1
                if i >= n or src[i] < UInt8(48) or src[i] > UInt8(57):
                    return set_error(errors, 9, i)
            while i < n and src[i] >= UInt8(48) and src[i] <= UInt8(57):
                i += 1
            if i < n and src[i] == UInt8(46):
                token_kind = K_FLOAT
                i += 1
                while i < n and src[i] >= UInt8(48) and src[i] <= UInt8(57):
                    i += 1
            if i < n and (src[i] == UInt8(101) or src[i] == UInt8(69)):
                token_kind = K_FLOAT
                i += 1
                if i < n and (src[i] == UInt8(43) or src[i] == UInt8(45)):
                    i += 1
                var exp_start = i
                while i < n and src[i] >= UInt8(48) and src[i] <= UInt8(57):
                    i += 1
                if i == exp_start:
                    return set_error(errors, 9, i)
        else:
            return set_error(errors, 10, i)

        kinds[event_count] = UInt8(token_kind)
        starts[event_count] = token_start
        ends[event_count] = i
        event_count += 1
        if typ == 0:
            stack_state[depth] = UInt8(1)
        elif typ == 1:
            stack_state[depth] = UInt8(1)
        else:
            stack_state[depth] = UInt8(3)


def write_hex_escape(dst: BPtr, pos: Int, cp: Int) -> Int:
    var p = pos
    dst[p] = UInt8(92)
    dst[p + 1] = UInt8(117)
    for shift in range(3, -1, -1):
        var h = (cp >> (shift * 4)) & 15
        dst[p + 5 - shift] = UInt8(h + (48 if h < 10 else 87))
    return p + 6


@export("mujson_encode")
def mujson_encode(
    kinds_addr: Int,
    starts_addr: Int,
    ends_addr: Int,
    count: Int,
    blob_addr: Int,
    dst_addr: Int,
    capacity: Int,
    ensure_ascii: Int,
    escape_slashes: Int,
    encode_html: Int,
) abi("C") -> Int:
    var kinds = BPtr(unsafe_from_address=kinds_addr)
    var starts = IPtr(unsafe_from_address=starts_addr)
    var ends = IPtr(unsafe_from_address=ends_addr)
    var blob = BPtr(unsafe_from_address=blob_addr)
    var dst = BPtr(unsafe_from_address=dst_addr)
    var pos = 0

    for token in range(count):
        var start = Int(starts[token])
        var end = Int(ends[token])
        var kind = Int(kinds[token])
        if kind == 0:
            if pos + end - start > capacity:
                return -1
            var count_bytes = end - start
            copy_bytes(blob, start, dst, pos, count_bytes)
            pos += count_bytes
            continue

        var overhead = 2
        if kind >= 2:
            overhead += 1
        if pos + overhead > capacity:
            return -1
        if kind == 2 or kind == 4:
            dst[pos] = UInt8(44)
            pos += 1
        dst[pos] = UInt8(34)
        pos += 1
        var i = start
        comptime W = simdwidthof[DType.float64]()
        comptime BYTE_W = W * 8
        while i < end:
            while i + BYTE_W <= end and pos + BYTE_W <= capacity:
                var values = blob.load[width=BYTE_W](i)
                var special = (
                    values.lt(SIMD[DType.uint8, BYTE_W](32))
                    | values.eq(SIMD[DType.uint8, BYTE_W](34))
                    | values.eq(SIMD[DType.uint8, BYTE_W](92))
                )
                if escape_slashes != 0:
                    special = special | values.eq(SIMD[DType.uint8, BYTE_W](47))
                if encode_html != 0:
                    special = (
                        special
                        | values.eq(SIMD[DType.uint8, BYTE_W](60))
                        | values.eq(SIMD[DType.uint8, BYTE_W](62))
                        | values.eq(SIMD[DType.uint8, BYTE_W](38))
                    )
                if ensure_ascii != 0:
                    special = special | ~values.lt(SIMD[DType.uint8, BYTE_W](128))
                if special.reduce_or():
                    var clean = 0
                    while clean < BYTE_W and not special[clean]:
                        dst[pos + clean] = blob[i + clean]
                        clean += 1
                    i += clean
                    pos += clean
                    break
                dst.store(pos, values)
                i += BYTE_W
                pos += BYTE_W
            if i >= end:
                break
            if pos + 12 > capacity:
                return -1
            var c = Int(blob[i])
            i += 1
            if c == 34 or c == 92:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(c)
                pos += 2
            elif c == 47 and escape_slashes != 0:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(47)
                pos += 2
            elif c == 8:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(98)
                pos += 2
            elif c == 9:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(116)
                pos += 2
            elif c == 10:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(110)
                pos += 2
            elif c == 12:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(102)
                pos += 2
            elif c == 13:
                dst[pos] = UInt8(92)
                dst[pos + 1] = UInt8(114)
                pos += 2
            elif c < 32 or (encode_html != 0 and (c == 60 or c == 62 or c == 38)):
                pos = write_hex_escape(dst, pos, c)
            elif c < 128:
                dst[pos] = UInt8(c)
                pos += 1
            elif ensure_ascii == 0:
                dst[pos] = UInt8(c)
                pos += 1
                while i < end and (Int(blob[i]) & 0xC0) == 0x80:
                    dst[pos] = blob[i]
                    pos += 1
                    i += 1
            else:
                var cp: Int
                var needed: Int
                if (c & 0xE0) == 0xC0:
                    cp = c & 0x1F
                    needed = 1
                elif (c & 0xF0) == 0xE0:
                    cp = c & 0x0F
                    needed = 2
                elif (c & 0xF8) == 0xF0:
                    cp = c & 0x07
                    needed = 3
                else:
                    return -2
                if i + needed > end:
                    return -2
                for _ in range(needed):
                    var tail = Int(blob[i])
                    if (tail & 0xC0) != 0x80:
                        return -2
                    cp = (cp << 6) | (tail & 0x3F)
                    i += 1
                if cp <= 0xFFFF:
                    pos = write_hex_escape(dst, pos, cp)
                else:
                    cp -= 0x10000
                    pos = write_hex_escape(dst, pos, 0xD800 | (cp >> 10))
                    pos = write_hex_escape(dst, pos, 0xDC00 | (cp & 0x3FF))
        dst[pos] = UInt8(34)
        pos += 1
        if kind == 3 or kind == 4:
            dst[pos] = UInt8(58)
            pos += 1
    return pos
