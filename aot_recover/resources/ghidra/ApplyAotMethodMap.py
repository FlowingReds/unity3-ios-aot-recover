#@category Unity3AOT
# Apply token-to-address labels produced by unity3-aot-recover.

from ghidra.program.model.symbol import SourceType
from java.math import BigInteger
import csv


args = getScriptArgs()
if args:
    mapping_path = args[0]
else:
    mapping_path = askFile("Select ghidra-method-map.csv", "Open").getAbsolutePath()

program_context = currentProgram.getProgramContext()
tmode = program_context.getRegister("TMode")
created = 0
renamed = 0
failed = 0

with open(mapping_path, "rb") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        if monitor.isCancelled():
            break
        try:
            address = toAddr(int(row["address"], 16))
            label = row["label"]
            if row.get("thumb") == "1" and tmode is not None:
                program_context.setValue(tmode, address, address, BigInteger.ONE)
            disassemble(address)
            function = getFunctionAt(address)
            if function is None:
                function = createFunction(address, label)
                if function is not None:
                    created += 1
            if function is not None:
                function.setName(label, SourceType.USER_DEFINED)
                function.setComment("%s | %s" % (row.get("token", ""), row.get("signature", "")))
                renamed += 1
            else:
                failed += 1
        except Exception as error:
            printerr("Could not label %s: %s" % (row.get("address", "?"), error))
            failed += 1

println("AOT labels created: %d" % created)
println("AOT functions named: %d" % renamed)
println("AOT labels failed: %d" % failed)
