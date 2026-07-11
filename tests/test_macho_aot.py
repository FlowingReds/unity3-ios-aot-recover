from __future__ import annotations

import struct
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aot_recover.macho import parse_macho
from aot_recover.mono_aot import build_method_map, parse_aot_modules
from aot_recover.cli import RecoveryError, _verify_binary_override


def uleb(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            return bytes(result)


def make_fixture(crypt_id: int = 0, uuid: bytes = bytes(range(16))) -> bytes:
    data = bytearray(0x2000)
    commands = []

    def segment(name: bytes, vm: int, vm_size: int, file_offset: int, file_size: int, protection: int) -> bytes:
        return struct.pack(
            "<II16sIIIIiiII",
            1,
            56,
            name.ljust(16, b"\0"),
            vm,
            vm_size,
            file_offset,
            file_size,
            protection,
            protection,
            0,
            0,
        )

    commands.append(segment(b"__TEXT", 0x1000, 0x2000, 0, 0x1000, 5))
    commands.append(segment(b"__DATA", 0x3000, 0x2000, 0x1000, 0x1000, 3))
    commands.append(struct.pack("<IIIIII", 2, 24, 0x1E00, 1, 0x1E0C, 128))
    commands.append(struct.pack("<IIII", 0x26, 16, 0x1F00, 16))
    commands.append(struct.pack("<IIIII", 0x21, 20, 0x400, 0x100, crypt_id))
    commands.append(struct.pack("<II16s", 0x1B, 24, uuid))
    command_blob = b"".join(commands)
    struct.pack_into("<IiiIIII", data, 0, 0xFEEDFACE, 12, 9, 2, len(commands), len(command_blob), 0)
    data[28 : 28 + len(command_blob)] = command_blob

    strings = b"\0_mono_aot_module_Assembly_CSharp_info\0"
    data[0x1E0C : 0x1E0C + len(strings)] = strings
    struct.pack_into("<IBBHI", data, 0x1E00, 1, 0x0F, 2, 0, 0x3100)

    def put_vm(address: int, value: bytes) -> None:
        if address < 0x3000:
            offset = address - 0x1000
        else:
            offset = 0x1000 + address - 0x3000
        data[offset : offset + len(value)] = value

    names = {
        "mono_aot_file_info": 0x1400,
        "method_addresses": 0x1420,
        "methods": 0x1440,
        "methods_end": 0x1450,
    }
    for name, address in names.items():
        put_vm(address, name.encode() + b"\0")
    put_vm(0x3100, struct.pack("<I", 0x3200))
    pairs = [
        (names["mono_aot_file_info"], 0x3300),
        (names["method_addresses"], 0x3400),
        (names["methods"], 0x1500),
        (names["methods_end"], 0x1600),
    ]
    globals_blob = bytearray(struct.pack("<I", 0x1200))
    for name_address, value_address in pairs:
        globals_blob += struct.pack("<II", name_address, value_address)
    globals_blob += struct.pack("<II", 0, 0)
    put_vm(0x3200, globals_blob)
    file_info = [1, 64, 4, 3] + [0] * 9
    put_vm(0x3300, struct.pack("<13I", *file_info))
    put_vm(0x3400, struct.pack("<3I", 0x1501, 0x1521, 0))
    starts = uleb(0x500) + uleb(0x20) + uleb(0x20) + b"\0"
    data[0x1F00 : 0x1F00 + len(starts)] = starts
    return bytes(data)


class MachOAotTests(unittest.TestCase):
    def test_parses_legacy_module_and_maps_method_tokens(self) -> None:
        image = parse_macho(make_fixture())[0]
        self.assertEqual("armv7", image.architecture)
        self.assertEqual("00010203-0405-0607-0809-0a0b0c0d0e0f", image.uuid)
        self.assertFalse(image.encrypted)
        self.assertEqual([0x1500, 0x1520, 0x1540], image.function_starts)
        modules = parse_aot_modules(image)
        self.assertEqual(1, len(modules))
        module = modules[0]
        self.assertEqual("Assembly_CSharp", module.module_name)
        self.assertEqual(3, module.nmethods)
        self.assertEqual(4, len(module.entries))
        metadata = [
            {"token": "0x06000001", "rid": 1, "declaringType": "A", "name": "One", "fullName": "A::One()", "returnType": "System.Void"},
            {"token": "0x06000002", "rid": 2, "declaringType": "A", "name": "Two", "fullName": "A::Two()", "returnType": "System.Void"},
            {"token": "0x06000003", "rid": 3, "declaringType": "A", "name": "Three", "fullName": "A::Three()", "returnType": "System.Void"},
        ]
        methods, error = build_method_map(image, module, metadata)
        self.assertIsNone(error)
        self.assertEqual(2, len(methods))
        self.assertEqual(0x1500, methods[0]["address"])
        self.assertTrue(methods[0]["thumb"])
        self.assertEqual(0x20, methods[0]["estimated_size"])

    def test_reports_encryption_command(self) -> None:
        image = parse_macho(make_fixture(crypt_id=1))[0]
        self.assertTrue(image.encrypted)
        self.assertTrue(image.is_offset_encrypted(0x450))
        self.assertFalse(image.is_offset_encrypted(0x350))

    def test_verifies_decrypted_override_build_identity(self) -> None:
        verification = _verify_binary_override(make_fixture(crypt_id=1), make_fixture(crypt_id=0))
        self.assertTrue(verification["verified"])
        self.assertEqual("mach-o-build-identity", verification["method"])

    def test_rejects_decrypted_override_with_different_uuid(self) -> None:
        with self.assertRaisesRegex(RecoveryError, "UUID mismatch"):
            _verify_binary_override(make_fixture(), make_fixture(uuid=b"\xff" * 16))


if __name__ == "__main__":
    unittest.main()
