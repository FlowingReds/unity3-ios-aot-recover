namespace DonorIndexFixture;

public sealed class Stable
{
    public int value;
    public void Run() { }
}

public sealed class FieldOnly
{
    public int value;
    public void Run() { }
}

public sealed class SignatureOnly
{
    public int value;
    public void Run() { }
}

public sealed class NoMatch
{
    public void TargetOnly() { }
}
