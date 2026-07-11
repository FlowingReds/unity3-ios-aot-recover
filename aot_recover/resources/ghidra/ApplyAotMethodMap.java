// Apply token-to-address labels produced by unity3-aot-recover.
//@category Unity3AOT

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.symbol.SourceType;

import java.io.BufferedReader;
import java.io.FileReader;
import java.math.BigInteger;

public class ApplyAotMethodMap extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("Usage: ApplyAotMethodMap.java <ghidra-method-map.tsv>");
            return;
        }
        ProgramContext context = currentProgram.getProgramContext();
        Register tmode = context.getRegister("TMode");
        int created = 0;
        int named = 0;
        int failed = 0;

        try (BufferedReader reader = new BufferedReader(new FileReader(args[0]))) {
            String line = reader.readLine();
            while ((line = reader.readLine()) != null && !monitor.isCancelled()) {
                String[] fields = line.split("\\t", -1);
                if (fields.length < 7) {
                    failed++;
                    continue;
                }
                try {
                    long offset = Long.parseUnsignedLong(fields[0].replaceFirst("^0[xX]", ""), 16);
                    Address address = toAddr(offset);
                    boolean thumb = fields[2].equals("1");
                    long size = fields[3].isEmpty() ? 0 : Long.parseLong(fields[3]);
                    String label = fields[4];
                    String signature = fields[5];
                    String token = fields[6];
                    if (thumb && tmode != null) {
                        try {
                            context.setValue(tmode, address, address, BigInteger.ONE);
                        }
                        catch (Exception conflict) {
                            if (size > 0) {
                                clearListing(address, address.add(size - 1));
                            }
                            try {
                                context.setValue(tmode, address, address, BigInteger.ONE);
                            }
                            catch (Exception ignored) {
                                printerr("Could not set Thumb context at " + address + "; keeping existing context");
                            }
                        }
                    }
                    disassemble(address);
                    Function function = getFunctionAt(address);
                    if (function == null) {
                        function = createFunction(address, label);
                        if (function != null) created++;
                    }
                    if (function == null) {
                        failed++;
                        continue;
                    }
                    function.setName(label, SourceType.USER_DEFINED);
                    function.setComment(token + " | " + signature);
                    named++;
                }
                catch (Exception error) {
                    printerr("Could not apply row: " + line + " (" + error + ")");
                    failed++;
                }
            }
        }
        println("AOT functions created: " + created);
        println("AOT functions named: " + named);
        println("AOT rows failed: " + failed);
    }
}
