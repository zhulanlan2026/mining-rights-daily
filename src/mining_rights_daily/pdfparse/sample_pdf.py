from __future__ import annotations

SAMPLE_LINES = [
    "NI 43-101 TECHNICAL REPORT (SYNTHETIC DEMONSTRATION FILING)",
    "Project: Pilgangoora Lithium Operation",
    "Location: Pilbara, Western Australia",
    "Issuer: Mining Rights Daily sample desk",
    "Effective Date: 2024-06-30",
    "Standard: NI 43-101",
    "Disclaimer: Synthetic filing for protocol demonstration. Not a company disclosure.",
    "MINERAL RESOURCES",
    "Cutoff: 0.20 percent Li2O. Resources are inclusive of reserves.",
    "Category Tonnes_Mt Grade_Li2O_pct Contained_Li2O_kt",
    "Measured 8.2 1.41 116",
    "Indicated 108.4 1.26 1366",
    "Inferred 53.1 1.15 611",
    "MINERAL RESERVES",
    "Category Tonnes_Mt Grade_Li2O_pct",
    "Proven 12.4 1.32",
    "Probable 74.8 1.24",
    "Notes: Inferred resources are not mineral reserves.",
]


def build_text_pdf(lines: list[str]) -> bytes:
    """One-page PDF with one absolutely positioned line per row.

    Standard Helvetica is WinAnsi, so non-ASCII characters are replaced.
    pypdf can group rows because each line has its own text matrix.
    """

    commands = ["BT", "/F1 10 Tf"]
    y = 760
    for line in lines:
        safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in line)
        escaped = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"1 0 0 1 48 {y} Tm ({escaped}) Tj")
        y -= 14
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")
    content = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>"
        ),
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: content,
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in range(1, 6):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("ascii")
        out += objects[number]
        out += b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 6\n"
    out += b"0000000000 65535 f \n"
    for number in range(1, 6):
        out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    return bytes(out)


def build_sample_pdf() -> bytes:
    return build_text_pdf(SAMPLE_LINES)
