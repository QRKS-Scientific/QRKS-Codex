"""Branded PDF technical report (clinical/institutional track: no mascot).

A report is either a DRAFT (diagonal watermark on every page) or FINAL (no watermark). The person
generating it chooses; the app does not decide. There is no Integrity Seal.
The report states results and methods only. It does not interpret results for the client.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from qrksdock import __version__, brand, paths
from qrksdock.core import rules
from qrksdock.core.pipeline import Project

P = brand.ACTIVE
C_BLUE, C_SKY, C_YELLOW = colors.HexColor(P.blue), colors.HexColor(P.sky), colors.HexColor(P.yellow)
C_INK, C_MUTED, C_BORDER = colors.HexColor(P.ink), colors.HexColor(P.muted), colors.HexColor(P.border)
C_CANVAS = colors.HexColor(P.canvas)


def _register_fonts() -> tuple[str, str, str, str, str]:
    """Register the Public Sans faces used by report text and return their names."""
    fdir = paths.asset("fonts")
    faces = (
        ("PublicSans-Regular", "PublicSans-Regular.ttf"),
        ("PublicSans-Medium", "PublicSans-Medium.ttf"),
        ("PublicSans-Bold", "PublicSans-Bold.ttf"),
        ("PublicSans-ExtraBold", "PublicSans-ExtraBold.ttf"),
        ("PublicSans-Italic", "PublicSans-Italic.ttf"),
        ("PublicSans-BoldItalic", "PublicSans-BoldItalic.ttf"),
    )
    for name, file in faces:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fdir / file)))
    pdfmetrics.registerFontFamily("PublicSans", normal="PublicSans-Regular", bold="PublicSans-Bold",
                                  italic="PublicSans-Italic", boldItalic="PublicSans-BoldItalic")
    return ("PublicSans-Regular", "PublicSans-Medium", "PublicSans-Bold",
            "PublicSans-ExtraBold", "PublicSans-Italic")


def _styles(reg: str, medium: str, bold: str, extra_bold: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName=extra_bold, fontSize=21, leading=25, textColor=C_BLUE, spaceAfter=3),
        "sub": ParagraphStyle("sub", fontName=reg, fontSize=9.5, leading=13, textColor=C_MUTED),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12.5, leading=16, textColor=C_BLUE, spaceBefore=14, spaceAfter=5),
        "h3": ParagraphStyle("h3", fontName=bold, fontSize=10, leading=13, textColor=C_INK, spaceBefore=6, spaceAfter=2),
        "body": ParagraphStyle("body", fontName=reg, fontSize=8.8, leading=12.6, textColor=C_INK, alignment=TA_LEFT),
        "small": ParagraphStyle("small", fontName=reg, fontSize=7.4, leading=10, textColor=C_MUTED),
        "cell": ParagraphStyle("cell", fontName=reg, fontSize=8, leading=10.5, textColor=C_INK),
        "cellm": ParagraphStyle("cellm", fontName=medium, fontSize=8, leading=10.5, textColor=C_INK),
        "signatory": ParagraphStyle("signatory", fontName=medium, fontSize=9, leading=11, textColor=C_INK),
        "th": ParagraphStyle("th", fontName=bold, fontSize=8, leading=10.5, textColor=colors.white),
    }


def _table(data, col_widths, header=True, zebra=True, highlight_row=None):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, C_BORDER),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), C_BLUE)]
    if zebra:
        for r in range(1 if header else 0, len(data)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), C_CANVAS))
    if highlight_row is not None:
        style.append(("BACKGROUND", (0, highlight_row), (-1, highlight_row), colors.HexColor("#FDF1C9")))
    t.setStyle(TableStyle(style))
    return t


def _structure_png(smiles: str) -> bytes | None:
    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
        mol = Chem.MolFromSmiles(smiles)
        d = rdMolDraw2D.MolDraw2DCairo(330, 230)
        options = d.drawOptions()
        options.fontFile = str(paths.asset("fonts", "PublicSans-Regular.ttf"))
        options.setBackgroundColour((1, 1, 1, 0))
        d.DrawMolecule(mol)
        d.FinishDrawing()
        return d.GetDrawingText()
    except Exception:                                                  # noqa: BLE001
        return None


def _p(text, style):
    return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _compact_display_name(display_name: str) -> str:
    name, separator, credential = display_name.partition(",")
    parts = name.split()
    if not parts:
        return display_name
    compact = "".join(f"{part[0]}." for part in parts[:-1]) + parts[-1]
    return f"{compact}, {credential.strip()}" if separator else compact


def generate_report(project: Project, actor: str, final: bool = False, out_path: Path | None = None) -> Path:
    t = project.run
    results = project.best_per_ligand()
    if not results:
        raise ValueError("Run docking before generating a report.")
    reg, medium, bold, extra_bold, italic = _register_fonts()
    S = _styles(reg, medium, bold, extra_bold)
    s = project.s
    allres = project.results
    params = s.get("dock_params", {})
    box = project.box
    val = project.validation
    out_path = out_path or (t.sub("reports") / f"{t.code}_Technical_Report_{'FINAL' if final else 'DRAFT'}.pdf")

    logo_wordmark = paths.asset("logos", "qrks_horizontal.png")
    cover_art = paths.asset("reports", "report_cover.png")
    watermark_text = "" if final else "DRAFT - NOT FOR RELEASE"

    def on_cover(canvas, doc):
        canvas.saveState()
        canvas.drawImage(str(cover_art), 0, 0, width=A4[0], height=A4[1])
        canvas.restoreState()

    def on_page(canvas, doc):
        w, h = A4
        canvas.saveState()
        if watermark_text:
            canvas.setFillColor(C_BLUE)
            canvas.setFillAlpha(0.07)
            canvas.setFont(bold, 46)
            canvas.translate(w / 2, h / 2)
            canvas.rotate(38)
            canvas.drawCentredString(0, 0, watermark_text)
            canvas.restoreState()
            canvas.saveState()
        canvas.drawImage(str(logo_wordmark), 18 * mm, h - 25 * mm, width=55 * mm, height=55 * mm * 549 / 1800,
                         mask="auto")
        header_x = 82 * mm
        bar_width = w - header_x
        bar_height = 8 * mm
        bar_y = h - 10 * mm - bar_height
        canvas.setFillColor(C_SKY)
        canvas.rect(header_x, bar_y, bar_width * 0.56, bar_height, fill=1, stroke=0)
        canvas.setFillColor(C_YELLOW)
        canvas.rect(header_x + bar_width * 0.56, bar_y, bar_width * 0.44, bar_height, fill=1, stroke=0)
        canvas.setFont(extra_bold, 18)
        canvas.setFillColor(C_BLUE)
        canvas.drawString(header_x, h - 24 * mm, "Docking Test Report")
        canvas.setFont(reg, 8.5)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(header_x, h - 30 * mm, f"Report No. {t.code}")
        footer_text = f"Page {doc.page}  |  "
        footer_size = 7.5
        tagline_size = 8
        footer_width = pdfmetrics.stringWidth(footer_text, reg, footer_size)
        tagline_width = pdfmetrics.stringWidth(brand.TAGLINE, italic, tagline_size)
        footer_x = (w - footer_width - tagline_width) / 2
        canvas.setFont(reg, footer_size)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(footer_x, 11 * mm, footer_text)
        canvas.setFont(italic, tagline_size)
        canvas.drawString(footer_x + footer_width, 11 * mm, brand.TAGLINE)
        canvas.restoreState()

    doc = BaseDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=38 * mm, bottomMargin=18 * mm, title=f"Docking Test Report {t.code}",
                          author="QRKS Scientific", subject="Molecular docking technical report")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    cover_frame = Frame(0, 0, A4[0], A4[1], id="cover",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=on_cover),
        PageTemplate(id="main", frames=[frame], onPage=on_page),
    ])
    W = doc.width
    story: list = [NextPageTemplate("main"), PageBreak()]

    # ---- report metadata ------------------------------------------------------------------------
    meta = [
        [_p("Client code", S["cellm"]), _p(t.client, S["cell"]),
         _p("Report date", S["cellm"]), _p(datetime.now(timezone.utc).strftime("%d %B %Y"), S["cell"])],
        [_p("Prepared by", S["cellm"]), _p(_compact_display_name(rules.display_name_of(actor)), S["cellm"]),
         _p("Run ID", S["cellm"]), _p(s.get("run_id", "n/a"), S["cell"])],
        [_p("Status", S["cellm"]), _p("Final" if final else "Draft (watermarked)", S["cell"]), "", ""],
    ]
    meta_table = _table(meta, [24 * mm, 56 * mm, 26 * mm, W - 106 * mm], header=False, zebra=False)
    meta_table.setStyle(TableStyle([("SPAN", (1, 2), (-1, 2))]))
    story.append(meta_table)

    # ---- summary ---------------------------------------------------------------------------------
    story.append(Paragraph("A. Binding Affinity Summary", S["h2"]))
    story.append(_p(f"{len(results)} ligand{'s' if len(results) != 1 else ''} docked. Binding affinity is the "
                    "Vina score of the top-ranked pose in kcal/mol; more negative scores are predicted to bind more strongly. "
                    "Scores are computational estimates and do not by themselves establish binding or biological activity.", S["body"]))
    story.append(Spacer(1, 6))
    rows = [[_p(h, S["th"]) for h in
             ("Rank", "Ligand", "Affinity (kcal/mol)", "Est. pKd", "Contact residues", "Polar contacts")]]
    for i, r in enumerate(results, 1):
        rows.append([_p(i, S["cell"]), _p(project.display_state(r), S["cellm"]),
                     _p(f"{r.best_affinity:.2f}", S["cellm"]), _p(f"{r.pkd:.2f}", S["cellm"]),
                     _p(len(r.contact_residues), S["cell"]), _p(len(r.polar_contacts), S["cell"])])
    story.append(_table(rows, [14 * mm, 50 * mm, 32 * mm, 24 * mm, 30 * mm, W - 150 * mm], highlight_row=1))
    story.append(Spacer(1, 4))
    story.append(_p("Estimated pKd = -dG / (2.303RT), with dG the Vina score and T = 298.15K.", S["small"]))

    # ---- per ligand -------------------------------------------------------------------------------------
    story.append(Spacer(1, 10))
    story.append(Paragraph("B. Results by Ligand", S["h2"]))
    for r in results:
        png = _structure_png(r.smiles)
        left = [Paragraph(project.display_state(r), S["h3"]),
                _p(f"Best pose {r.best_affinity:.2f} kcal/mol (estimated pKd {r.pkd:.1f}). Poses returned: {len(r.affinities)}.", S["body"]),
                Spacer(1, 3),
                _p(f"Protonation state docked (predicted at pH {params.get('ph', 7.4)}): net charge {r.charge:+d}, "
                   f"{r.rot_bonds} rotatable torsions.", S["body"]),
                Spacer(1, 3),
                _p("Contact residues within 4.0 Å: " + (", ".join(r.contact_residues) or "none"), S["body"]),
                Spacer(1, 3),
                _p("Polar contact candidates (N/O pairs within 3.5 Å): " +
                   ("; ".join(f"{a} to {b} ({d:.2f} Å)" for a, b, d in r.polar_contacts[:6]) or "none"), S["body"])]
        strip = Table([[_p("Pose", S["cellm"])] + [_p(k + 1, S["cellm"]) for k in range(len(r.affinities))],
                       [_p("kcal/mol", S["cell"])] + [_p(f"{a:.2f}", S["cell"]) for a in r.affinities]],
                      colWidths=[15 * mm] + [(W - 48 * mm - 15 * mm) / max(len(r.affinities), 1)] * len(r.affinities))
        strip.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 6.5), ("LINEBELOW", (0, 0), (-1, 0), 0.4, C_BORDER),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        left += [Spacer(1, 4), strip]
        for w_ in r.warnings:
            left += [Spacer(1, 3), _p("Note: " + w_, S["small"])]
        img = Image(io.BytesIO(png), width=42 * mm, height=42 * mm * 230 / 330) if png else _p("", S["small"])
        block = Table([[left, img]], colWidths=[W - 48 * mm, 48 * mm])
        block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.4, C_BORDER),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
        story.append(KeepTogether(block))

    # ---- methods ------------------------------------------------------------------------------------
    rec = s["receptor"]
    removed = ", ".join(f"{k} x{v}" for k, v in rec["removed"].items()) or "none"
    states = ", ".join(f"{k} x{v}" for k, v in rec["residue_states"].items()) or "n/a"
    prot = (f"pdb2pqr with PROPKA at pH {rec['ph']}" if rec["method"] == "pdb2pqr"
            else "supplied by the user (structure already protonated)")
    if val:
        verdict = "passed" if val.passed else "did not pass"
        validation = (f"The co-crystal reference ligand was redocked with identical settings. Validation {verdict}: the top-ranked pose "
                      f"lies {val.rmsd_top:.2f} Å (heavy-atom RMSD, symmetry-corrected) from the crystal pose against an acceptance "
                      f"threshold of {val.threshold:.1f} Å. The closest of {val.n_poses} poses was {val.rmsd_best:.2f} Å "
                      f"(pose {val.best_pose}). Reference top-pose affinity: {val.affinity_top:.2f} kcal/mol.")
        if not val.passed:
            validation += (" Because redocking did not reproduce the crystal pose, the docking protocol should be interpreted with "
                           "caution. Common causes are removed cofactors or ions that shape the pocket, and receptor flexibility.")
    else:
        validation = ("No redocking validation was performed for this run. The reported affinities have not been benchmarked "
                      "against a known co-crystal pose.")
    story.append(Paragraph("C. Methods", S["h2"]))
    method_rows = [
        ["Ligand preparation", f"Protonated at pH {params.get('ph', 7.4)} and converted to 3D with the Scrubber, then prepared with Meeko. "
                               f"Stereochemistry policy: {s.get('stereo_policy', 'warn')}."],
        ["Receptor preparation", f"Chains {', '.join(rec['chains_kept'])} of the supplied structure. Removed: {removed}. Protonation: {prot}. "
                                f"Titratable residue states: {states}."],
        ["Search box", box.summary() if box else "n/a"],
        ["Docking", f"AutoDock Vina {s.get('vina_version', '')}: exhaustiveness {params.get('exhaustiveness')}, up to {params.get('num_modes')} poses per ligand, "
                    f"energy range {params.get('energy_range')} kcal/mol, {params.get('cpu')} CPU thread(s). Vina chose its random seed automatically "
                    "for each ligand; the seeds are recorded in the run manifest. The receptor was treated as rigid and ligand torsions were flexible. "
                    "The complete Vina output (vina_output.log) is delivered with this report."],
        ["Validation", validation],
    ]
    story.append(_table([[_p(a, S["cellm"]), _p(b, S["cell"])] for a, b in method_rows], [24 * mm, W - 24 * mm], header=False, zebra=False))
    story.append(Paragraph("Reproducibility", S["h3"]))
    man_path = t.sub("results") / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    env = man.get("environment", {})
    story.append(_p(f"Run ID {man.get('run_id', 'n/a')}. The run manifest (manifest.json in the run folder) records software versions, all parameters, "
                    "the random seed, and SHA-256 hashes of the inputs and outputs, so this analysis can be repeated and verified.", S["body"]))
    story.append(Spacer(1, 5))
    sw = [[_p("Software", S["th"]), _p("Version", S["th"])]]
    sw.extend([[_p(k, S["cellm"]), _p(v, S["cell"])] for k, v in env.items()
               if k in ("qrksdock", "autodock_vina", "rdkit", "meeko", "molscrub", "pdb2pqr", "propka")])
    if len(sw) > 1:
        story.append(_table(sw, [40 * mm, W - 40 * mm], header=True))
    story.append(Spacer(1, 8))
    story.append(_p("QRKS Scientific provides computational infrastructure and technical advisory support. This report presents "
                    "computational results and methods; it does not draft or interpret the client's manuscript.", S["small"]))

    people = {person["initials"]: person for person in rules.roster()}
    actor_person = people.get(actor, {"display_name": rules.display_name_of(actor),
                                      "role": rules.role_of(actor) or "Docking lead"})

    def signature_block(person: dict[str, str], width: float) -> list:
        signature_line = Table([[""]], colWidths=[width], rowHeights=[14 * mm])
        signature_line.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, C_BORDER)]))
        return [signature_line, _p(person["display_name"], S["signatory"]),
                _p(f"{person['role']}, QRKS Scientific", S["small"])]

    signatories = [signature_block(actor_person, W / 2 - 8 * mm)]
    if actor in people:
        checker = people["JER"] if actor == "LEM" else people["LEM"]
        signatories.append(signature_block(checker, W / 2 - 8 * mm))
    signatory_width = W / len(signatories)
    signatory_table = Table([signatories], colWidths=[signatory_width] * len(signatories))
    signatory_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8 * mm),
    ]))
    story.append(signatory_table)

    story.append(Spacer(1, 12))
    story.append(_p("This report and all data herein are the confidential property of the named client and QRKS Scientific. "
                    "Reproduction in part, without the consent of QRKS Scientific, is not authorized. This report is intended "
                    "for the named client only and may not be distributed to third parties without prior consent from "
                    "QRKS Scientific.", S["small"]))

    doc.build(story)
    t.log(actor, "report_generated", {"file": out_path.name, "final": final})
    return out_path
