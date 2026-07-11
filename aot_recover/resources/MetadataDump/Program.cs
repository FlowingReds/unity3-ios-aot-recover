using System.Text.Json;
using Mono.Cecil;
using Mono.Cecil.Cil;

if (args.Length != 1)
{
    Console.Error.WriteLine("usage: MetadataDump <managed-assembly.dll>");
    return 2;
}

var input = Path.GetFullPath(args[0]);
if (!File.Exists(input))
{
    Console.Error.WriteLine($"assembly not found: {input}");
    return 2;
}

var readerParameters = new ReaderParameters
{
    ReadingMode = ReadingMode.Immediate,
    ReadSymbols = false,
    InMemory = true,
};

using var assembly = AssemblyDefinition.ReadAssembly(input, readerParameters);
var methods = new List<MethodRecord>();
var typeCount = 0;

foreach (var module in assembly.Modules)
{
    foreach (var type in Flatten(module.Types))
    {
        typeCount++;
        foreach (var method in type.Methods)
        {
            var instructions = method.HasBody ? method.Body.Instructions : null;
            var retOnly = instructions is { Count: 1 } && instructions[0].OpCode == OpCodes.Ret;
            methods.Add(new MethodRecord(
                Token: $"0x{method.MetadataToken.ToUInt32():x8}",
                Rid: checked((int)method.MetadataToken.RID),
                DeclaringType: method.DeclaringType.FullName,
                Name: method.Name,
                FullName: method.FullName,
                ReturnType: method.ReturnType.FullName,
                Parameters: method.Parameters.Select(parameter => new ParameterRecord(
                    parameter.Index,
                    parameter.Name,
                    parameter.ParameterType.FullName
                )).ToArray(),
                GenericParameterCount: method.GenericParameters.Count,
                Rva: method.RVA,
                HasBody: method.HasBody,
                RetOnlyBody: retOnly,
                InstructionCount: instructions?.Count ?? 0,
                CodeSize: method.HasBody ? method.Body.CodeSize : 0,
                IsAbstract: method.IsAbstract,
                IsPInvokeImpl: method.IsPInvokeImpl,
                IsInternalCall: method.IsInternalCall,
                IsRuntime: method.IsRuntime,
                IsStatic: method.IsStatic,
                IsVirtual: method.IsVirtual
            ));
        }
    }
}

methods.Sort((left, right) => left.Rid.CompareTo(right.Rid));
var result = new AssemblyRecord(
    Path: input,
    Name: assembly.Name.Name,
    Version: assembly.Name.Version?.ToString() ?? "",
    ModuleCount: assembly.Modules.Count,
    TypeCount: typeCount,
    MethodCount: methods.Count,
    MethodsWithBodies: methods.Count(method => method.HasBody),
    RetOnlyBodies: methods.Count(method => method.RetOnlyBody),
    Methods: methods
);

var options = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    WriteIndented = true,
};
Console.WriteLine(JsonSerializer.Serialize(result, options));
return 0;

static IEnumerable<TypeDefinition> Flatten(IEnumerable<TypeDefinition> roots)
{
    foreach (var root in roots)
    {
        yield return root;
        foreach (var nested in Flatten(root.NestedTypes))
            yield return nested;
    }
}

internal sealed record ParameterRecord(int Index, string Name, string Type);

internal sealed record MethodRecord(
    string Token,
    int Rid,
    string DeclaringType,
    string Name,
    string FullName,
    string ReturnType,
    ParameterRecord[] Parameters,
    int GenericParameterCount,
    int Rva,
    bool HasBody,
    bool RetOnlyBody,
    int InstructionCount,
    int CodeSize,
    bool IsAbstract,
    bool IsPInvokeImpl,
    bool IsInternalCall,
    bool IsRuntime,
    bool IsStatic,
    bool IsVirtual
);

internal sealed record AssemblyRecord(
    string Path,
    string Name,
    string Version,
    int ModuleCount,
    int TypeCount,
    int MethodCount,
    int MethodsWithBodies,
    int RetOnlyBodies,
    List<MethodRecord> Methods
);
