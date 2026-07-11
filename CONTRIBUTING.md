# Contributing

Contributions should include a synthetic or freely redistributable fixture. Do not commit commercial game binaries, extracted assets, managed assemblies, or source reconstructed from third-party applications.

Before opening a pull request, run:

```bash
python3 -m compileall -q aot_recover
python3 -m unittest discover -s tests -v
dotnet build aot_recover/resources/MetadataDump/MetadataDump.csproj --configuration Release --nologo
dotnet build aot_recover/resources/DonorIndex/DonorIndex.csproj --configuration Release --nologo
```

Keep format-specific changes bounded by a documented Unity/Mono generation, and include the evidence used to distinguish that generation.
