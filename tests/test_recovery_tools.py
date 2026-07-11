from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.modernize_unity3_component_api import SourceAnalysis, rewrite
from tools.sanitize_aot_stubs import ILSPY_STUB, THROW_STUB, sanitize


class ModernizeUnity3ComponentApiTests(unittest.TestCase):
    def _rewrite_files(self, sources: dict[str, str]) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths: list[Path] = []
            for name, source in sources.items():
                path = root / name
                path.write_text(source, encoding="utf-8")
                paths.append(path)

            analysis = SourceAnalysis(paths)
            for path in paths:
                rewrite(path, analysis)
            return {path.name: path.read_text(encoding="utf-8") for path in paths}

    def test_rewrites_only_known_component_receivers(self) -> None:
        source = """using UnityEngine;

public class AudioInfo
{
    public AudioSource audio;
}

public class Player : MonoBehaviour
{
    private AudioInfo info;
    private RaycastHit rayHit;
    private ControllerColliderHit controllerHit;
    private GameObject target;
    private Player teammate;
    private Foo.GameObject foreignTarget;

    private void Run()
    {
        info.audio.Play();
        rayHit.collider.enabled = true;
        controllerHit.collider.enabled = true;
        target.audio.Play();
        teammate.renderer.enabled = true;
        foreignTarget.audio.Play();
        this.animation.Play();
        gameObject.camera.enabled = true;
        transform.collider.enabled = true;
        target.transform.light.enabled = true;
        target.owner.audio.Play();
    }
}
"""

        output = self._rewrite_files({"Player.cs": source})["Player.cs"]

        self.assertIn("info.audio.Play();", output)
        self.assertIn("rayHit.collider.enabled", output)
        self.assertIn("controllerHit.collider.enabled", output)
        self.assertIn("foreignTarget.audio.Play();", output)
        self.assertIn("target.owner.audio.Play();", output)
        self.assertIn("target.GetComponent<AudioSource>().Play();", output)
        self.assertIn("teammate.GetComponent<Renderer>().enabled", output)
        self.assertIn("this.GetComponent<Animation>().Play();", output)
        self.assertIn("gameObject.GetComponent<Camera>().enabled", output)
        self.assertIn("transform.GetComponent<Collider>().enabled", output)
        self.assertIn(
            "target.transform.GetComponent<Light>().enabled", output
        )

    def test_resolves_component_subclasses_across_files(self) -> None:
        outputs = self._rewrite_files(
            {
                "Actor.cs": "using UnityEngine; public class Actor : MonoBehaviour {}",
                "UseActor.cs": (
                    "public class UseActor { Actor actor; "
                    "void Run() { actor.renderer.enabled = true; } }"
                ),
            }
        )

        self.assertIn(
            "actor.GetComponent<Renderer>().enabled", outputs["UseActor.cs"]
        )

    def test_does_not_rewrite_comments_or_literals(self) -> None:
        source = '''using UnityEngine;
public class Player : MonoBehaviour
{
    GameObject target;
    void Run()
    {
        // target.audio is mentioned in documentation
        string member = "target.audio";
        target.audio.Play();
    }
}
'''

        output = self._rewrite_files({"Player.cs": source})["Player.cs"]

        self.assertIn("// target.audio is mentioned", output)
        self.assertIn('"target.audio"', output)
        self.assertIn("target.GetComponent<AudioSource>().Play();", output)

    def test_math_qualification_is_limited_and_ignores_non_code(self) -> None:
        source = '''public class Numbers
{
    double Run(double value)
    {
        // Math.Abs(value)
        string text = "Math.Sqrt(value)";
        Math.SeedRandom(1);
        return Math.Abs(value) + Math.PI;
    }
}
'''

        output = self._rewrite_files({"Numbers.cs": source})["Numbers.cs"]

        self.assertIn("// Math.Abs(value)", output)
        self.assertIn('"Math.Sqrt(value)"', output)
        self.assertIn("Math.SeedRandom(1);", output)
        self.assertIn("System.Math.Abs(value) + System.Math.PI", output)

    def test_navmesh_import_requires_unqualified_code_reference(self) -> None:
        sources = {
            "CommentOnly.cs": "// NavMeshPath is documented here\nclass Plain {}\n",
            "Qualified.cs": (
                "class Qualified { UnityEngine.AI.NavMeshPath path; }\n"
            ),
            "NeedsImport.cs": "class PathUser { NavMeshPath path; }\n",
        }

        outputs = self._rewrite_files(sources)

        self.assertFalse(outputs["CommentOnly.cs"].startswith("using UnityEngine.AI;"))
        self.assertFalse(outputs["Qualified.cs"].startswith("using UnityEngine.AI;"))
        self.assertTrue(outputs["NeedsImport.cs"].startswith("using UnityEngine.AI;"))

    def test_rewrite_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "Player.cs"
            path.write_text(
                "using UnityEngine; class Player : MonoBehaviour { "
                "void Run() { this.audio.Play(); } }",
                encoding="utf-8",
            )

            first = rewrite(path)
            after_first = path.read_text(encoding="utf-8")
            second = rewrite(path)

            self.assertEqual((1, 1), first)
            self.assertEqual((0, 0), second)
            self.assertEqual(after_first, path.read_text(encoding="utf-8"))


class SanitizeAotStubsTests(unittest.TestCase):
    def test_sanitizes_ilspy_and_default_literal_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "Recovered.cs"
            path.write_text(
                f"void A() {{ {ILSPY_STUB} }}\n"
                "int B() { return default; // stub\n}\n",
                encoding="utf-8",
            )

            changed = sanitize(path)
            output = path.read_text(encoding="utf-8")

            self.assertEqual((1, 2), changed)
            self.assertEqual(2, output.count(THROW_STUB))


if __name__ == "__main__":
    unittest.main()
