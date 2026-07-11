from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .macho import CPU_TYPE_ARM, MachOError, MachOSlice, Symbol


MODULE_PREFIX = "_mono_aot_module_"
MODULE_SUFFIX = "_info"


@dataclass(frozen=True)
class GlobalEntry:
    index: int
    name_address: int
    value_address: int
    name: str | None
    name_storage_encrypted: bool

    def to_manifest(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AotModule:
    symbol: Symbol
    module_name: str
    globals_address: int | None = None
    globals_hash_address: int | None = None
    entries: list[GlobalEntry] = field(default_factory=list)
    error: str | None = None
    file_info_address: int | None = None
    file_info_words: list[int] = field(default_factory=list)
    file_info_inferred: bool = False

    @property
    def readable_name_count(self) -> int:
        return sum(entry.name is not None for entry in self.entries)

    @property
    def global_names_readable(self) -> bool:
        return self.readable_name_count >= min(5, max(1, len(self.entries) // 4))

    @property
    def globals_by_name(self) -> dict[str, int]:
        return {
            entry.name: entry.value_address
            for entry in self.entries
            if entry.name is not None
        }

    @property
    def nmethods(self) -> int | None:
        if len(self.file_info_words) >= 4:
            value = self.file_info_words[3]
            if 0 < value < 10_000_000:
                return value
        return None

    def to_manifest(self, include_entries: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "symbol": self.symbol.name,
            "symbol_address": self.symbol.value,
            "module_name": self.module_name,
            "globals_address": self.globals_address,
            "globals_hash_address": self.globals_hash_address,
            "global_entry_count": len(self.entries),
            "readable_name_count": self.readable_name_count,
            "global_names_readable": self.global_names_readable,
            "file_info_address": self.file_info_address,
            "file_info_words": self.file_info_words,
            "file_info_inferred": self.file_info_inferred,
            "nmethods": self.nmethods,
            "error": self.error,
        }
        if include_entries:
            result["entries"] = [entry.to_manifest() for entry in self.entries]
        else:
            result["named_globals"] = self.globals_by_name
        return result


def sanitize_module_name(assembly_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", assembly_name)


def _module_name(symbol_name: str) -> str:
    if not symbol_name.startswith(MODULE_PREFIX) or not symbol_name.endswith(MODULE_SUFFIX):
        return symbol_name
    return symbol_name[len(MODULE_PREFIX) : -len(MODULE_SUFFIX)]


def _read_words(image: MachOSlice, address: int, count: int) -> list[int]:
    return [image.read_u32(address + index * 4) for index in range(count)]


def _plausible_file_info(words: list[int], executable_size: int) -> int:
    if len(words) < 4:
        return -1
    plt_got_base, got_size, plt_size, nmethods = words[:4]
    if not 1 <= nmethods <= 2_000_000:
        return -1
    if got_size > executable_size * 4 or plt_size > 2_000_000:
        return -1
    score = 2
    if plt_got_base <= max(got_size, 0x100000):
        score += 1
    if len(words) >= 7 and all(value <= 0x100000 for value in words[4:7]):
        score += 1
    if len(words) >= 13 and all(value <= 0x100000 for value in words[7:13]):
        score += 1
    return score


def _is_writable_address(image: MachOSlice, address: int) -> bool:
    return any(
        segment.initial_protection & 0x2
        and segment.vm_address <= address < segment.vm_address + segment.file_size
        for segment in image.segments
    )


def parse_aot_module(image: MachOSlice, symbol: Symbol, maximum_entries: int = 250_000) -> AotModule:
    module = AotModule(symbol=symbol, module_name=_module_name(symbol.name))
    if image.is_64_bit:
        module.error = "legacy Unity Mono AOT module parsing currently supports 32-bit images"
        return module

    try:
        globals_address = image.read_pointer(symbol.value)
        module.globals_address = globals_address
        module.globals_hash_address = image.read_pointer(globals_address)
        cursor = globals_address + image.pointer_size
        for index in range(maximum_entries):
            name_address = image.read_pointer(cursor)
            value_address = image.read_pointer(cursor + image.pointer_size)
            cursor += image.pointer_size * 2
            if name_address == 0 and value_address == 0:
                break
            name = image.read_c_string(name_address)
            module.entries.append(
                GlobalEntry(
                    index=index,
                    name_address=name_address,
                    value_address=value_address,
                    name=name,
                    name_storage_encrypted=image.is_vm_encrypted(name_address),
                )
            )
        else:
            module.error = f"global table exceeded safety limit ({maximum_entries} entries)"
    except (MachOError, IndexError) as error:
        module.error = str(error)
        return module

    named_file_info = module.globals_by_name.get("mono_aot_file_info")
    if named_file_info:
        try:
            module.file_info_address = named_file_info
            module.file_info_words = _read_words(image, named_file_info, 13)
        except MachOError:
            pass

    if module.file_info_address is None:
        best: tuple[int, int, list[int]] | None = None
        for entry in module.entries:
            if not _is_writable_address(image, entry.value_address):
                continue
            try:
                words = _read_words(image, entry.value_address, 13)
            except MachOError:
                continue
            score = _plausible_file_info(words, len(image.data))
            if score >= 0 and (best is None or score > best[0]):
                best = (score, entry.value_address, words)
        if best is not None:
            _, address, words = best
            module.file_info_address = address
            module.file_info_words = words
            module.file_info_inferred = True

    return module


def parse_aot_modules(image: MachOSlice) -> list[AotModule]:
    return [parse_aot_module(image, symbol) for symbol in image.module_symbols()]


def canonical_code_address(image: MachOSlice, raw_address: int) -> int:
    if image.cpu_type == CPU_TYPE_ARM:
        return raw_address & ~1
    return raw_address


def _is_executable_address(image: MachOSlice, address: int) -> bool:
    for segment in image.segments:
        if not segment.initial_protection & 0x4:
            continue
        if segment.vm_address <= address < segment.vm_address + segment.vm_size:
            return True
    return False


def build_method_map(
    image: MachOSlice,
    module: AotModule,
    metadata_methods: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    globals_by_name = module.globals_by_name
    table_address = globals_by_name.get("method_addresses")
    if table_address is None:
        if image.encrypted or not module.global_names_readable:
            return [], "native AOT names/tables are unavailable until the executable is decrypted"
        return [], "AOT global table has no method_addresses entry"

    method_count = module.nmethods
    highest_rid = max((int(method["rid"]) for method in metadata_methods), default=0)
    read_count = method_count or highest_rid
    if read_count < highest_rid:
        return [], f"AOT table has {read_count} entries but metadata needs RID {highest_rid}"
    if read_count > 2_000_000:
        return [], f"refusing implausible method table size {read_count}"

    try:
        raw_addresses = [
            image.read_pointer(table_address + index * image.pointer_size)
            for index in range(read_count)
        ]
    except MachOError as error:
        return [], f"could not read method_addresses: {error}"

    canonical_addresses = [canonical_code_address(image, value) for value in raw_addresses if value]
    usable_addresses = sorted(set(value for value in canonical_addresses if _is_executable_address(image, value)))
    result: list[dict[str, Any]] = []
    by_rid = {int(method["rid"]): method for method in metadata_methods}

    for rid in sorted(by_rid):
        index = rid - 1
        raw_address = raw_addresses[index]
        if raw_address == 0:
            continue
        address = canonical_code_address(image, raw_address)
        if not _is_executable_address(image, address):
            continue
        end = image.nearest_function_end(address, usable_addresses)
        size = end - address if end is not None and end > address else None
        method = dict(by_rid[rid])
        method.update(
            {
                "aot_index": index,
                "raw_address": raw_address,
                "address": address,
                "thumb": bool(image.cpu_type == CPU_TYPE_ARM and raw_address & 1),
                "estimated_size": size,
            }
        )
        result.append(method)

    return result, None
