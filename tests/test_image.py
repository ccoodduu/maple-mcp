"""Tests for image encode/decode (Wheeler compression + Base64)."""
import pytest


class TestImageCodec:
    """Wheeler compression round-trip."""

    def test_small_png_round_trip(self):
        """Create a tiny PNG and round-trip through Wheeler codec."""
        from maple_mcp.image_decode import encode_maple_image, decode_maple_image

        # Minimal 1x1 red PNG
        import struct, zlib
        def make_png(r, g, b):
            raw = b'\x00' + bytes([r, g, b])
            compressed = zlib.compress(raw)
            chunks = b''
            for ctype, data in [
                (b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)),
                (b'IDAT', compressed),
                (b'IEND', b''),
            ]:
                chunk = ctype + data
                crc = struct.pack('>I', zlib.crc32(chunk) & 0xffffffff)
                chunks += struct.pack('>I', len(data)) + chunk + crc
            return b'\x89PNG\r\n\x1a\n' + chunks

        original = make_png(255, 0, 0)
        encoded = encode_maple_image(original)
        assert encoded  # Should produce non-empty string
        assert len(encoded) > 10

        decoded = decode_maple_image(encoded)
        assert decoded[:4] == b'\x89PNG'  # Valid PNG header
        assert len(decoded) > 0

    def test_encode_returns_string(self):
        from maple_mcp.image_decode import encode_maple_image
        import struct, zlib
        raw = b'\x00\xff\xff\xff'
        compressed = zlib.compress(raw)
        ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = struct.pack('>I', zlib.crc32(b'IHDR' + ihdr) & 0xffffffff)
        idat = compressed
        idat_crc = struct.pack('>I', zlib.crc32(b'IDAT' + idat) & 0xffffffff)
        iend_crc = struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
        png = (b'\x89PNG\r\n\x1a\n'
               + struct.pack('>I', len(ihdr)) + b'IHDR' + ihdr + ihdr_crc
               + struct.pack('>I', len(idat)) + b'IDAT' + idat + idat_crc
               + struct.pack('>I', 0) + b'IEND' + iend_crc)
        result = encode_maple_image(png)
        assert isinstance(result, str)


class TestImageRead:
    """read_document must surface Image elements as image entries."""

    def _mw_with_image(self, tmp_path, extra_text):
        """Build a .mw whose PB holds a Text-field with an Image (+ optional text),
        mirroring the real structure: PB > Group > Input > Text-field > Image."""
        from maple_mcp.image_decode import encode_maple_image

        encoded = encode_maple_image(b'\x89PNG\r\n\x1a\nfake-png-payload')
        content = f'''<?xml version="1.0" encoding="UTF-8"?>
<Worksheet>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L1" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">{extra_text}<Image height="10" width="10" zoomable="false">{encoded}</Image></Text-field></Input>
</Group></Presentation-Block>
</Worksheet>'''
        p = tmp_path / "img.mw"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_image_alongside_text_survives(self, tmp_path):
        """An image sharing its block with text must not be dropped by the
        multi-entry merge (regression: the merge collapsed the PB to one text
        entry and discarded the image's encoded data)."""
        from maple_mcp.document import read_document

        entries = read_document(self._mw_with_image(tmp_path, "Caption text."))
        images = [e for e in entries if e.get("type") == "image"]
        assert len(images) == 1
        assert images[0].get("encoded")
        texts = [e for e in entries if e.get("type") == "text"]
        assert any("Caption text." in e.get("content", "") for e in texts)

    def test_solo_image_survives(self, tmp_path):
        from maple_mcp.document import read_document

        entries = read_document(self._mw_with_image(tmp_path, ""))
        images = [e for e in entries if e.get("type") == "image"]
        assert len(images) == 1
        assert images[0].get("encoded")
