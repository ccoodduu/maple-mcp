import base64


def _sling_hash(x: int, hash_val: int) -> int:
    return ((hash_val << 4) + x) & 0xFFF


# --- DECODE (Maple .mw → PNG bytes) ---

def decode_maple_image(encoded: str) -> bytes:
    raw = base64.b64decode(encoded).decode("latin-1")
    return _wheeler_decompress(raw)


def _wheeler_decompress(data: str) -> bytes:
    output = bytearray()
    table = [0] * 4096
    hash_val = 0
    bit = 6
    wholeByte = 0
    byte1 = 0
    c = 0
    bitCount = -1

    stream = _WheelerInStream(data)

    while bitCount != 0:
        if bit == 6:
            ok, ch = stream.input_char()
            if not ok:
                break
            c = ch
            if 48 <= c < 58:
                bitCount = c - 48 + 1
                continue
            bit = 0
            c -= 58

        if wholeByte > 0:
            byte1 |= (c & 1) << (8 - wholeByte)
            wholeByte -= 1
            if wholeByte == 0:
                output.append(byte1 & 0xFF)
                table[hash_val] = byte1
                hash_val = _sling_hash(byte1, hash_val)
        elif (c & 1) > 0:
            byte1 = 0
            wholeByte = 8
        else:
            byte1 = table[hash_val]
            output.append(byte1 & 0xFF)
            hash_val = _sling_hash(byte1, hash_val)

        c >>= 1
        bit += 1
        bitCount -= 1

    return bytes(output)


class _WheelerInStream:
    def __init__(self, data: str):
        self._data = data
        self._index = 0

    def _getch(self) -> tuple[bool, int]:
        while True:
            if self._index >= len(self._data):
                return False, 0
            ch = ord(self._data[self._index])
            self._index += 1
            if ch == 10 or ch < 32 or ch > 126:
                continue
            return True, ch

    def input_char(self) -> tuple[bool, int]:
        while True:
            ok, ch = self._getch()
            if not ok:
                return False, 0

            if ch == ord('"'):
                return False, 0

            if ch == ord('\\'):
                ok, ch = self._getch()
                if not ok:
                    return False, 0

                if chr(ch).isdigit():
                    digits = chr(ch)
                    ok, ch2 = self._getch()
                    if not ok:
                        return False, 0
                    digits += chr(ch2)
                    ok, ch3 = self._getch()
                    if not ok:
                        return False, 0
                    digits += chr(ch3)
                    n = int(digits)
                    octal_str = oct(n)[2:]
                    val = int(octal_str)
                    if val == 13:
                        val = 10
                    return True, val

                if ch == ord('n'):
                    return True, 10

                if ch == ord('+'):
                    continue

                return True, ch

            return True, ch


# --- ENCODE (PNG bytes → Maple .mw format) ---

def encode_maple_image(data: bytes) -> str:
    wheeler = _wheeler_compress(data)
    slashified = _slashify(wheeler)
    return base64.b64encode(slashified.encode("latin-1")).decode("ascii")


def _output_char(ch: int, out: list):
    if 32 <= ch <= 126:
        out.append(chr(ch))
    else:
        out.append("\\" + oct(ch)[2:])


def _wheeler_compress(data: bytes) -> str:
    out = []
    table = [0] * 4096
    hash_val = 0
    bit = 1
    byte1 = 0

    for c in data:
        uc = c
        if table[hash_val] == uc:
            bit <<= 1
            if bit == 64:
                _output_char(byte1 + 58, out)
                bit = 1
                byte1 = 0
        else:
            table[hash_val] = uc
            byte1 |= bit
            bit <<= 1
            if bit == 64:
                _output_char(byte1 + 58, out)
                bit = 1
                byte1 = 0
            for _ in range(8):
                if uc & 1:
                    byte1 |= bit
                bit <<= 1
                if bit == 64:
                    _output_char(byte1 + 58, out)
                    bit = 1
                    byte1 = 0
                uc >>= 1

        hash_val = _sling_hash(c, hash_val)

    bit_count = 0
    bit_shift = bit
    while bit_shift != 0:
        bit_count += 1
        bit_shift >>= 1

    _output_char(bit_count + 48, out)
    if bit != 0:
        _output_char(byte1 + 58, out)

    return "".join(out)


def _slashify(content: str) -> str:
    out = []
    for ch in content:
        if ch in ('"', '{', '}', '\\'):
            out.append('\\')
        out.append(ch)
    out.append('\\')
    out.append('"')
    out.append('\\')
    out.append('{')
    out.append('\\')
    out.append('}')
    return "".join(out)
