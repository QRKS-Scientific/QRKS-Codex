"""Branded PDF technical report (clinical/institutional track: no mascot).

Rules from the QRKS portfolio, enforced here:
  * The Integrity Seal appears only when the ticket's QA audit has passed AND the Technical
    Lead has signed. Never on drafts, never on test tickets.
  * Deliverables stay watermarked until the Finance Lead clears the balance.
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
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from qrksdock import __version__, brand, paths
from qrksdock.core import rules
from qrksdock.core.pipeline import Project

P = brand.ACTIVE
C_BLUE, C_SKY, C_YELLOW = colors.HexColor(P.blue), colors.HexColor(P.sky), colors.HexColor(P.yellow)
C_INK, C_MUTED, C_BORDER = colors.HexColor(P.ink), colors.HexColor(P.muted), colors.HexColor(P.border)
C_CANVAS = colors.HexColor(P.canvas)


def _register_fonts() -> tuple[str, str, str]:
    """Return (regular, semibold, bold) font names; fall back to Helvetica if the TTFs are missing."""
    fdir = paths.asset("fonts")
    try:
        for name, file in (("Mont", "Montserrat-Regular.ttf"), ("Mont-SB", "Montserrat-SemiBold.ttf"),
                           ("Mont-B", "Montserrat-Bold.ttf")):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(fdir / file)))
        pdfmetrics.registerFontFamily("Mont", normal="Mont", bold="Mont-B", italic="Mont", boldItalic="Mont-B")
        return "Mont", "Mont-SB", "Mont-B"
    except Exception:                                                  # noqa: BLE001
        return "Helvetica", "Helvetica-Bold", "Helvetica-Bold"


def _styles(reg: str, sb: str, bold: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=21, leading=25, textColor=C_BLUE, spaceAfter=3),
        "sub": ParagraphStyle("sub", fontName=reg, fontSize=9.5, leading=13, textColor=C_MUTED),
        "h2": ParagraphStyle("h2", fontName=sb, fontSize=12.5, leading=16, textColor=C_BLUE, spaceBefore=14, spaceAfter=5),
        "h3": ParagraphStyle("h3", fontName=sb, fontSize=10, leading=13, textColor=C_INK, spaceBefore=6, spaceAfter=2),
        "body": ParagraphStyle("body", fontName=reg, fontSize=8.8, leading=12.6, textColor=C_INK, alignment=TA_LEFT),
        "small": ParagraphStyle("small", fontName=reg, fontSize=7.4, leading=10, textColor=C_MUTED),
        "cell": ParagraphStyle("cell", fontName=reg, fontSize=8, leading=10.5, textColor=C_INK),
        "cellb": ParagraphStyle("cellb", fontName=sb, fontSize=8, leading=10.5, textColor=C_INK),
        "th": ParagraphStyle("th", fontName=sb, fontSize=8, leading=10.5, textColor=colors.white),
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
        d.drawOptions().setBackgroundColour((1, 1, 1, 0))
        d.DrawMolecule(mol)
        d.FinishDrawing()
        return d.GetDrawingText()
    except Exception:                                                  # noqa: BLE001
        return None


def _p(text, style):
    return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _status_line(state: dict) -> str:
    if state["test"]:
        return "TEST TICKET - not a client deliverable"
    if state["watermark"]:
        return "WATERMARKED PREVIEW - final files are released after the balance is settled"
    return "Final deliverable" if state["seal"] else "Final files released - QA audit or signature still pending"


def generate_report(project: Project, actor: str, out_path: Path | None = None) -> Path:
    t = project.ticket
    t.check_can_report(actor)
    results = project.best_per_ligand()
    if not results:
        raise ValueError("Run docking before generating a report.")
    rstate = t.report_state()
    reg, sb, bold = _register_fonts()
    S = _styles(reg, sb, bold)
    s = project.s
    allres = project.results
    params = s.get("dock_params", {})
    box = project.box
    val = project.validation
    suffix = "_TEST" if rstate["test"] else ("_PREVIEW" if rstate["watermark"] else "")
    out_path = out_path or (t.sub("reports") / f"{t.id}_QRKSDock_Technical_Report{suffix}.pdf")

    logo = paths.asset("logos", "qrks_horizontal.png")
    seal = paths.asset("logos", "emblem.png")
    watermark_text = "TEST - NOT FOR RELEASE" if rstate["test"] else ("WATERMARKED PREVIEW" if rstate["watermark"] else "")

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
        canvas.drawImage(str(logo), 18 * mm, h - 19 * mm, width=33 * mm, height=33 * mm * 0.3049, mask="auto")
        canvas.setFont(sb, 8)
        canvas.setFillColor(C_MUTED)
        canvas.drawRightString(w - 18 * mm, h - 14 * mm, f"QRKSDock Technical Report  |  {t.id}")
        canvas.setStrokeColor(C_SKY)
        canvas.setLineWidth(1.4)
        canvas.line(18 * mm, h - 22 * mm, w - 18 * mm, h - 22 * mm)
        canvas.setFont(reg, 7.2)
        canvas.drawString(18 * mm, 11 * mm, f"QRKS Scientific  |  {brand.TAGLINE}")
        canvas.drawRightString(w - 18 * mm, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=28 * mm, bottomMargin=18 * mm, title=f"QRKSDock Technical Report {t.id}",
                          author="QRKS Scientific", subject="Molecular docking technical report")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])
    W = doc.width
    story: list = []

    # ---- title block ------------------------------------------------------------------------
    story += [Paragraph("Molecular Docking Technical Report", S["title"]),
              Paragraph("Protein-ligand docking with AutoDock Vina", S["sub"]), Spacer(1, 8)]
    meta = [
        [_p("Ticket", S["cellb"]), _p(t.id, S["cell"]), _p("Package tier", S["cellb"]), _p(t.tier, S["cell"])],
        [_p("Prepared by", S["cellb"]), _p(f"{actor} ({rules.role_of(actor)})", S["cell"]),
         _p("Report date", S["cellb"]), _p(datetime.now(timezone.utc).strftime("%d %B %Y"), S["cell"])],
        [_p("Run ID", S["cellb"]), _p(s.get("run_id", "n/a"), S["cell"]), _p("Status", S["cellb"]), _p(_status_line(rstate), S["cell"])],
    ]
    story.append(_table(meta, [24 * mm, 56 * mm, 26 * mm, W - 106 * mm], header=False, zebra=False))

    # ---- summary ---------------------------------------------------------------------------------
    n_small = sum(1 for r in results if r.kind == "small_molecule")
    n_pep = len(results) - n_small
    story.append(Paragraph("1. Binding affinity summary", S["h2"]))
    story.append(_p(f"{len(results)} ligand{'s' if len(results) != 1 else ''} docked ({n_small} small molecule{'s' if n_small != 1 else ''}, "
                    f"{n_pep} peptide{'s' if n_pep != 1 else ''}). Binding affinity is the "
                    "Vina score of the top-ranked pose in kcal/mol; more negative scores are predicted to bind more strongly. "
                    "Scores are computational estimates and do not by themselves establish binding or biological activity.", S["body"]))
    story.append(Spacer(1, 6))
    rows = [[_p(h, S["th"]) for h in ("Rank", "Ligand", "Type", "Affinity (kcal/mol)", "Est. pKd", "Contact residues", "Polar contacts")]]
    for i, r in enumerate(results, 1):
        rows.append([_p(i, S["cell"]), _p(project.display_state(r), S["cellb"]), _p(r.kind.replace("_", " "), S["cell"]),
                     _p(f"{r.best_affinity:.2f}", S["cellb"]), _p(f"{r.pkd:.2f}", S["cellb"]),
                     _p(len(r.contact_residues), S["cell"]), _p(len(r.polar_contacts), S["cell"])])
    story.append(_table(rows, [14 * mm, 42 * mm, 24 * mm, 30 * mm, 20 * mm, 24 * mm, W - 154 * mm], highlight_row=1))
    story.append(Spacer(1, 4))
    story.append(_p("Estimated pKd = -dG / (2.303 R T), with dG the Vina score and T = 298.15 K. Vina scores carry an error of roughly 2 kcal/mol "
                    "(about 1.5 pKd units), so this value is for ranking ligands and is not a measured affinity.", S["small"]))

    # ---- validation -----------------------------------------------------------------------------
    story.append(Paragraph("2. Method validation (redocking)", S["h2"]))
    if val:
        verdict = "passed" if val.passed else "did not pass"
        story.append(_p(f"The co-crystal reference ligand was redocked with identical settings. Validation {verdict}: the top-ranked pose "
                        f"lies {val.rmsd_top:.2f} Å (heavy-atom RMSD, symmetry-corrected) from the crystal pose against an acceptance "
                        f"threshold of {val.threshold:.1f} Å. The closest of {val.n_poses} poses was {val.rmsd_best:.2f} Å "
                        f"(pose {val.best_pose}). Reference top-pose affinity: {val.affinity_top:.2f} kcal/mol.", S["body"]))
        if not val.passed:
            story.append(Spacer(1, 4))
            story.append(_p("Because redocking did not reproduce the crystal pose, the docking protocol should be interpreted with "
                            "caution. Common causes are removed cofactors or ions that shape the pocket, and receptor flexibility.", S["body"]))
    else:
        story.append(_p("No redocking validation was performed for this run. The reported affinities have not been benchmarked "
                        "against a known co-crystal pose.", S["body"]))

    # ---- methods ------------------------------------------------------------------------------------
    rec = s["receptor"]
    removed = ", ".join(f"{k} x{v}" for k, v in rec["removed"].items()) or "none"
    states = ", ".join(f"{k} x{v}" for k, v in rec["residue_states"].items()) or "n/a"
    prot = (f"pdb2pqr with PROPKA at pH {rec['ph']}" if rec["method"] == "pdb2pqr"
            else "supplied by the user (structure already protonated)")
    story.append(Paragraph("3. Methods", S["h2"]))
    method_rows = [
        ["Receptor", f"Chains {', '.join(rec['chains_kept'])} of the supplied structure. Removed: {removed}. Protonation: {prot}. Titratable residue states: {states}."],
        ["Ligands", f"Protonated at pH {params.get('ph', 7.4)} and converted to 3D with the Scrubber, then prepared with Meeko. "
                    f"Stereochemistry policy: {s.get('stereo_policy', 'warn')}. Peptides were built from sequence (L-amino acids, free termini)."],
        ["Search box", box.summary() if box else "n/a"],
        ["Docking", f"AutoDock Vina {s.get('vina_version', '')}: exhaustiveness {params.get('exhaustiveness')}, up to {params.get('num_modes')} poses per ligand, "
                    f"energy range {params.get('energy_range')} kcal/mol, {params.get('cpu')} CPU thread(s). Vina chose its random seed automatically "
                    "for each ligand; the seeds are recorded in the run manifest. The receptor was treated as rigid and ligand torsions were flexible. "
                    "The complete Vina output (vina_output.log) is delivered with this report."],
    ]
    story.append(_table([[_p(a, S["cellb"]), _p(b, S["cell"])] for a, b in method_rows], [24 * mm, W - 24 * mm], header=False, zebra=False))

    # ---- per ligand -------------------------------------------------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("4. Results by ligand", S["h2"]))
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
        strip = Table([[_p("Pose", S["cellb"])] + [_p(k + 1, S["cellb"]) for k in range(len(r.affinities))],
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
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(KeepTogether(block))

    # ---- limitations -------------------------------------------------------------------------------------------
    story.append(Paragraph("5. Limitations", S["h2"]))
    for line in (
        "Docking scores approximate binding free energy and are best used to rank and compare ligands against the same receptor, not as absolute measurements.",
        "The receptor was held rigid, and waters, ions and cofactors were removed unless stated otherwise in Methods.",
        "Peptides of five or six residues are highly flexible, and pose reliability decreases as flexibility increases.",
        "Contact residues and polar contacts are listed by simple distance cutoffs. They are candidates for inspection, not a validated interaction profile.",
        "Experimental testing is required to confirm binding or activity."):
        story.append(_p("- " + line, S["body"]))

    # ---- reproducibility ------------------------------------------------------------------------------------------
    story.append(Paragraph("6. Reproducibility", S["h2"]))
    man_path = t.sub("results") / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
    env = man.get("environment", {})
    story.append(_p(f"Run ID {man.get('run_id', 'n/a')}. The run manifest (manifest.json in the ticket folder) records software versions, all parameters, "
                    "the random seed, and SHA-256 hashes of the inputs and outputs, so this analysis can be repeated and verified.", S["body"]))
    story.append(Spacer(1, 5))
    sw = [[_p(k, S["cellb"]), _p(v, S["cell"])] for k, v in env.items() if k in ("qrksdock", "autodock_vina", "rdkit", "meeko", "molscrub", "pdb2pqr", "propka")]
    if sw:
        story.append(_table(sw, [40 * mm, W - 40 * mm], header=False))

    # ---- sign-off -----------------------------------------------------------------------------------------------------
    f = rstate["flags"]
    sign_rows = [[_p("Technical Lead (LEM)", S["cellb"]), _p("Signed" if f["report_signed"] else "Signature pending", S["cell"])],
                 [_p("QA audit (JER)", S["cellb"]), _p("Passed" if f["qa_passed"] else "Pending", S["cell"])]]
    sign = _table(sign_rows, [42 * mm, 46 * mm], header=False, zebra=False)
    if rstate["seal"]:
        seal_cell = [Image(str(seal), width=26 * mm, height=26 * mm * 1000 / 897), _p("QRKS Scientific Integrity Seal", S["small"])]
    else:
        seal_cell = [_p("The Integrity Seal is applied only after the QA audit is passed and the Technical Lead has signed.", S["small"])]
    story.append(Paragraph("7. Sign-off", S["h2"]))
    block = Table([[sign, seal_cell]], colWidths=[W - 60 * mm, 60 * mm])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether(block))
    story.append(Spacer(1, 10))
    story.append(_p("QRKS Scientific provides computational infrastructure and technical advisory support. This report presents "
                    "computational results and methods; it does not draft or interpret the client's manuscript.", S["small"]))
    doc.build(story)
    t.add_event(actor, "report_generated", {"file": out_path.name, "seal": rstate["seal"], "watermark": rstate["watermark"]})
    return out_path
