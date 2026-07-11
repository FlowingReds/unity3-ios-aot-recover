using System;

namespace DonorIndexFixture;

public sealed class Stable
{
    public int value;
    public void Run() => Console.WriteLine("stable donor");
}

public sealed class FieldOnly
{
    public int value;
    public void Run() => Console.WriteLine("field-only donor");
    public void AddedLater() => Console.WriteLine("changes the method surface");
}

public sealed class SignatureOnly
{
    public string value = "changed";
    public void Run() => Console.WriteLine(value);
}
