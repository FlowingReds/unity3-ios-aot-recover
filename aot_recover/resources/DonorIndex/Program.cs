using System.Security.Cryptography;
using System.Text.Json;
using Mono.Cecil;
using Mono.Cecil.Cil;

var targetPaths = new List<string>();
var donorPaths = new List<string>();
for (var index = 0; index < args.Length; index++)
{
    if (args[index] == "--target" && index + 1 < args.Length)
        targetPaths.Add(args[++index]);
    else if (args[index] == "--donor" && index + 1 < args.Length)
        donorPaths.Add(args[++index]);
    else
    {
        Console.Error.WriteLine("usage: DonorIndex --target target.dll [--target ...] --donor donor.dll [--donor ...]");
        return 2;
    }
}

if (targetPaths.Count == 0 || donorPaths.Count == 0)
{
    Console.Error.WriteLine("at least one --target and one --donor assembly are required");
    return 2;
}

var targets = targetPaths.Select(AssemblyInput.Load).ToArray();
var donors = donorPaths.Select(AssemblyInput.Load).ToArray();
try
{
    var donorByAssembly = donors.ToDictionary(input => input.Assembly);
    var donorMethods = donors.SelectMany(input => input.Methods)
        .GroupBy(ExactKey)
        .ToDictionary(group => group.Key, group => group.ToArray());
    var matches = new List<MatchRecord>();
    var summaries = new List<TargetSummary>();

    foreach (var target in targets)
    {
        var exactCount = 0;
        var bodyBeyondRetStubCount = 0;
        var tierACount = 0;
        var tierBCount = 0;
        var tierCCount = 0;

        foreach (var targetMethod in target.Methods)
        {
            if (!donorMethods.TryGetValue(ExactKey(targetMethod), out var candidates))
                continue;
            exactCount++;
            var ranked = candidates.Select(method =>
            {
                var sameFields = FieldShape(targetMethod.DeclaringType) == FieldShape(method.DeclaringType);
                var sameMethods = sameFields &&
                    MethodShape(targetMethod.DeclaringType) == MethodShape(method.DeclaringType);
                return new
                {
                    Method = method,
                    BodyBeyondRetStub = HasBodyBeyondRetStub(method),
                    SameFieldShape = sameFields,
                    SameMethodShape = sameMethods,
                    Donor = donorByAssembly[method.Module.Assembly],
                };
            })
                .OrderByDescending(item => item.BodyBeyondRetStub)
                .ThenByDescending(item => item.SameMethodShape)
                .ThenByDescending(item => item.SameFieldShape)
                .ThenBy(item => item.Donor.Sha256, StringComparer.Ordinal)
                .ThenBy(item => item.Method.MetadataToken.RID)
                .First();
            var donorMethod = ranked.Method;
            var bodyBeyondRetStub = ranked.BodyBeyondRetStub;
            var sameFieldShape = ranked.SameFieldShape;
            var sameMethodShape = ranked.SameMethodShape;
            string tier;
            if (!bodyBeyondRetStub)
                tier = "metadata-only";
            else if (sameMethodShape)
            {
                tier = "A";
                tierACount++;
            }
            else if (sameFieldShape)
            {
                tier = "B";
                tierBCount++;
            }
            else
            {
                tier = "C";
                tierCCount++;
            }
            if (bodyBeyondRetStub) bodyBeyondRetStubCount++;

            var donorInput = ranked.Donor;
            matches.Add(new MatchRecord(
                TargetAssembly: target.Assembly.Name.Name,
                TargetAssemblySha256: target.Sha256,
                TargetToken: $"0x{targetMethod.MetadataToken.ToUInt32():x8}",
                TargetRid: checked((int)targetMethod.MetadataToken.RID),
                TargetDeclaringType: DisplayTypeKey(targetMethod.DeclaringType),
                TargetFullName: targetMethod.FullName,
                TargetRetOnlyBody: IsRetOnly(targetMethod),
                DonorAssembly: donorInput.Assembly.Name.Name,
                DonorAssemblySha256: donorInput.Sha256,
                DonorToken: $"0x{donorMethod.MetadataToken.ToUInt32():x8}",
                DonorRid: checked((int)donorMethod.MetadataToken.RID),
                DonorDeclaringType: DisplayTypeKey(donorMethod.DeclaringType),
                DonorFullName: donorMethod.FullName,
                DonorHasBodyBeyondRetStub: bodyBeyondRetStub,
                DonorCodeSize: donorMethod.HasBody ? donorMethod.Body.CodeSize : 0,
                DonorInstructionCount: donorMethod.HasBody ? donorMethod.Body.Instructions.Count : 0,
                SameFieldShape: sameFieldShape,
                SameMethodShape: sameMethodShape,
                ConfidenceTier: tier,
                AmbiguousDonorCount: candidates.Length
            ));
        }

        summaries.Add(new TargetSummary(
            Assembly: target.Assembly.Name.Name,
            AssemblySha256: target.Sha256,
            TargetMethodCount: target.Methods.Length,
            ExactSignatureMatches: exactCount,
            DonorBodiesBeyondRetStub: bodyBeyondRetStubCount,
            TierA: tierACount,
            TierB: tierBCount,
            TierC: tierCCount
        ));
    }

    var donorSummaries = donors.Select(input => new DonorSummary(
        Assembly: input.Assembly.Name.Name,
        Version: input.Assembly.Name.Version?.ToString() ?? "",
        Sha256: input.Sha256,
        MethodCount: input.Methods.Length,
        BodyBeyondRetStubCount: input.Methods.Count(HasBodyBeyondRetStub)
    )).ToArray();
    var result = new DonorIndexReport(
        SchemaVersion: 1,
        IdentityPolicy: "scope-aware normalized signature; Assembly-CSharp and firstpass share <game> scope",
        BodyPolicy: "method has CIL and is not exactly one ret instruction",
        Targets: summaries,
        Donors: donorSummaries,
        ExactSignatureMatches: summaries.Sum(item => item.ExactSignatureMatches),
        DonorBodiesBeyondRetStub: summaries.Sum(item => item.DonorBodiesBeyondRetStub),
        TierA: summaries.Sum(item => item.TierA),
        TierB: summaries.Sum(item => item.TierB),
        TierC: summaries.Sum(item => item.TierC),
        Matches: matches
    );
    Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
    }));
    return 0;
}
finally
{
    foreach (var input in targets.Concat(donors)) input.Dispose();
}

static bool IsRetOnly(MethodDefinition method) => method.HasBody &&
    method.Body.Instructions.Count == 1 && method.Body.Instructions[0].OpCode == OpCodes.Ret;

static bool HasBodyBeyondRetStub(MethodDefinition method) => method.HasBody && !IsRetOnly(method);

static string DisplayTypeKey(TypeReference type) => type.FullName.Replace("/", "+");

static string ScopeKey(TypeReference type)
{
    var scope = type.GetElementType().Scope;
    var simpleName = scope switch
    {
        AssemblyNameReference assembly => assembly.Name,
        ModuleDefinition module when module.Assembly is not null => module.Assembly.Name.Name,
        ModuleDefinition module => Path.GetFileNameWithoutExtension(module.Name),
        ModuleReference module => Path.GetFileNameWithoutExtension(module.Name),
        _ => scope?.Name ?? "<generic>",
    };
    return simpleName.Equals("Assembly-CSharp", StringComparison.OrdinalIgnoreCase) ||
        simpleName.Equals("Assembly-CSharp-firstpass", StringComparison.OrdinalIgnoreCase)
        ? "<game>"
        : simpleName;
}

static string IdentityTypeKey(TypeReference type) => type switch
{
    GenericParameter parameter => $"generic({parameter.Type},{parameter.Position})",
    GenericInstanceType generic =>
        $"{IdentityTypeKey(generic.ElementType)}<{string.Join(",", generic.GenericArguments.Select(IdentityTypeKey))}>",
    ArrayType array => $"array({array.Rank},{IdentityTypeKey(array.ElementType)})",
    ByReferenceType byReference => $"byref({IdentityTypeKey(byReference.ElementType)})",
    PointerType pointer => $"pointer({IdentityTypeKey(pointer.ElementType)})",
    PinnedType pinned => $"pinned({IdentityTypeKey(pinned.ElementType)})",
    SentinelType sentinel => $"sentinel({IdentityTypeKey(sentinel.ElementType)})",
    RequiredModifierType modifier =>
        $"modreq({IdentityTypeKey(modifier.ModifierType)},{IdentityTypeKey(modifier.ElementType)})",
    OptionalModifierType modifier =>
        $"modopt({IdentityTypeKey(modifier.ModifierType)},{IdentityTypeKey(modifier.ElementType)})",
    FunctionPointerType function =>
        $"fnptr({IdentityTypeKey(function.ReturnType)}({string.Join(",", function.Parameters.Select(parameter => IdentityTypeKey(parameter.ParameterType)))}))",
    _ => $"{DisplayTypeKey(type)}@{ScopeKey(type)}",
};

static string ExactKey(MethodDefinition method) =>
    $"{IdentityTypeKey(method.DeclaringType)}::{method.Name}`{method.GenericParameters.Count}" +
    $"({string.Join(",", method.Parameters.Select(parameter => IdentityTypeKey(parameter.ParameterType)))})" +
    $"=>{IdentityTypeKey(method.ReturnType)};this={method.HasThis};explicit={method.ExplicitThis};" +
    $"call={(int)method.CallingConvention}";

static string ConstantKey(object? value) => value switch
{
    null => "<null>",
    byte[] bytes => Convert.ToHexString(bytes),
    _ => $"{value.GetType().FullName}:{value}",
};

static string FieldShape(TypeDefinition type) =>
    $"base={(type.BaseType is null ? "" : IdentityTypeKey(type.BaseType))};attrs={(uint)type.Attributes};" +
    $"interfaces={string.Join(",", type.Interfaces.Select(item => IdentityTypeKey(item.InterfaceType)).OrderBy(item => item))};" +
    "fields=" + string.Join("|", type.Fields.Select(field =>
        $"{field.Name}:{IdentityTypeKey(field.FieldType)}:attrs={(uint)field.Attributes}:" +
        $"hasconst={field.HasConstant}:const={ConstantKey(field.HasConstant ? field.Constant : null)}"));

static string MethodShape(TypeDefinition type) => string.Join("|", type.Methods.Select(method =>
    $"{ExactKey(method)}:attrs={(uint)method.Attributes}:impl={(uint)method.ImplAttributes}").OrderBy(item => item));

internal sealed class AssemblyInput : IDisposable
{
    public required AssemblyDefinition Assembly { get; init; }
    public required string Sha256 { get; init; }
    public required MethodDefinition[] Methods { get; init; }

    public static AssemblyInput Load(string path)
    {
        var fullPath = Path.GetFullPath(path);
        var assembly = AssemblyDefinition.ReadAssembly(fullPath, new ReaderParameters
        {
            ReadingMode = ReadingMode.Immediate,
            InMemory = true,
            ReadSymbols = false,
        });
        var methods = assembly.Modules.SelectMany(module => Flatten(module.Types))
            .SelectMany(type => type.Methods)
            .ToArray();
        foreach (var method in methods)
            if (method.HasBody) _ = method.Body.Instructions.Count;
        return new AssemblyInput
        {
            Assembly = assembly,
            Sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(fullPath))).ToLowerInvariant(),
            Methods = methods,
        };
    }

    private static IEnumerable<TypeDefinition> Flatten(IEnumerable<TypeDefinition> roots)
    {
        foreach (var root in roots)
        {
            yield return root;
            foreach (var nested in Flatten(root.NestedTypes)) yield return nested;
        }
    }

    public void Dispose() => Assembly.Dispose();
}

internal sealed record TargetSummary(
    string Assembly,
    string AssemblySha256,
    int TargetMethodCount,
    int ExactSignatureMatches,
    int DonorBodiesBeyondRetStub,
    int TierA,
    int TierB,
    int TierC
);

internal sealed record DonorSummary(
    string Assembly,
    string Version,
    string Sha256,
    int MethodCount,
    int BodyBeyondRetStubCount
);

internal sealed record MatchRecord(
    string TargetAssembly,
    string TargetAssemblySha256,
    string TargetToken,
    int TargetRid,
    string TargetDeclaringType,
    string TargetFullName,
    bool TargetRetOnlyBody,
    string DonorAssembly,
    string DonorAssemblySha256,
    string DonorToken,
    int DonorRid,
    string DonorDeclaringType,
    string DonorFullName,
    bool DonorHasBodyBeyondRetStub,
    int DonorCodeSize,
    int DonorInstructionCount,
    bool SameFieldShape,
    bool SameMethodShape,
    string ConfidenceTier,
    int AmbiguousDonorCount
);

internal sealed record DonorIndexReport(
    int SchemaVersion,
    string IdentityPolicy,
    string BodyPolicy,
    List<TargetSummary> Targets,
    DonorSummary[] Donors,
    int ExactSignatureMatches,
    int DonorBodiesBeyondRetStub,
    int TierA,
    int TierB,
    int TierC,
    List<MatchRecord> Matches
);
