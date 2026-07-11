// Decompile functions named by ApplyAotMethodMap.py into one C-like file per method.
//@category Unity3AOT

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;

public class ExportAotPseudoC extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("Usage: ExportAotPseudoC.java <output-directory> [maximum-functions]");
            return;
        }
        File output = new File(args[0]);
        if (!output.exists() && !output.mkdirs()) {
            throw new IOException("Could not create " + output.getAbsolutePath());
        }
        int maximum = args.length >= 2 ? Integer.parseInt(args[1]) : 0;
        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(true);
        decompiler.setSimplificationStyle("decompile");
        if (!decompiler.openProgram(currentProgram)) {
            throw new IOException("Ghidra decompiler could not open the current program");
        }

        int written = 0;
        Set<String> names = new HashSet<>();
        File indexFile = new File(output, "functions.tsv");
        try (BufferedWriter index = new BufferedWriter(new FileWriter(indexFile))) {
            index.write("address\tname\tfile\tstatus\n");
            FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
            while (iterator.hasNext() && !monitor.isCancelled()) {
                Function function = iterator.next();
                if (!function.getName().startsWith("aot_") || function.isExternal()) {
                    continue;
                }
                if (maximum > 0 && written >= maximum) {
                    break;
                }
                monitor.setMessage("Decompiling " + function.getName());
                String base = safeName(function.getEntryPoint() + "_" + function.getName());
                String unique = base;
                int suffix = 2;
                while (!names.add(unique)) {
                    unique = base + "_" + suffix++;
                }
                File target = new File(output, unique + ".c");
                DecompileResults result = decompiler.decompileFunction(function, 90, monitor);
                String status;
                String body;
                if (result != null && result.decompileCompleted() && result.getDecompiledFunction() != null) {
                    body = result.getDecompiledFunction().getC();
                    status = "ok";
                }
                else {
                    String message = result == null ? "no result" : result.getErrorMessage();
                    body = "/* Decompilation failed: " + message + " */\n";
                    status = "failed: " + message;
                }
                try (BufferedWriter writer = new BufferedWriter(new FileWriter(target))) {
                    writer.write("/* " + function.getEntryPoint() + " | " + function.getComment() + " */\n\n");
                    writer.write(body);
                    if (!body.endsWith("\n")) writer.write("\n");
                }
                index.write(function.getEntryPoint() + "\t" + function.getName() + "\t" +
                    target.getName() + "\t" + status.replace('\t', ' ') + "\n");
                written++;
            }
        }
        finally {
            decompiler.dispose();
        }
        println("AOT pseudocode files written: " + written);
    }

    private String safeName(String value) {
        String result = value.replaceAll("[^A-Za-z0-9_.@+-]+", "_");
        return result.length() > 180 ? result.substring(0, 180) : result;
    }
}
