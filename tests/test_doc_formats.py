"""0.70.0: document formats for the documentation import (the user, 18.11.2026: "alle gängigen Datenformate: PDF, doc, docx, ods, odt,
etc."). Every file ends converted or refused with a named reason; the converters keep headings, lists, tables and links."""
import io
import shutil
import subprocess
import zipfile

import pytest

from vi_mcp import doc_formats as df

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
ODF_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
          'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" xmlns:xlink="http://www.w3.org/1999/xlink"')


def _zip(files: dict[str, str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return b.getvalue()


def _docx() -> bytes:
    doc = f"""<w:document {W_NS}><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Runbook</w:t></w:r></w:p>
<w:p><w:r><w:t xml:space="preserve">See the </w:t></w:r><w:hyperlink r:id="rId9"><w:r><w:t>wiki</w:t></w:r></w:hyperlink><w:r><w:t>.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>stop postfix</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Host</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Size</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>mail01</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>120 GB</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
    styles = f'<w:styles {W_NS}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>'
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId9" Target="https://example.org/wiki" TargetMode="External" Type="x"/></Relationships>')
    return _zip({"word/document.xml": doc, "word/styles.xml": styles, "word/_rels/document.xml.rels": rels})


def _xlsx() -> bytes:
    ss = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    return _zip({
        "xl/workbook.xml": f'<workbook {ss} {rns}><sheets><sheet name="Hosts" sheetId="1" r:id="rId1"/>'
                           f'<sheet name="Secret" sheetId="2" r:id="rId2" state="hidden"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/>'
                                      '<Relationship Id="rId2" Target="worksheets/sheet2.xml" Type="x"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst {ss}><si><t>Host</t></si><si><t>Size</t></si><si><t>mail01</t></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {ss}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                    f'<row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>120</v></c></row></sheetData></worksheet>',
        "xl/worksheets/sheet2.xml": f'<worksheet {ss}><sheetData/></worksheet>'})


def _pptx() -> bytes:
    p = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
         'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    rel = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'
    shape = '<p:sp><p:nvSpPr><p:nvPr>{}</p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{}</a:t></a:r></a:p></p:txBody></p:sp>'
    return _zip({
        "ppt/presentation.xml": f'<p:presentation {p}><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": rel.format('<Relationship Id="rId1" Target="slides/slide1.xml" Type="x"/>'),
        "ppt/slides/slide1.xml": f'<p:sld {p}><p:cSld><p:spTree>' + shape.format('<p:ph type="title"/>', "Backup plan")
                                 + shape.format("", "Daily at 02:30") + '</p:spTree></p:cSld></p:sld>',
        "ppt/slides/_rels/slide1.xml.rels": rel.format('<Relationship Id="rId2" Target="../notesSlides/notesSlide1.xml" Type="x"/>'),
        "ppt/notesSlides/notesSlide1.xml": f'<p:notes {p}><p:cSld><p:spTree>' + shape.format("", "Ask the on-call first")
                                           + '</p:spTree></p:cSld></p:notes>'})


def _odf(body: str) -> bytes:
    return _zip({"mimetype": "application/vnd.oasis.opendocument.text",
                 "content.xml": f'<office:document-content {ODF_NS}><office:body>{body}</office:body></office:document-content>'})


def test_docx_keeps_headings_links_lists_and_tables():
    d = df.convert(_docx(), "runbook.docx")
    assert "# Runbook" in d.markdown and "[wiki](https://example.org/wiki)" in d.markdown and "- stop postfix" in d.markdown
    assert "| Host | Size |" in d.markdown and "| mail01 | 120 GB |" in d.markdown
    assert "- stop postfix\n\n| Host" in d.markdown  # a table never continues a list item


def test_xlsx_one_table_per_sheet_hidden_sheets_named():
    d = df.convert(_xlsx(), "hosts.xlsx")
    assert "## Hosts" in d.markdown and "| Host | Size |" in d.markdown and "| mail01 |  | 120 |" in d.markdown
    assert "Secret" not in d.markdown and any("hidden sheet Secret" in n for n in d.notes)


def test_pptx_slides_with_title_text_and_notes():
    d = df.convert(_pptx(), "deck.pptx")
    assert "## Slide 1: Backup plan" in d.markdown and "- Daily at 02:30" in d.markdown and "Notes: Ask the on-call first" in d.markdown


def test_odt_ods_odp():
    odt = df.convert(_odf('<office:text><text:h text:outline-level="2">Restore</text:h><text:p>Run <text:a xlink:href="https://x.org">it</text:a>'
                          '<text:s text:c="2"/>now</text:p><text:list><text:list-item><text:p>one</text:p>'
                          '<text:list><text:list-item><text:p>nested</text:p></text:list-item></text:list></text:list-item></text:list>'
                          '<table:table table:name="T"><table:table-row><table:table-cell><text:p>a</text:p></table:table-cell>'
                          '<table:table-cell table:number-columns-repeated="16000"/></table:table-row>'
                          '<table:table-row><table:table-cell><text:p>b</text:p></table:table-cell></table:table-row></table:table>'
                          '</office:text>'), "doc.odt")
    md = odt.markdown
    assert "## Restore" in md and "Run [it](https://x.org)  now" in md  # text:s c=2: two spaces and "- one" in md and "  - nested" in md and "| a |" in md
    assert "|---|\n| b |" in md  # 16,000 repeated empty cells do not become 16,000 columns
    ods = df.convert(_odf('<office:spreadsheet><table:table table:name="Hosts"><table:table-row><table:table-cell><text:p>Host</text:p>'
                          '</table:table-cell></table:table-row><table:table-row><table:table-cell><text:p>mail01</text:p>'
                          '</table:table-cell></table:table-row></table:table></office:spreadsheet>'), "s.ods")
    assert ods.fmt == "ods" and "## Hosts" in ods.markdown and "| mail01 |" in ods.markdown
    odp = df.convert(_odf('<office:presentation><draw:page draw:name="p1"><draw:frame presentation:class="title"><draw:text-box>'
                          '<text:p>Plan</text:p></draw:text-box></draw:frame><draw:frame presentation:class="outline"><draw:text-box>'
                          '<text:p>Step one</text:p></draw:text-box></draw:frame></draw:page></office:presentation>'), "p.odp")
    assert odp.fmt == "odp" and "## Slide 1: Plan" in odp.markdown and "- Step one" in odp.markdown


def test_html_epub_eml_csv_text():
    h = df.convert(b"<html><head><title>T</title><script>x()</script></head><body><h2>Sec</h2><p>A <a href='https://e.org'>link</a>"
                   b" and [1] stays</p><table><tr><th>k</th><th>v</th></tr><tr><td>a</td><td>1</td></tr></table></body></html>", "p.html")
    assert h.title == "T" and "## Sec" in h.markdown and "[link](https://e.org)" in h.markdown and "[1] stays" in h.markdown
    assert "x()" not in h.markdown and "| a | 1 |" in h.markdown
    ep = df.convert(_zip({"META-INF/container.xml": '<container><rootfiles><rootfile full-path="o/c.opf"/></rootfiles></container>',
                          "o/c.opf": '<package><metadata><title>Book</title></metadata><manifest><item id="a" href="c1.xhtml"/></manifest>'
                                     '<spine><itemref idref="a"/></spine></package>',
                          "o/c1.xhtml": "<html><body><h1>Chapter</h1><p>Text</p></body></html>"}), "b.epub")
    assert ep.title == "Book" and "# Chapter" in ep.markdown
    from email.message import EmailMessage
    m = EmailMessage()
    m["Subject"], m["From"] = "Outage", "ops@example.org"
    m.set_content("The relay is down.")
    m.add_attachment(b"x", maintype="application", subtype="octet-stream", filename="log.zip")
    e = df.convert(m.as_bytes(), "mail.eml")
    assert e.title == "Outage" and "The relay is down." in e.markdown and "attachment not imported: log.zip" in e.markdown
    c = df.convert("Host;Größe\nmail01;120\n".encode("utf-8"), "t.csv")
    assert "| Host | Größe |" in c.markdown and "| mail01 | 120 |" in c.markdown
    assert df.convert("ä Text".encode("cp1252"), "old.txt").markdown == "ä Text"  # not UTF-8: decoded as cp1252, not dropped


def test_every_refusal_has_a_class_and_a_reason(monkeypatch):
    def refused(data, name):
        with pytest.raises(df.Refused) as e:
            df.convert(data, name)
        assert e.value.reason
        return e.value.kind
    assert refused(b"x", "a.xyz") == "unknown format"
    assert refused(b"x", "photo.png") == "unknown format"
    assert refused(b"not a zip", "a.docx") == "unreadable"
    assert refused(_zip({"word/document.xml": "<broken"}), "a.docx") == "unreadable"
    assert refused(b"   \n", "empty.txt") == "no text"
    monkeypatch.setattr(df, "UNZIP_MAX", 10)
    assert refused(_docx(), "big.docx") == "too large"
    monkeypatch.undo()
    monkeypatch.setattr(df, "libreoffice", lambda: None)
    assert refused(b"\xd0\xcf\x11\xe0", "old.doc") == "needs LibreOffice"
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError(n)) if n == "pypdf" else real(n, *a, **k))
    assert refused(b"%PDF-1.4", "a.pdf") == "needs pypdf"


def test_pdf_text_layer_and_scans():
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    b = io.BytesIO()
    w.write(b)
    with pytest.raises(df.Refused) as e:
        df.convert(b.getvalue(), "scan.pdf")
    assert e.value.kind == "no text" and "OCR" in e.value.reason


def test_pages_from_a_directory_name_every_file(tmp_path):
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "runbook.docx").write_bytes(_docx())
    (tmp_path / "notes.md").write_text("# Notes\n\ntext", encoding="utf-8")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG")
    (tmp_path / "ops" / "~$runbook.docx").write_bytes(b"lock")
    pages, refused = df.pages_from_paths([tmp_path])
    by_id = {p["page_id"]: p for p in pages}
    assert set(by_id) == {"ops/runbook.docx", "notes.md"} and by_id["ops/runbook.docx"]["labels"] == ["format-docx"]
    assert by_id["notes.md"]["markdown"].startswith("# Notes") and by_id["ops/runbook.docx"]["area"] == "ops"
    assert [r["kind"] for r in refused] == ["unknown format"] and refused[0]["file"].endswith("photo.png")


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_real_files_written_by_libreoffice(tmp_path):
    """Round trip: one reference document, written by LibreOffice as docx, odt, rtf, doc, pdf — every converter finds its content."""
    src = tmp_path / "ref.html"
    src.write_text("<html><head><meta charset='utf-8'><title>Ref</title></head><body><h1>Runbook Größe</h1><p>täglich 02:30</p>"
                   "<table><tr><td>mail01</td><td>120 GB</td></tr></table></body></html>", encoding="utf-8")
    prof = f"-env:UserInstallation=file://{tmp_path}/profile"
    subprocess.run(["soffice", prof, "--headless", "--convert-to", "odt", "--outdir", str(tmp_path), str(src)], capture_output=True, timeout=180)
    for ext in ("docx", "rtf", "doc", "pdf"):
        subprocess.run(["soffice", prof, "--headless", "--convert-to", ext, "--outdir", str(tmp_path), str(tmp_path / "ref.odt")],
                       capture_output=True, timeout=180)
    for ext in ("odt", "docx", "rtf", "doc") + (("pdf",) if _has("pypdf") else ()):
        md = df.convert((tmp_path / f"ref.{ext}").read_bytes(), f"ref.{ext}").markdown
        assert "Runbook Größe" in md and "täglich 02:30" in md and "mail01" in md and "120 GB" in md, ext


def _has(mod):
    try:
        __import__(mod)
        return True
    except ImportError:
        return False
