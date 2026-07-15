import unittest

from aot_recover.gui_server import build_args


class BuildArgsTest(unittest.TestCase):
    def test_maps_fields(self):
        args = build_args(
            {
                "ipa": " /games/x.ipa ",
                "output": "/out",
                "binary": "",
                "arch": "armv7",
                "ilspycmd": "",
                "no_decompile": True,
                "reference_managed": ["/a", "", "  ", "/b"],
            }
        )
        self.assertEqual(args.ipa, "/games/x.ipa")
        self.assertEqual(args.output, "/out")
        self.assertIsNone(args.binary)
        self.assertEqual(args.arch, "armv7")
        self.assertIsNone(args.ilspycmd)
        self.assertIs(args.no_decompile, True)
        self.assertEqual(args.reference_managed, ["/a", "/b"])

    def test_arch_all_is_none(self):
        self.assertIsNone(build_args({"arch": "all"}).arch)
        self.assertIsNone(build_args({}).arch)

    def test_empty_defaults(self):
        args = build_args({})
        self.assertIsNone(args.ipa)
        self.assertIsNone(args.output)
        self.assertIs(args.no_decompile, False)
        self.assertIsNone(args.reference_managed)

    def test_refs_accepts_newline_string(self):
        args = build_args({"reference_managed": "/a\n\n/b\n"})
        self.assertEqual(args.reference_managed, ["/a", "/b"])


if __name__ == "__main__":
    unittest.main()
