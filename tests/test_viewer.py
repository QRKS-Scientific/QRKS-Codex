import base64
import json
import os

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from rdkit import Chem

from qrksdock import paths
from qrksdock.gui.viewer import HTML_TEMPLATE, MolViewer, _draw_molecule_data


def test_bundled_3dmol_javascript_loads():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    assert paths.asset("vendor", "3dmol", "3Dmol-min.js").is_file()
    assert 'src="vendor/3dmol/3Dmol-min.js"' in HTML_TEMPLATE
    app = QApplication.instance() or QApplication([])
    viewer = MolViewer()
    loop = QEventLoop()
    result = {}

    def on_timeout():
        result.setdefault("error", "Viewer page load timed out")
        loop.quit()

    def on_library_loaded(available):
        result["available"] = available
        loop.quit()

    def on_load(ok):
        if not ok:
            result["error"] = "Viewer page failed to load"
            loop.quit()
            return
        viewer.web.page().runJavaScript(
            "typeof $3Dmol !== 'undefined' && typeof $3Dmol.createViewer === 'function'",
            on_library_loaded,
        )

    viewer.web.loadFinished.connect(on_load)
    QTimer.singleShot(30000, on_timeout)
    loop.exec()
    app.processEvents()
    viewer.close()
    assert "error" not in result, result.get("error")
    assert result["available"], "Bundled 3Dmol.js did not expose createViewer"


def test_diagram_draws_nh2_hydrogens_as_separate_atoms():
    molecule = Chem.MolFromSmiles("NCC(=O)N")
    assert molecule is not None

    data = _draw_molecule_data(molecule, 420, 280)

    nitrogen_indices = {
        atom_index for atom_index, atom in enumerate(data["atoms"])
        if atom["element"] == "N"
    }
    hydrogen_atoms = [
        atom for atom in data["atoms"]
        if atom["element"] == "H"
    ]
    assert len(hydrogen_atoms) == 4
    assert all(len(atom["neighbors"]) == 1 for atom in hydrogen_atoms)
    assert all(atom["neighbors"][0] in nitrogen_indices for atom in hydrogen_atoms)
    assert len(data["atom_points"]) == len(data["atoms"])
    assert all(
        data["atom_points"][hydrogen_index] != data["atom_points"][atom["neighbors"][0]]
        for hydrogen_index, atom in enumerate(data["atoms"])
        if atom["element"] == "H"
    )


def test_ligand_and_residue_diagrams_use_the_same_bond_length():
    molecule = Chem.MolFromSmiles("CCO")
    assert molecule is not None

    ligand_data = _draw_molecule_data(molecule, 420, 280)
    residue_data = _draw_molecule_data(molecule, 180, 120)

    def bond_lengths(data):
        return [
            (
                (data["atom_points"][bond.GetBeginAtomIdx()]["x"] -
                 data["atom_points"][bond.GetEndAtomIdx()]["x"]) ** 2
                + (data["atom_points"][bond.GetBeginAtomIdx()]["y"] -
                   data["atom_points"][bond.GetEndAtomIdx()]["y"]) ** 2
            ) ** 0.5
            for bond in molecule.GetBonds()
        ]

    assert bond_lengths(ligand_data) == pytest.approx(bond_lengths(residue_data))


def test_2d_png_export_preserves_edits_and_removes_editing_handles():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    viewer = MolViewer()
    loop = QEventLoop()
    result = {}

    def finish():
        loop.quit()

    def on_timeout():
        result.setdefault("error", "Qt WebEngine export timed out")
        finish()

    def on_png(data_url):
        if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
            result["error"] = f"PNG export failed: {data_url!r}"
            finish()
            return
        image = QImage.fromData(base64.b64decode(data_url.split(",", 1)[1], validate=True))
        result["size"] = (image.width(), image.height())
        result["white_background"] = image.pixelColor(0, 0) == QColor("#ffffff")
        result["has_diagram"] = any(
            image.pixelColor(x, y) != QColor("#ffffff")
            for y in range(560, 640)
            for x in range(850, 1050)
        )
        finish()

    def on_svg(svg):
        result["svg"] = svg
        viewer.export_2d_png(on_png)

    def on_mutation(_):
        viewer.web.page().runJavaScript("window.export2DSVG();", on_svg)

    def on_diagram(_):
        viewer.web.page().runJavaScript(
            """
            (() => {
                const root = document.getElementById('poseview-canvas');
                document.querySelector('.diagram-draggable').setAttribute('transform', 'translate(17 19)');
                const rotate = document.createElementNS(root.namespaceURI, 'g');
                rotate.setAttribute('class', 'diagram-rotate-handle');
                root.appendChild(rotate);
                const edit = document.createElementNS(root.namespaceURI, 'circle');
                edit.setAttribute('class', 'hydrophobic-edit-handle');
                root.appendChild(edit);
                const hitArea = document.createElementNS(root.namespaceURI, 'rect');
                hitArea.setAttribute('fill', 'transparent');
                root.appendChild(hitArea);
            })();
            """,
            on_mutation,
        )

    def on_load(ok):
        if not ok:
            result["error"] = "Viewer page failed to load"
            finish()
            return
        molecule = Chem.MolFromSmiles("CCO")
        assert molecule is not None
        payload = json.dumps(_draw_molecule_data(molecule, 420, 280))
        thresholds = json.dumps({
            "contact": 4.0, "polar": 3.5, "pi_stacking": 5.5,
            "pi_parallel_angle": 30.0, "pi_edge_on_angle": 60.0, "cation_pi": 6.0,
        })
        viewer.web.page().runJavaScript(
            f"window.show2DView({payload}, [], [], {thresholds});",
            on_diagram,
        )

    viewer.web.loadFinished.connect(on_load)
    QTimer.singleShot(30000, on_timeout)
    loop.exec()
    app.processEvents()
    viewer.close()
    assert "error" not in result, result.get("error")
    assert "translate(17 19)" in result["svg"]
    assert "diagram-rotate-handle" not in result["svg"]
    assert "hydrophobic-edit-handle" not in result["svg"]
    assert 'fill="transparent"' not in result["svg"]
    assert 'font-family="-apple-system, sans-serif"' in result["svg"]
    assert result["size"] == (1920, 1200)
    assert result["white_background"]
    assert result["has_diagram"]
