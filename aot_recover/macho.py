from __future__ import annotations

from dataclasses import asdict, dataclass, field
import struct
from typing import Iterable


FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
MH_MAGIC = 0xFEEDFACE
MH_MAGIC_64 = 0xFEEDFACF

LC_SEGMENT = 0x1
LC_SYMTAB = 0x2
LC_SEGMENT_64 = 0x19
LC_ENCRYPTION_INFO = 0x21
LC_FUNCTION_STARTS = 0x26
LC_ENCRYPTION_INFO_64 = 0x2C

CPU_TYPE_ARM = 12
CPU_TYPE_ARM64 = 0x0100000C


class MachOError(ValueError):
    pass


@dataclass(frozen=True)
class FatArch:
    cpu_type: int
    cpu_subtype: int
    offset: int
    size: int
    align: int


@dataclass(frozen=True)
class Section:
    segment: str
    name: str
    address: int
    size: int
    offset: int
    flags: int


@dataclass(frozen=True)
class Segment:
    name: str
    vm_address: int
    vm_size: int
    file_offset: int
    file_size: int
    max_protection: int
    initial_protection: int
    sections: tuple[Section, ...] = ()


@dataclass(frozen=True)
class EncryptionInfo:
    offset: int
    size: int
    crypt_id: int

    @property
    def enabled(self) -> bool:
        return self.crypt_id != 0 and self.size != 0


@dataclass(frozen=True)
class Symbol:
    name: str
    value: int
    type: int
    section: int
    description: int


@dataclass
class MachOSlice:
    data: bytes
    source_offset: int
    source_size: int
    cpu_type: int
    cpu_subtype: int
    is_64_bit: bool
    segments: list[Segment] = field(default_factory=list)
    encryption: list[EncryptionInfo] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    function_starts: list[int] = field(default_factory=list)
    uuid: str | None = None

    @property
    def architecture(self) -> str:
        subtype = self.cpu_subtype & 0x00FFFFFF
        if self.cpu_type == CPU_TYPE_ARM:
            return {
                5: "armv4t",
                6: "armv6",
                7: "armv5tej",
                8: "xscale",
                9: "armv7",
                10: "armv7f",
                11: "armv7s",
                12: "armv7k",
            }.get(subtype, f"arm-subtype-{subtype}")
        if self.cpu_type == CPU_TYPE_ARM64:
            return "arm64e" if subtype == 2 else "arm64"
        return f"cpu-{self.cpu_type}-subtype-{subtype}"

    @property
    def encrypted(self) -> bool:
        return any(item.enabled for item in self.encryption)

    def vm_to_offset(self, address: int, size: int = 1) -> int:
        for segment in self.segments:
            start = segment.vm_address
            end = start + segment.file_size
            if start <= address and address + size <= end:
                return segment.file_offset + (address - start)
        raise MachOError(f"VM address 0x{address:x} is not backed by file data")

    def offset_to_vm(self, offset: int) -> int:
        for segment in self.segments:
            start = segment.file_offset
            end = start + segment.file_size
            if start <= offset < end:
                return segment.vm_address + (offset - start)
        raise MachOError(f"file offset 0x{offset:x} is not mapped")

    def is_offset_encrypted(self, offset: int, size: int = 1) -> bool:
        for info in self.encryption:
            if not info.enabled:
                continue
            if offset < info.offset + info.size and offset + size > info.offset:
                return True
        return False

    def is_vm_encrypted(self, address: int, size: int = 1) -> bool:
        try:
            return self.is_offset_encrypted(self.vm_to_offset(address, size), size)
        except MachOError:
            return False

    def read(self, address: int, size: int) -> bytes:
        offset = self.vm_to_offset(address, size)
        return self.data[offset : offset + size]

    def read_u32(self, address: int) -> int:
        return struct.unpack_from("<I", self.data, self.vm_to_offset(address, 4))[0]

    def read_pointer(self, address: int) -> int:
        if self.is_64_bit:
            return struct.unpack_from("<Q", self.data, self.vm_to_offset(address, 8))[0]
        return self.read_u32(address)

    @property
    def pointer_size(self) -> int:
        return 8 if self.is_64_bit else 4

    def read_c_string(self, address: int, maximum: int = 512) -> str | None:
        try:
            offset = self.vm_to_offset(address)
        except MachOError:
            return None
        end = min(len(self.data), offset + maximum)
        nul = self.data.find(b"\0", offset, end)
        if nul < 0:
            return None
        raw = self.data[offset:nul]
        if not raw or any(byte < 0x20 or byte > 0x7E for byte in raw):
            return None
        try:
            return raw.decode("ascii")
        except UnicodeDecodeError:
            return None

    def find_symbol(self, name: str) -> Symbol | None:
        return next((symbol for symbol in self.symbols if symbol.name == name), None)

    def module_symbols(self) -> list[Symbol]:
        marker = "_mono_aot_module_"
        return [
            symbol
            for symbol in self.symbols
            if symbol.name.startswith(marker) and symbol.name.endswith("_info")
        ]

    def nearest_function_end(self, address: int, fallback: Iterable[int] = ()) -> int | None:
        candidates = set(self.function_starts)
        candidates.update(item for item in fallback if item)
        for candidate in sorted(candidates):
            if candidate > address:
                return candidate
        return None

    def to_manifest(self) -> dict:
        return {
            "architecture": self.architecture,
            "cpu_type": self.cpu_type,
            "cpu_subtype": self.cpu_subtype,
            "source_offset": self.source_offset,
            "source_size": self.source_size,
            "is_64_bit": self.is_64_bit,
            "encrypted": self.encrypted,
            "encryption": [asdict(item) for item in self.encryption],
            "segments": [
                {
                    **{key: value for key, value in asdict(segment).items() if key != "sections"},
                    "sections": [asdict(section) for section in segment.sections],
                }
                for segment in self.segments
            ],
            "function_start_count": len(self.function_starts),
            "symbol_count": len(self.symbols),
            "uuid": self.uuid,
        }


def _decode_uleb128(data: bytes, offset: int, end: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < end:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise MachOError("invalid ULEB128 value")
    raise MachOError("truncated ULEB128 value")


def _parse_thin(data: bytes, source_offset: int = 0, source_size: int | None = None) -> MachOSlice:
    if len(data) < 28:
        raise MachOError("truncated Mach-O header")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == MH_MAGIC:
        is_64_bit = False
        header_size = 28
        _, cpu_type, cpu_subtype, _, command_count, command_size, _ = struct.unpack_from(
            "<IiiIIII", data, 0
        )
    elif magic == MH_MAGIC_64:
        is_64_bit = True
        header_size = 32
        (
            _,
            cpu_type,
            cpu_subtype,
            _,
            command_count,
            command_size,
            _,
            _,
        ) = struct.unpack_from("<IiiIIIII", data, 0)
    else:
        raise MachOError(f"unsupported Mach-O magic 0x{magic:08x}")

    if header_size + command_size > len(data):
        raise MachOError("truncated Mach-O load commands")

    result = MachOSlice(
        data=data,
        source_offset=source_offset,
        source_size=source_size if source_size is not None else len(data),
        cpu_type=cpu_type,
        cpu_subtype=cpu_subtype,
        is_64_bit=is_64_bit,
    )
    symtab: tuple[int, int, int, int] | None = None
    function_data: tuple[int, int] | None = None
    command_offset = header_size

    for _ in range(command_count):
        if command_offset + 8 > len(data):
            raise MachOError("truncated load command")
        command, size = struct.unpack_from("<II", data, command_offset)
        if size < 8 or command_offset + size > len(data):
            raise MachOError(f"invalid load command size {size}")

        if command == LC_SEGMENT and not is_64_bit:
            raw_name = data[command_offset + 8 : command_offset + 24]
            name = raw_name.split(b"\0", 1)[0].decode("ascii", "replace")
            (
                vm_address,
                vm_size,
                file_offset,
                file_size,
                max_protection,
                initial_protection,
                section_count,
                _,
            ) = struct.unpack_from("<IIIIiiII", data, command_offset + 24)
            sections: list[Section] = []
            section_offset = command_offset + 56
            for _section in range(section_count):
                if section_offset + 68 > command_offset + size:
                    raise MachOError("truncated Mach-O section")
                section_name = data[section_offset : section_offset + 16].split(b"\0", 1)[0]
                segment_name = data[section_offset + 16 : section_offset + 32].split(b"\0", 1)[0]
                address, section_size, offset, _, _, _, flags, _, _ = struct.unpack_from(
                    "<IIIIIIIII", data, section_offset + 32
                )
                sections.append(
                    Section(
                        segment=segment_name.decode("ascii", "replace"),
                        name=section_name.decode("ascii", "replace"),
                        address=address,
                        size=section_size,
                        offset=offset,
                        flags=flags,
                    )
                )
                section_offset += 68
            result.segments.append(
                Segment(
                    name=name,
                    vm_address=vm_address,
                    vm_size=vm_size,
                    file_offset=file_offset,
                    file_size=file_size,
                    max_protection=max_protection,
                    initial_protection=initial_protection,
                    sections=tuple(sections),
                )
            )
        elif command == LC_SEGMENT_64 and is_64_bit:
            raw_name = data[command_offset + 8 : command_offset + 24]
            name = raw_name.split(b"\0", 1)[0].decode("ascii", "replace")
            (
                vm_address,
                vm_size,
                file_offset,
                file_size,
                max_protection,
                initial_protection,
                section_count,
                _,
            ) = struct.unpack_from("<QQQQiiII", data, command_offset + 24)
            sections = []
            section_offset = command_offset + 72
            for _section in range(section_count):
                if section_offset + 80 > command_offset + size:
                    raise MachOError("truncated Mach-O 64-bit section")
                section_name = data[section_offset : section_offset + 16].split(b"\0", 1)[0]
                segment_name = data[section_offset + 16 : section_offset + 32].split(b"\0", 1)[0]
                address, section_size, offset, _, _, _, flags, _, _, _ = struct.unpack_from(
                    "<QQIIIIIIII", data, section_offset + 32
                )
                sections.append(
                    Section(
                        segment=segment_name.decode("ascii", "replace"),
                        name=section_name.decode("ascii", "replace"),
                        address=address,
                        size=section_size,
                        offset=offset,
                        flags=flags,
                    )
                )
                section_offset += 80
            result.segments.append(
                Segment(
                    name=name,
                    vm_address=vm_address,
                    vm_size=vm_size,
                    file_offset=file_offset,
                    file_size=file_size,
                    max_protection=max_protection,
                    initial_protection=initial_protection,
                    sections=tuple(sections),
                )
            )
        elif command == LC_SYMTAB:
            symtab = struct.unpack_from("<IIII", data, command_offset + 8)
        elif command in (LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64):
            crypt_offset, crypt_size, crypt_id = struct.unpack_from("<III", data, command_offset + 8)
            result.encryption.append(EncryptionInfo(crypt_offset, crypt_size, crypt_id))
        elif command == LC_FUNCTION_STARTS:
            function_data = struct.unpack_from("<II", data, command_offset + 8)
        elif command == 0x1B and size >= 24:  # LC_UUID
            raw_uuid = data[command_offset + 8 : command_offset + 24]
            text = raw_uuid.hex()
            result.uuid = f"{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:]}"

        command_offset += size

    if symtab is not None:
        symbol_offset, symbol_count, string_offset, string_size = symtab
        entry_size = 16 if is_64_bit else 12
        if (
            symbol_offset + symbol_count * entry_size <= len(data)
            and string_offset + string_size <= len(data)
        ):
            string_table = data[string_offset : string_offset + string_size]
            for index in range(symbol_count):
                offset = symbol_offset + index * entry_size
                if is_64_bit:
                    string_index, symbol_type, section, description, value = struct.unpack_from(
                        "<IBBHQ", data, offset
                    )
                else:
                    string_index, symbol_type, section, description, value = struct.unpack_from(
                        "<IBBHI", data, offset
                    )
                if string_index >= len(string_table):
                    name = ""
                else:
                    end = string_table.find(b"\0", string_index)
                    if end < 0:
                        end = len(string_table)
                    name = string_table[string_index:end].decode("utf-8", "replace")
                result.symbols.append(Symbol(name, value, symbol_type, section, description))

    if function_data is not None:
        data_offset, data_size = function_data
        end = min(len(data), data_offset + data_size)
        text_segment = next((segment for segment in result.segments if segment.name == "__TEXT"), None)
        address = text_segment.vm_address if text_segment else 0
        offset = data_offset
        try:
            while offset < end:
                delta, offset = _decode_uleb128(data, offset, end)
                if delta == 0:
                    break
                address += delta
                result.function_starts.append(address)
        except MachOError:
            result.function_starts.clear()

    return result


def parse_macho(data: bytes) -> list[MachOSlice]:
    if len(data) < 4:
        raise MachOError("file is too small")
    big_magic = struct.unpack_from(">I", data, 0)[0]
    if big_magic in (FAT_MAGIC, FAT_MAGIC_64):
        is_64 = big_magic == FAT_MAGIC_64
        if len(data) < 8:
            raise MachOError("truncated fat Mach-O header")
        count = struct.unpack_from(">I", data, 4)[0]
        entry_size = 32 if is_64 else 20
        if 8 + count * entry_size > len(data):
            raise MachOError("truncated fat architecture table")
        slices = []
        for index in range(count):
            offset = 8 + index * entry_size
            if is_64:
                cpu_type, cpu_subtype, file_offset, size, align, _ = struct.unpack_from(
                    ">iiQQII", data, offset
                )
            else:
                cpu_type, cpu_subtype, file_offset, size, align = struct.unpack_from(
                    ">iiIII", data, offset
                )
            if file_offset + size > len(data):
                raise MachOError("fat Mach-O slice extends beyond the file")
            slices.append(
                _parse_thin(
                    data[file_offset : file_offset + size],
                    source_offset=file_offset,
                    source_size=size,
                )
            )
        return slices
    return [_parse_thin(data)]
