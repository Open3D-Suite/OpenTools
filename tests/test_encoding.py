# SPDX-License-Identifier: GPL-3.0-or-later
"""The text files of the repo are valid UTF-8 and free of mojibake.

Mojibake is what UTF-8 text becomes when a program reads it as cp1252 or latin-1
and saves it again: one curly quote turns into three junk characters. Everything
searched for here is written with escapes, so this file never matches itself.
"""

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEXT_EXTENSIONS = (
    ".py",
    ".ms",
    ".mcr",
    ".json",
    ".xml",
    ".md",
    ".txt",
    ".ui",
    ".qss",
    ".toml",
    ".yml",
    ".yaml",
    ".cfg",
    ".ini",
    ".svg",
    ".ps1",
)
TEXT_NAMES = ("LICENSE", ".gitattributes", ".gitignore")


def as_cp1252(data):
    """Bytes read the way Windows reads cp1252 (its five unassigned bytes become control characters)."""
    return "".join(bytes([byte]).decode("cp1252", "ignore") or chr(byte) for byte in data)


# What the second and later bytes of a UTF-8 character (0x80-0xBF) look like once misread.
_TRAIL_BYTES = bytes(range(0x80, 0xC0))
_TRAIL = "[%s]" % re.escape("".join(sorted(set(as_cp1252(_TRAIL_BYTES) + _TRAIL_BYTES.decode("latin-1")))))

MOJIBAKE = re.compile(
    "|".join(
        (
            "\xe2\N{EURO SIGN}",  # curly quotes, dashes, bullet, ellipsis (U+2000-U+203F), whatever follows
            "\xe2%s{2}" % _TRAIL,  # arrows, check marks, squares and the rest of U+2000-U+2FFF
            "\xc3%s" % _TRAIL,  # accented Latin letters (U+00C0-U+00FF)
            "\xc2[\xa0-\xbf]",  # no-break space, middle dot, degree sign (U+00A0-U+00BF)
            "[\xd0\xd1]%s" % _TRAIL,  # Cyrillic
            "\xef\xbb\xbf",  # byte order mark
            "\xf0%s{3}" % _TRAIL,  # emoji
            "\N{REPLACEMENT CHARACTER}",  # the original text is already lost
        )
    )
)


def problems_in(data):
    """What is wrong with the bytes of a text file: ["not valid UTF-8 ..."], ["line 12: ...", ...] or []."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return ["not valid UTF-8 (byte 0x%02X at offset %d)" % (data[error.start], error.start)]
    return [
        "line %d: %s" % (number, ascii(line.strip()[:120]))
        for number, line in enumerate(text.split("\n"), 1)
        if MOJIBAKE.search(line)
    ]


def text_files():
    """Paths of the text files in the working tree (hidden and cache folders are skipped)."""
    for folder, subfolders, names in os.walk(REPO):
        subfolders[:] = [name for name in subfolders if not name.startswith(".") and name != "__pycache__"]
        for name in names:
            if name in TEXT_NAMES or os.path.splitext(name)[1].lower() in TEXT_EXTENSIONS:
                yield os.path.join(folder, name)


class EncodingTests(unittest.TestCase):
    def test_repo_text_files(self):
        problems = []
        names = []
        for path in text_files():
            name = os.path.relpath(path, REPO).replace(os.sep, "/")
            names.append(name)
            with open(path, "rb") as handle:
                problems.extend("%s: %s" % (name, problem) for problem in problems_in(handle.read()))
        self.assertIn("OpenTools.bundle/Contents/python/opentools/inspector.py", names)  # the walk finds the sources
        if problems:
            self.fail("mojibake or invalid UTF-8 in %d place(s):\n%s" % (len(problems), "\n".join(problems)))

    def test_detector(self):
        # the defect that started this test: curly quotes around a name, read as cp1252
        quoted = "signature \N{LEFT DOUBLE QUOTATION MARK}%s\N{RIGHT DOUBLE QUOTATION MARK}"
        self.assertEqual(problems_in(("fine\n%s\nfine" % quoted).encode("utf-8")), [])
        found = problems_in(("fine\n%s\nfine" % as_cp1252(quoted.encode("utf-8"))).encode("utf-8"))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("line 2: "), found[0])
        # characters this repo uses: fine as they are, caught once they are misread
        for code in (0xB7, 0xE7, 0x434, 0x2014, 0x201D, 0x2026, 0x2193, 0x2605, 0x2713, 0xFEFF, 0x1F512):
            data = chr(code).encode("utf-8")
            self.assertEqual(problems_in(data), [], hex(code))
            self.assertTrue(problems_in(as_cp1252(data).encode("utf-8")), hex(code))
            self.assertTrue(problems_in(data.decode("latin-1").encode("utf-8")), hex(code))
        self.assertTrue(problems_in("lost \N{REPLACEMENT CHARACTER}".encode("utf-8")))
        self.assertTrue(problems_in(b"fa\xe7ade"))  # saved as cp1252: not UTF-8 at all
        self.assertEqual(problems_in(b"plain ASCII\r\n"), [])


if __name__ == "__main__":
    unittest.main()
