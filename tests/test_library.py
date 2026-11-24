import json
import os
import tempfile
import unittest
from pathlib import Path

from bridge import library as L

ACF = '''"AppState"
{
\t"appid"\t\t"123"
\t"name"\t\t"Test \\"Game\\""
\t"installdir"\t\t"TestGame"
}
'''
VDF = '''"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"%s"
\t\t"apps"
\t\t{
\t\t\t"123"\t\t"5"
\t\t}
\t}
}
'''


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._rv, self._rs = L.reg_value, L.reg_subkeys
        L.reg_value = lambda *a, **k: None
        L.reg_subkeys = lambda *a, **k: []

    def tearDown(self):
        L.reg_value, L.reg_subkeys = self._rv, self._rs
        self.tmp.cleanup()

    def test_vdf(self):
        d = L.parse_vdf(ACF)
        self.assertEqual(d["appstate"]["name"], 'Test "Game"')
        d = L.parse_vdf(VDF % "C:\\\\Lib")
        self.assertEqual(d["libraryfolders"]["0"]["path"], "C:\\Lib")
        self.assertEqual(d["libraryfolders"]["0"]["apps"]["123"], "5")

    def test_slug(self):
        self.assertEqual(L.slugify("S.T.A.L.K.E.R. 2: Heart!"), "s-t-a-l-k-e-r-2-heart")
        self.assertLessEqual(len(L.slugify("x" * 100)), 40)
        self.assertEqual(L.slugify("!!!"), "game")

    def _steam(self):
        steam = self.root / "Steam"
        sa = steam / "steamapps"
        (sa / "common" / "TestGame").mkdir(parents=True)
        (sa / "common" / "TestGame" / "g.exe").write_text("")
        (sa / "common" / "Steamworks Shared").mkdir()
        (sa / "common" / "Steamworks Shared" / "x.exe").write_text("")
        (sa / "common" / "Empty").mkdir()
        (sa / "appmanifest_123.acf").write_text(ACF)
        (sa / "appmanifest_228980.acf").write_text(
            '"AppState"\n{\n"appid" "228980"\n"name" "Steamworks Common Redistributables"\n'
            '"installdir" "Steamworks Shared"\n}')
        (sa / "appmanifest_5.acf").write_text(
            '"AppState"\n{\n"appid" "5"\n"name" "Leer"\n"installdir" "Empty"\n}')
        (sa / "appmanifest_6.acf").write_text("kaputt {{{")
        (sa / "libraryfolders.vdf").write_text(VDF % str(steam).replace("\\", "\\\\"))
        cov = steam / "appcache" / "librarycache" / "123" / "abc"
        cov.mkdir(parents=True)
        (cov / "library_600x900.jpg").write_text("x")
        return steam

    def test_steam(self):
        steam = self._steam()
        res = L.scan_steam(str(steam))
        self.assertEqual(len(res), 1)
        g = res[0]
        self.assertEqual((g["steam"], g["source"]), ("123", "steam"))
        self.assertTrue(g["cover"].endswith("library_600x900.jpg"))
        self.assertTrue(g["dir"].endswith("TestGame"))

    def test_epic(self):
        gd = self.root / "epicgame"
        gd.mkdir()
        m = self.root / "m"
        m.mkdir()
        (m / "a.item").write_text(json.dumps({"DisplayName": "Epic G", "InstallLocation": str(gd)}))
        (m / "b.item").write_text("{kaputt")
        res = L.scan_epic(str(m))
        self.assertEqual([g["name"] for g in res], ["Epic G"])

    def test_xbox(self):
        c = self.root / "XboxGames" / "Forza" / "Content"
        c.mkdir(parents=True)
        (c / "f.exe").write_text("")
        (c / "MicrosoftGame.config").write_text(
            '<Game><ShellVisuals DefaultDisplayName="Forza Test"/></Game>')
        res = L.scan_xbox([str(self.root)])
        self.assertEqual(res[0]["name"], "Forza Test")

    def test_xbox_gaming_root(self):
        for folder, name in (("Fallout76", "Gears"), ("XboxGames", "Forza")):
            c = self.root / folder / name / "Content"
            c.mkdir(parents=True)
            (c / "f.exe").write_text("")

        def scan(folder, magic=b"RGBX"):
            (self.root / ".GamingRoot").write_bytes(
                magic + b"\x01\x00\x00\x00" + (folder + "\0").encode("utf-16-le"))
            return [g["name"] for g in L.scan_xbox([str(self.root)])]

        self.assertEqual(scan("Fallout76"), ["Gears", "Forza"])
        self.assertEqual(scan("XboxGames"), ["Forza"])          # nicht doppelt
        for bad in ("", "\\", ".", "..", "..\\x", "C:\\x", "fehlt"):
            self.assertEqual(scan(bad), ["Forza"], bad)
        self.assertEqual(scan("Fallout76", b"XXXX"), ["Forza"])
        (self.root / ".GamingRoot").write_bytes(b"RGBX\x01")     # abgeschnitten
        self.assertEqual(len(L.scan_xbox([str(self.root)])), 1)

    def test_registry_sources(self):
        gd = self.root / "gog"
        gd.mkdir()
        L.reg_subkeys = lambda r, p: ["1"] if "GOG" in p else []
        L.reg_value = lambda r, p, n: {"gameName": "GOG G", "path": str(gd)}.get(n)
        self.assertEqual(L.scan_gog()[0]["source"], "gog")

    def test_match(self):
        lib = [L._entry("A", "steam", r"E:\Lib\Game"), L._entry("B", "epic", r"E:\Lib\Game\Sub"),
               L._entry("C", "gog", r"E:\Lib\Gam")]
        self.assertEqual(L.match(lib, [r"e:/lib/game/bin/x.exe"])["name"], "A")
        self.assertEqual(L.match(lib, [r"E:\Lib\Game\Sub\x.exe"])["name"], "B")
        self.assertIsNone(L.match(lib, [r"E:\Lib\Gamer\x.exe"]))
        self.assertIsNone(L.match(lib, [r"E:\Lib\Game\CrashReportClient.exe",
                                        r"E:\Lib\Game\EasyAntiCheat_EOS.exe",
                                        r"E:\Lib\Game\UnityCrashHandler64.exe"]))

    def test_util_exes_ignored(self):
        lib = [L._entry("A", "steam", r"E:\Lib\Game")]
        for n in ("GameLauncher.exe", "Updater.exe", "Config.exe", "MySetup64.exe", "Settings.exe"):
            self.assertIsNone(L.match(lib, [r"E:\Lib\Game\%s" % n]), n)
        self.assertIsNotNone(L.match(lib, [r"E:\Lib\Game\game.exe"]))

    def _win(self, exes, names=None):
        names = names or {}
        L.reg_subkeys = lambda r, p: [str(i) for i in range(len(exes))] if "GameConfigStore" in p else []
        L.reg_value = lambda r, p, n: exes[int(p.rsplit("\\", 1)[1])] if n == "MatchedExeFullPath" else None
        pn = L.exe_product_name
        L.exe_product_name = lambda e: names.get(e)
        self.addCleanup(setattr, L, "exe_product_name", pn)

    def _exe(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return str(p)

    def test_windows_names(self):
        a = self._exe(r"SC\StarCitizen\LIVE\Bin64\StarCitizen.exe")
        b = self._exe(r"Foo Game\Binaries\Win64\Foo-Win64-Shipping.exe")
        c = self._exe(r"Bar\bar.exe")
        d = self._exe(r"Baz\Shipping\baz.exe")
        self._win([a, b, c, d, str(self.root / "weg.exe")],
                  {a: "Star Citizen", b: "UE4 Game", c: "  Bar Deluxe ", d: "Shipping"})
        res = L.scan_windows()
        self.assertEqual([g["name"] for g in res], ["Star Citizen", "Foo Game", "Bar Deluxe", "Baz"])
        self.assertTrue(all(g["source"] == "windows" and g["steam"] is None and g["cover"] is None
                            for g in res))
        self.assertEqual(res[0]["exe"], os.path.normpath(a))
        self.assertTrue(res[0]["dir"].endswith(os.path.join("SC", "StarCitizen")))
        self.assertTrue(res[1]["dir"].endswith("Foo Game"))

    def test_windows_duplicates(self):
        a = self._exe(r"Lib\TestGame\bin\g.exe")
        b = self._exe(r"Other\o.exe")
        self._win([a, b, b])
        steam = [L._entry("TestGame", "steam", str(self.root / "Lib" / "TestGame"), "1")]
        self.assertEqual([g["name"] for g in L.scan_windows(steam)], ["Other"])

    def test_windows_exact_match(self):
        a = self._exe(r"Big\Game\g.exe")
        b = self._exe(r"Big\Game\tool\t.exe")
        self._win([a])
        lib = L.scan_windows()
        lib[0]["dir"] = str(self.root / "Big")  # grosser Ordner
        self.assertIs(L.match(lib, [a]), lib[0])
        self.assertIsNone(L.match(lib, [b]))
        self.assertIsNone(L.match(lib, [str(self.root / "Big" / "Game" / "launcher.exe")]))
        self.assertIs(L.match(lib, [a.upper().replace("\\", "/")]), lib[0])

    def test_windows_broad_dir_and_name(self):
        a = self._exe(r"Games\foo.exe")
        b = self._exe(r"Program Files\Bar\client.exe")
        self._win([a, b], {a: "Foo", b: "Client"})
        res = L.scan_windows()
        self.assertTrue(res[0]["dir"].endswith("Games"))
        self.assertEqual(res[1]["name"], "Bar")
        c = self._exe(r"Games\Sub\bin\x.exe")
        self._win([c], {c: "X"})
        self.assertTrue(L.scan_windows()[0]["dir"].endswith("Sub"))
        self.assertEqual(L._windows_game_dir(r"C:\g.exe")[0], "C:\\")

    def test_windows_broad_dir_keeps_games_apart(self):
        a = self._exe(r"Games\alpha.exe")
        b = self._exe(r"Games\beta.exe")
        c = self._exe(r"Spiele\Win64\gamma-Win64-Shipping.exe")
        self._win([a, b, c])
        res = L.scan_windows()
        self.assertEqual(sorted(g["name"] for g in res), ["alpha", "beta", "gamma"])
        self.assertEqual(L.match(res, [b])["name"], "beta")

    def test_windows_merge_same_dir(self):
        a = self._exe(r"Two\Two.exe")
        b = self._exe(r"Two\other.exe")
        self._win([b, a])
        res = L.scan_windows()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["exe"], os.path.normpath(a))
        self.assertIs(L.match(res, [b]), res[0])
        self.assertIs(L.match(res, [a]), res[0])

    def test_running_paths(self):
        p = L.running_game_paths()
        self.assertTrue(any(os.path.basename(x).lower().startswith("python") for x in p))


if __name__ == "__main__":
    unittest.main()
