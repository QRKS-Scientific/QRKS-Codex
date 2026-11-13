"""3D Molecular Viewer using 3Dmol.js embedded via Qt WebEngine."""
from __future__ import annotations

import json
from typing import Any, Callable

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView

from qrksdock import brand
from qrksdock.core.contacts import DiagramInteraction, ResidueStructure
P = brand.ACTIVE


def _draw_molecule_data(molecule: Chem.Mol, width: int, height: int) -> dict[str, Any]:
    diagram_mol = Chem.Mol(molecule)
    nitrogen_atoms = [
        atom.GetIdx() for atom in diagram_mol.GetAtoms()
        if atom.GetSymbol() == "N" and atom.GetTotalNumHs() >= 2
        and not any(neighbor.GetSymbol() == "H" for neighbor in atom.GetNeighbors())
    ]
    if nitrogen_atoms:
        diagram_mol = Chem.AddHs(diagram_mol, onlyOnAtoms=nitrogen_atoms)
    rdDepictor.Compute2DCoords(diagram_mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    options = drawer.drawOptions()
    options.clearBackground = False
    options.bondLineWidth = 2.2
    options.fixedBondLength = 24
    options.fixedFontSize = 14
    options.multipleBondOffset = 0.18
    drawer.DrawMolecule(diagram_mol)
    drawer.FinishDrawing()
    atoms = []
    for atom in diagram_mol.GetAtoms():
        info = atom.GetPDBResidueInfo()
        atoms.append({
            "name": info.GetName().strip() if info is not None else "",
            "element": atom.GetSymbol().upper(),
            "charge": atom.GetFormalCharge(),
            "neighbors": [neighbor.GetIdx() for neighbor in atom.GetNeighbors()],
        })
    return {
        "width": width,
        "height": height,
        "svg": drawer.GetDrawingText(),
        "atoms": atoms,
        "atom_points": [
            {"x": drawer.GetDrawCoords(atom.GetIdx()).x, "y": drawer.GetDrawCoords(atom.GetIdx()).y}
            for atom in diagram_mol.GetAtoms()
        ],
    }


HTML_TEMPLATE = f"""
<!DOCTYPE html>
<html>
<head>
    <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background-color: {P.surface}; overflow: hidden; font-family: -apple-system, sans-serif; }}
        #container {{ width: 100vw; height: 100vh; position: relative; }}
        #interaction-2d {{ display: none; width: 100vw; height: 100vh; background: #ffffff; padding: 12px; box-sizing: border-box; overflow: auto; text-align: center; }}
        #poseview-canvas {{ display: block; width: 100%; height: calc(100% - 84px); min-height: 280px; }}
        .title-2d {{ font-size: 15px; font-weight: 700; color: #1e429f; margin-bottom: 3px; }}
        .subtitle-2d {{ font-size: 11px; color: #6b7280; margin-bottom: 7px; }}
        .diagram-controls {{ display: flex; justify-content: center; align-items: center; gap: 10px; margin: 0 0 4px; color: #64748b; font-size: 11px; }}
        #reset-2d-layout {{ padding: 3px 9px; border: 1px solid #cbd5e1; border-radius: 4px; background: #ffffff; color: #334155; font: inherit; cursor: pointer; }}
        #reset-2d-layout:hover {{ background: #f1f5f9; }}
        .diagram-rotate-handle {{ opacity: 0.65; cursor: grab; }}
        .diagram-rotate-handle:hover {{ opacity: 1; }}
        .hydrophobic-edit-handle {{ opacity: 0.45; cursor: grab; }}
        .diagram-hydrophobic-target:hover .hydrophobic-edit-handle {{ opacity: 1; }}
    </style>
</head>
<body>
    <div id="container"></div>
    <div id="interaction-2d">
        <div class="title-2d">2D Interaction Diagram</div>
        <div class="subtitle-2d">Distance-based candidates; polar contacts are not validated hydrogen bonds.</div>
        <div class="diagram-controls">
            <span>Drag fragments to move · ↻ rotates residues · Drag brackets or handles to edit</span>
            <button id="reset-2d-layout" type="button">Reset layout</button>
        </div>
        <svg id="poseview-canvas" viewBox="0 0 960 600" role="img" aria-label="Ligand interaction diagram"></svg>
    </div>
    <script>
        let viewer = null;
        let current2DDiagram = null;
        const manual2DLayouts = new Map();
        let viewerSceneVersion = 0;
        let surfaceUpdateVersion = 0;
        let proteinSurfaceId = null;

        function clearViewerScene() {{
            viewerSceneVersion += 1;
            surfaceUpdateVersion += 1;
            proteinSurfaceId = null;
        }}

        function setProteinSurface(enabled) {{
            const sceneVersion = viewerSceneVersion;
            const updateVersion = ++surfaceUpdateVersion;
            if (proteinSurfaceId !== null) {{
                viewer.removeSurface(proteinSurfaceId);
                proteinSurfaceId = null;
            }}
            if (!enabled || !viewer.getModel(0)) return;

            Promise.resolve(viewer.addSurface(
                $3Dmol.SurfaceType.VDW,
                {{opacity: 0.35, color: '#94a3b8'}},
                {{model: 0}}
            )).then(surfaceId => {{
                if (sceneVersion !== viewerSceneVersion) return;
                if (updateVersion !== surfaceUpdateVersion) {{
                    viewer.removeSurface(surfaceId);
                    viewer.render();
                    return;
                }}
                proteinSurfaceId = surfaceId;
                viewer.render();
            }}).catch(error => {{
                if (sceneVersion === viewerSceneVersion && updateVersion === surfaceUpdateVersion) {{
                    console.error('Unable to render molecular surface', error);
                }}
            }});
        }}

        window.onload = function() {{
            let element = document.getElementById('container');
            let config = {{ backgroundColor: '{P.surface}' }};
            viewer = $3Dmol.createViewer(element, config);
            viewer.render();
        }};

        window.loadReceptor = function(modelData, format) {{
            document.getElementById('container').style.display = 'block';
            document.getElementById('interaction-2d').style.display = 'none';
            if (!viewer) return;
            clearViewerScene();
            viewer.clear();
            viewer.addModel(modelData, format);
            viewer.setStyle({{}}, {{cartoon: {{color: '#A0A0A0'}}}});
            viewer.zoomTo();
            viewer.render();
        }};

        window.loadLigand = function(ligData, format) {{
            document.getElementById('container').style.display = 'block';
            document.getElementById('interaction-2d').style.display = 'none';
            if (!viewer) return;
            clearViewerScene();
            viewer.clear();
            viewer.addModel(ligData, format);
            viewer.setStyle({{}}, {{stick: {{colorscheme: 'cyanCarbon', radius: 0.2}}}});
            viewer.zoomTo();
            viewer.render();
        }};

        window.addReference = function(modelData, format) {{
            if (!viewer) return;
            const referenceModel = viewer.addModel(modelData, format);
            referenceModel.setStyle({{}}, {{stick: {{colorscheme: 'cyanCarbon', radius: 0.2}}}});
            viewer.zoomTo();
            viewer.render();
        }};

        window.addBox = function(center, size) {{
            if (!viewer) return;
            if (typeof viewer.addBox === 'function') {{
                viewer.addBox(center, size, {{ color: '#ff4d9d', wireframe: true, opacity: 0.9 }});
                viewer.render();
                return;
            }}
            viewer.render();
        }};

        window.loadComplex = function(recData, ligData, recFormat, ligFormat, showSurf, showCart, showSticks) {{
            document.getElementById('container').style.display = 'block';
            document.getElementById('interaction-2d').style.display = 'none';
            if (!viewer) return;
            clearViewerScene();
            viewer.clear();

            // Receptor
            viewer.addModel(recData, recFormat);
            let recStyle = {{}};
            if (showCart) recStyle.cartoon = {{color: '#A0A0A0', opacity: 0.8}};
            viewer.setStyle({{model: 0}}, recStyle);
            setProteinSurface(showSurf);

            // Ligand - robust fallback with both sticks and spheres to guarantee full visibility
            viewer.addModel(ligData, ligFormat);
            if (showSticks) {{
                viewer.setStyle({{model: 1}}, {{
                    stick: {{colorscheme: 'cyanCarbon', radius: 0.2}}
                }});
            }} else {{
                viewer.setStyle({{model: 1}}, {{hidden: true}});
            }}

            viewer.zoomTo();
            viewer.render();
        }};

        window.export2DSVG = function() {{
            const svg = document.getElementById('poseview-canvas');
            if (!current2DDiagram || !svg || !svg.childElementCount) return null;
            const exported = svg.cloneNode(true);
            exported.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            exported.setAttribute('width', '1920');
            exported.setAttribute('height', '1200');
            exported.setAttribute('font-family', '-apple-system, sans-serif');
            exported.querySelectorAll('.diagram-rotate-handle, .hydrophobic-edit-handle').forEach(node => node.remove());
            exported.querySelectorAll('text').forEach(node =>
                node.setAttribute('font-family', '-apple-system, sans-serif')
            );
            exported.querySelectorAll('rect[fill="transparent"]').forEach(node => node.remove());
            const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            background.setAttribute('width', '100%');
            background.setAttribute('height', '100%');
            background.setAttribute('fill', '#ffffff');
            exported.insertBefore(background, exported.firstChild);
            return new XMLSerializer().serializeToString(exported);
        }};

        window.export2DPNG = function() {{
            window.exported2DPNG = null;
            window.export2DPNGError = null;
            const svg = window.export2DSVG();
            if (!svg) {{
                window.export2DPNGError = 'The current interaction diagram is not ready to export.';
                return;
            }}
            const image = new Image();
            const objectUrl = URL.createObjectURL(new Blob([svg], {{type: 'image/svg+xml'}}));
            image.onload = () => {{
                try {{
                    const canvas = document.createElement('canvas');
                    canvas.width = 1920;
                    canvas.height = 1200;
                    const context = canvas.getContext('2d');
                    if (!context) throw new Error('Could not initialize the PNG canvas.');
                    context.fillStyle = '#ffffff';
                    context.fillRect(0, 0, canvas.width, canvas.height);
                    context.drawImage(image, 0, 0, canvas.width, canvas.height);
                    window.exported2DPNG = canvas.toDataURL('image/png');
                }} catch (error) {{
                    window.export2DPNGError = String(error);
                }} finally {{
                    URL.revokeObjectURL(objectUrl);
                }}
            }};
            image.onerror = () => {{
                window.export2DPNGError = 'The interaction diagram could not be rasterized.';
                URL.revokeObjectURL(objectUrl);
            }};
            image.src = objectUrl;
        }};

        window.show2DView = function(molecule, residueStructures, interactionList, thresholds) {{
            current2DDiagram = null;
            document.getElementById('container').style.display = 'none';
            document.getElementById('interaction-2d').style.display = 'block';
            document.querySelector('.subtitle-2d').textContent =
                `Contact / hydrophobic / salt bridge ≤${{thresholds.contact.toFixed(1)}} Å · ` +
                `polar ≤${{thresholds.polar.toFixed(1)}} Å · π ≤${{thresholds.pi_stacking.toFixed(1)}} Å ` +
                `(parallel ≤${{thresholds.pi_parallel_angle.toFixed(0)}}° or edge-on ≥${{thresholds.pi_edge_on_angle.toFixed(0)}}°) · ` +
                `cation-π ≤${{thresholds.cation_pi.toFixed(1)}} Å. Geometric candidates; polar pairs are not validated H-bonds.`;
            const svg = document.getElementById('poseview-canvas');
            svg.innerHTML = '';
            const ns = 'http://www.w3.org/2000/svg';
            const colors = {{
                polar: '#3b82f6',
                hydrophobic: '#d97706',
                salt_bridge: '#d946ef',
                pi_stacking: '#7c3aed',
                cation_pi: '#2563eb',
                contact: '#94a3b8'
            }};
            const make = (tag, attrs, parent = svg, text = '') => {{
                const el = document.createElementNS(ns, tag);
                Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
                if (text) el.textContent = text;
                parent.appendChild(el);
                return el;
            }};
            if (!molecule || !molecule.atoms || molecule.atoms.length === 0) {{
                make('text', {{x: 480, y: 300, 'text-anchor': 'middle', fill: '#64748b', 'font-size': 16}},
                     svg, 'No ligand structure is available for this pose.');
                return;
            }}
            const layoutKey = JSON.stringify([
                molecule.atoms.map(atom => atom.element),
                (interactionList || []).map(item =>
                    [item.kind, item.residue, item.ligand_atom, item.receptor_atom, item.distance]
                )
            ]);
            current2DDiagram = {{molecule, residueStructures, interactionList, thresholds, layoutKey}};
            const savedLayout = manual2DLayouts.get(layoutKey);
            const layoutState = {{
                ligand: savedLayout ? {{...savedLayout.ligand}} : {{x: 0, y: 0}},
                residues: savedLayout ? {{...savedLayout.residues}} : {{}},
                hydrophobic: savedLayout ? {{...savedLayout.hydrophobic}} : {{}}
            }};
            document.getElementById('reset-2d-layout').onclick = () => {{
                if (!current2DDiagram) return;
                manual2DLayouts.delete(current2DDiagram.layoutKey);
                const diagram = current2DDiagram;
                window.show2DView(diagram.molecule, diagram.residueStructures, diagram.interactionList, diagram.thresholds);
            }};

            const centerX = 480;
            const centerY = 300;
            const structureGroup = document.createElementNS(ns, 'g');
            const links = document.createElementNS(ns, 'g');
            const labels = document.createElementNS(ns, 'g');
            labels.setAttribute('pointer-events', 'none');
            const dragOverlay = document.createElementNS(ns, 'g');
            svg.appendChild(links);
            svg.appendChild(structureGroup);
            svg.appendChild(labels);
            svg.appendChild(dragOverlay);

            const drawMolecule = (data, box, rotation = 0, parent = structureGroup) => {{
                const scale = Math.min(box.width / data.width, box.height / data.height);
                const drawWidth = data.width * scale;
                const drawHeight = data.height * scale;
                const x = box.x + (box.width - drawWidth) / 2;
                const y = box.y + (box.height - drawHeight) / 2;
                const points = data.atom_points.map(point => {{
                    const px = x + point.x * scale;
                    const py = y + point.y * scale;
                    if (!rotation) return {{x: px, y: py}};
                    const radians = rotation * Math.PI / 180;
                    const dx = px - box.cx;
                    const dy = py - box.cy;
                    return {{
                        x: box.cx + dx * Math.cos(radians) - dy * Math.sin(radians),
                        y: box.cy + dx * Math.sin(radians) + dy * Math.cos(radians)
                    }};
                }});
                const parsed = new DOMParser().parseFromString(data.svg, 'image/svg+xml');
                const drawing = document.importNode(parsed.documentElement, true);
                drawing.setAttribute('x', String(box.x));
                drawing.setAttribute('y', String(box.y));
                drawing.setAttribute('width', String(box.width));
                drawing.setAttribute('height', String(box.height));
                drawing.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                drawing.setAttribute('pointer-events', 'none');
                if (rotation) drawing.setAttribute('transform', `rotate(${{rotation}} ${{box.cx}} ${{box.cy}})`);
                parent.appendChild(drawing);
                return points;
            }};
            const dragTargets = [];
            const svgPoint = event => {{
                const point = svg.createSVGPoint();
                point.x = event.clientX;
                point.y = event.clientY;
                const matrix = svg.getScreenCTM();
                return matrix ? point.matrixTransform(matrix.inverse()) : {{x: event.clientX, y: event.clientY}};
            }};
            const rotatePoint = (point, center, degrees) => {{
                const radians = degrees * Math.PI / 180;
                const dx = point.x - center.x;
                const dy = point.y - center.y;
                return {{
                    x: center.x + dx * Math.cos(radians) - dy * Math.sin(radians),
                    y: center.y + dx * Math.sin(radians) + dy * Math.cos(radians)
                }};
            }};
            const addDragTarget = (element, getOffset, setOffset) => {{
                element.style.cursor = 'grab';
                element.style.touchAction = 'none';
                dragTargets.push({{element, getOffset, setOffset}});
            }};
            const addRotateTarget = (element, getCenter, getRotation, setRotation) => {{
                element.style.touchAction = 'none';
                element.addEventListener('pointerdown', event => {{
                    if (event.button !== 0) return;
                    event.preventDefault();
                    event.stopPropagation();
                    const start = svgPoint(event);
                    const center = getCenter();
                    const startAngle = Math.atan2(start.y - center.y, start.x - center.x) * 180 / Math.PI;
                    const initialRotation = getRotation();
                    element.setPointerCapture(event.pointerId);
                    const move = pointerEvent => {{
                        const current = svgPoint(pointerEvent);
                        const angle = Math.atan2(current.y - center.y, current.x - center.x) * 180 / Math.PI;
                        const delta = ((angle - startAngle + 540) % 360) - 180;
                        setRotation((initialRotation + delta + 360) % 360);
                    }};
                    const finish = pointerEvent => {{
                        element.removeEventListener('pointermove', move);
                        element.removeEventListener('pointerup', finish);
                        element.removeEventListener('pointercancel', finish);
                        if (element.hasPointerCapture(pointerEvent.pointerId)) {{
                            element.releasePointerCapture(pointerEvent.pointerId);
                        }}
                    }};
                    element.addEventListener('pointermove', move);
                    element.addEventListener('pointerup', finish);
                    element.addEventListener('pointercancel', finish);
                }});
            }};
            const makeDragGroup = (parent, box, labelSpace = 0) => {{
                const group = document.createElementNS(ns, 'g');
                group.setAttribute('class', 'diagram-draggable');
                parent.appendChild(group);
                make('rect', {{
                    x: box.x - 8, y: box.y - 8, width: box.width + 16,
                    height: box.height + labelSpace + 16, fill: 'transparent', 'pointer-events': 'all'
                }}, group);
                return group;
            }};
            let updateInteractionPositions = () => {{}};
            const saveLayout = () => manual2DLayouts.set(layoutKey, {{
                ligand: {{...layoutState.ligand}},
                residues: {{...layoutState.residues}},
                hydrophobic: {{...layoutState.hydrophobic}}
            }});
            const nearestHydrogenPoint = (atoms, atomIndex, atomPoints, target) => {{
                let nearest = null;
                let nearestDistance = Infinity;
                atoms.forEach((atom, index) => {{
                    if (atom.element !== 'H' || !(atom.neighbors || []).includes(atomIndex)) return;
                    const point = atomPoints[index];
                    const distance = Math.hypot(point.x - target.x, point.y - target.y);
                    if (distance < nearestDistance) {{
                        nearest = point;
                        nearestDistance = distance;
                    }}
                }});
                return nearest;
            }};

            const ligandBox = {{x: centerX - 170, y: centerY - 110, width: 340, height: 220,
                cx: centerX, cy: centerY}};
            const ligandGroup = makeDragGroup(structureGroup, ligandBox);
            const ligandLinkGroup = document.createElementNS(ns, 'g');
            const ligandLabelGroup = document.createElementNS(ns, 'g');
            const hydrophobicDragTargets = [];
            links.appendChild(ligandLinkGroup);
            labels.appendChild(ligandLabelGroup);
            const applyLigandOffset = () => {{
                const transform = `translate(${{layoutState.ligand.x}} ${{layoutState.ligand.y}})`;
                ligandGroup.setAttribute('transform', transform);
                ligandLinkGroup.setAttribute('transform', transform);
                ligandLabelGroup.setAttribute('transform', transform);
                hydrophobicDragTargets.forEach(target => {{
                    const offset = layoutState.hydrophobic[target.residue] || {{x: 0, y: 0}};
                    target.element.setAttribute('transform',
                        `translate(${{layoutState.ligand.x + offset.x}} ${{layoutState.ligand.y + offset.y}})`);
                }});
            }};
            applyLigandOffset();
            addDragTarget(ligandGroup, () => layoutState.ligand, offset => {{
                layoutState.ligand = offset;
                applyLigandOffset();
                updateInteractionPositions();
                saveLayout();
            }});
            const points = drawMolecule(molecule, ligandBox, 0, ligandGroup);
            const uniqueInteractions = new Map();
            const hydrophobicContacts = new Map();
            (interactionList || []).forEach(item => {{
                if (item.ligand_atom < 0 || item.ligand_atom >= molecule.atoms.length) return;
                if (item.kind === 'hydrophobic') {{
                    const key = `${{item.residue}}|${{item.ligand_atom}}`;
                    if (!hydrophobicContacts.has(key) || item.distance < hydrophobicContacts.get(key).distance) {{
                        hydrophobicContacts.set(key, item);
                    }}
                }} else {{
                    const key = ['polar', 'salt_bridge'].includes(item.kind)
                        ? `${{item.kind}}|${{item.residue}}|${{item.ligand_atom}}|${{item.receptor_atom}}`
                        : `${{item.kind}}|${{item.residue}}`;
                    if (!uniqueInteractions.has(key) || item.distance < uniqueInteractions.get(key).distance) {{
                        uniqueInteractions.set(key, item);
                    }}
                }}
            }});
            const interactions = [...uniqueInteractions.values(), ...hydrophobicContacts.values()]
                .sort((a, b) => a.residue.localeCompare(b.residue) || a.kind.localeCompare(b.kind));
            const structuresByResidue = new Map((residueStructures || []).map(item => [item.residue, item]));
            const interactionsByResidue = new Map();
            interactions.forEach(item => {{
                if (!interactionsByResidue.has(item.residue)) interactionsByResidue.set(item.residue, []);
                interactionsByResidue.get(item.residue).push(item);
            }});
            const residueGroups = Array.from(interactionsByResidue, ([residue, items]) => {{
                const anchorPoints = items.map(item => points[item.ligand_atom]);
                const avgX = anchorPoints.reduce((sum, point) => sum + point.x, 0) / anchorPoints.length;
                const avgY = anchorPoints.reduce((sum, point) => sum + point.y, 0) / anchorPoints.length;
                let angle = Math.atan2((avgY - centerY) / 220, (avgX - centerX) / 340);
                if (angle < 0) angle += 2 * Math.PI;
                return {{residue, items, angle}};
            }}).sort((a, b) => a.angle - b.angle);
            if (residueGroups.length > 1) {{
                let startIndex = 0;
                let largestGap = -1;
                residueGroups.forEach((group, index) => {{
                    const nextIndex = (index + 1) % residueGroups.length;
                    let gap = residueGroups[nextIndex].angle - group.angle;
                    if (nextIndex === 0) gap += 2 * Math.PI;
                    if (gap > largestGap) {{
                        largestGap = gap;
                        startIndex = nextIndex;
                    }}
                }});
                const ordered = residueGroups.slice(startIndex).concat(residueGroups.slice(0, startIndex));
                const minGap = Math.min(0.32, 0.8 * 2 * Math.PI / ordered.length);
                const angles = [];
                ordered.forEach((group, index) => {{
                    let angle = group.angle;
                    if (index > 0) {{
                        while (angle < angles[index - 1]) angle += 2 * Math.PI;
                        angle = Math.max(angle, angles[index - 1] + minGap);
                    }}
                    angles.push(angle);
                }});
                const maxSpan = 2 * Math.PI - minGap;
                const span = angles[angles.length - 1] - angles[0];
                if (span > maxSpan) {{
                    const midpoint = (angles[0] + angles[angles.length - 1]) / 2;
                    const factor = maxSpan / span;
                    for (let index = 0; index < angles.length; index += 1) {{
                        angles[index] = midpoint + (angles[index] - midpoint) * factor;
                    }}
                }}
                ordered.forEach((group, index) => {{
                    group.positionAngle = angles[index] % (2 * Math.PI);
                }});
            }} else if (residueGroups.length === 1) {{
                residueGroups[0].positionAngle = residueGroups[0].angle;
            }}
            const proteinPoints = new Map();
            const residueLayouts = new Map();
            const fragmentWidth = Math.min(150, 2100 / Math.max(residueGroups.length, 1));
            const fragmentHeight = 90;
            const ligandHalfWidth = Math.max(...points.map(point => Math.abs(point.x - centerX)));
            const ligandHalfHeight = Math.max(...points.map(point => Math.abs(point.y - centerY)));
            residueGroups.forEach(group => {{
                const angle = group.positionAngle;
                const kinds = new Set(group.items.map(item => item.kind));
                const isHydrophobicOnly = kinds.size === 1 && kinds.has('hydrophobic');
                const fragment = structuresByResidue.get(group.residue);
                let cx;
                let cy;
                if (residueGroups.length === 1 && fragment && !isHydrophobicOnly) {{
                    const cos = Math.cos(angle);
                    const sin = Math.sin(angle);
                    const orbit = (ligandHalfWidth + fragmentWidth / 2 + 18) * Math.abs(cos)
                        + (ligandHalfHeight + fragmentHeight / 2 + 18) * Math.abs(sin);
                    cx = centerX + orbit * cos;
                    cy = centerY + orbit * sin;
                }} else {{
                    cx = centerX + 400 * Math.cos(angle);
                    cy = centerY + 230 * Math.sin(angle);
                }}
                if (isHydrophobicOnly) {{
                    const labelPoint = {{x: cx, y: cy}};
                    residueLayouts.set(group.residue, {{center: labelPoint, isHydrophobicOnly, group}});
                    return;
                }}
                if (!fragment) return;
                const anchorItem = group.items.reduce((best, item) => item.distance < best.distance ? item : best);
                const receptorAtomIndex = fragment.atoms.findIndex(atom => atom.name === anchorItem.receptor_atom);
                const anchor = fragment.atom_points[receptorAtomIndex];
                const anchorX = anchor.x - fragment.width / 2;
                const anchorY = anchor.y - fragment.height / 2;
                const targetX = -Math.cos(angle);
                const targetY = -Math.sin(angle);
                const baseRotation = (Math.atan2(targetY, targetX) - Math.atan2(anchorY, anchorX)) * 180 / Math.PI;
                const box = {{x: cx - fragmentWidth / 2, y: cy - fragmentHeight / 2,
                    width: fragmentWidth, height: fragmentHeight, cx, cy}};
                const fragmentGroup = makeDragGroup(structureGroup, box, 32);
                const labelGroup = document.createElementNS(ns, 'g');
                labels.appendChild(labelGroup);
                const residueOffset = layoutState.residues[group.residue] || {{x: 0, y: 0, rotation: 0}};
                if (typeof residueOffset.rotation !== 'number') residueOffset.rotation = 0;
                layoutState.residues[group.residue] = residueOffset;
                const fragmentPoints = drawMolecule(fragment, box, baseRotation, fragmentGroup);
                let residueNameText = null;
                const applyResidueOffset = offset => {{
                    const manualRotation = offset.rotation || 0;
                    fragmentGroup.setAttribute(
                        'transform', `translate(${{offset.x}} ${{offset.y}}) rotate(${{manualRotation}} ${{cx}} ${{cy}})`
                    );
                    labelGroup.setAttribute('transform', `translate(${{offset.x}} ${{offset.y}})`);
                    if (residueNameText) {{
                        const maxY = Math.max(...fragmentPoints.map(point =>
                            rotatePoint(point, {{x: cx, y: cy}}, manualRotation).y
                        ));
                        residueNameText.setAttribute('x', String(cx));
                        residueNameText.setAttribute('y', String(maxY + 24));
                    }}
                }};
                applyResidueOffset(residueOffset);
                addDragTarget(fragmentGroup, () => layoutState.residues[group.residue], offset => {{
                    offset.rotation = layoutState.residues[group.residue].rotation || 0;
                    layoutState.residues[group.residue] = offset;
                    applyResidueOffset(offset);
                    updateInteractionPositions();
                    saveLayout();
                }});
                const rotateHandle = document.createElementNS(ns, 'g');
                rotateHandle.setAttribute('class', 'diagram-rotate-handle');
                rotateHandle.setAttribute('aria-label', `Rotate ${{group.residue}}`);
                rotateHandle.style.cursor = 'grab';
                fragmentGroup.appendChild(rotateHandle);
                const rotateX = box.x + box.width - 4;
                const rotateY = box.y - 4;
                make('circle', {{
                    cx: rotateX, cy: rotateY, r: 10, fill: '#ffffff',
                    stroke: '#2563eb', 'stroke-width': 1.5, 'pointer-events': 'all'
                }}, rotateHandle);
                make('text', {{
                    x: rotateX, y: rotateY + 4, 'text-anchor': 'middle',
                    fill: '#2563eb', 'font-size': 13, 'font-weight': 700, 'pointer-events': 'none'
                }}, rotateHandle, '↻');
                make('title', {{}}, rotateHandle, 'Drag to rotate residue');
                addRotateTarget(
                    rotateHandle,
                    () => {{
                        const offset = layoutState.residues[group.residue];
                        return {{x: cx + offset.x, y: cy + offset.y}};
                    }},
                    () => layoutState.residues[group.residue].rotation || 0,
                    rotationValue => {{
                        const offset = layoutState.residues[group.residue];
                        offset.rotation = rotationValue;
                        applyResidueOffset(offset);
                        updateInteractionPositions();
                        saveLayout();
                    }}
                );
                fragment.atoms.forEach((atom, atomIndex) => {{
                    proteinPoints.set(`${{group.residue}}|${{atom.name}}`, fragmentPoints[atomIndex]);
                }});
                residueLayouts.set(group.residue, {{
                    center: {{x: cx, y: cy}}, fragment, fragmentPoints, group, labelGroup,
                    setNameText: text => {{
                        residueNameText = text;
                        applyResidueOffset(layoutState.residues[group.residue]);
                    }}
                }});
            }});

            const visibleInteractions = interactions.filter(item =>
                item.kind !== 'hydrophobic' &&
                proteinPoints.has(`${{item.residue}}|${{item.receptor_atom}}`)
            );
            const interactionSegments = [];
            visibleInteractions.forEach(item => {{
                let ligandPoint = points[item.ligand_atom];
                let proteinPoint = proteinPoints.get(`${{item.residue}}|${{item.receptor_atom}}`);
                if (item.kind === 'polar') {{
                    const ligandAtom = molecule.atoms[item.ligand_atom];
                    const fragment = structuresByResidue.get(item.residue);
                    const receptorAtomIndex = fragment.atoms.findIndex(atom => atom.name === item.receptor_atom);
                    const receptorAtom = fragment.atoms[receptorAtomIndex];
                    if (ligandAtom.element === 'N' && receptorAtom.element === 'O') {{
                        ligandPoint = nearestHydrogenPoint(molecule.atoms, item.ligand_atom, points, proteinPoint) || ligandPoint;
                    }} else if (ligandAtom.element === 'O' && receptorAtom.element === 'N') {{
                        proteinPoint = nearestHydrogenPoint(
                            fragment.atoms, receptorAtomIndex, residueLayouts.get(item.residue).fragmentPoints, ligandPoint
                        ) || proteinPoint;
                    }}
                }}
                const color = colors[item.kind] || colors.contact;
                const line = make('line', {{
                    x1: ligandPoint.x, y1: ligandPoint.y, x2: proteinPoint.x, y2: proteinPoint.y,
                    stroke: color, 'stroke-width': item.kind === 'contact' ? 1.2 : 2,
                    'stroke-dasharray': item.kind === 'hydrophobic' || item.kind === 'contact' ? 'none' : '6,4',
                    opacity: item.kind === 'contact' ? 0.45 : 0.9
                }}, links);
                const distanceLabel = make('text', {{
                    x: (ligandPoint.x + proteinPoint.x) / 2, y: (ligandPoint.y + proteinPoint.y) / 2 - 4,
                    fill: color, 'font-size': 10, 'font-weight': 600,
                    'text-anchor': 'middle', stroke: '#ffffff', 'stroke-width': 3,
                    'paint-order': 'stroke'
                }}, links, `${{item.distance.toFixed(1)}} Å`);
                interactionSegments.push({{
                    item, line, distanceLabel,
                    ligandPoint: {{...ligandPoint}},
                    proteinPoint: {{...proteinPoint}}
                }});
            }});
            updateInteractionPositions = () => {{
                interactionSegments.forEach(segment => {{
                    const ligandOffset = layoutState.ligand;
                    const residueOffset = layoutState.residues[segment.item.residue] || {{x: 0, y: 0}};
                    const residueCenter = residueLayouts.get(segment.item.residue).center;
                    const proteinPoint = rotatePoint(
                        segment.proteinPoint, residueCenter, residueOffset.rotation || 0
                    );
                    const x1 = segment.ligandPoint.x + ligandOffset.x;
                    const y1 = segment.ligandPoint.y + ligandOffset.y;
                    const x2 = proteinPoint.x + residueOffset.x;
                    const y2 = proteinPoint.y + residueOffset.y;
                    segment.line.setAttribute('x1', String(x1));
                    segment.line.setAttribute('y1', String(y1));
                    segment.line.setAttribute('x2', String(x2));
                    segment.line.setAttribute('y2', String(y2));
                    segment.distanceLabel.setAttribute('x', String((x1 + x2) / 2));
                    segment.distanceLabel.setAttribute('y', String((y1 + y2) / 2 - 4));
                }});
            }};
            updateInteractionPositions();
            residueGroups.forEach(group => {{
                const hydrophobicItems = group.items.filter(item => item.kind === 'hydrophobic');
                if (hydrophobicItems.length === 0) return;
                const contactPoints = hydrophobicItems.map(item => points[item.ligand_atom]);
                const center = {{
                    x: contactPoints.reduce((sum, point) => sum + point.x, 0) / contactPoints.length,
                    y: contactPoints.reduce((sum, point) => sum + point.y, 0) / contactPoints.length
                }};
                const outwardX = centerX + 400 * Math.cos(group.positionAngle) - center.x;
                const outwardY = centerY + 230 * Math.sin(group.positionAngle) - center.y;
                const outwardLength = Math.max(Math.hypot(outwardX, outwardY), 1);
                const ux = outwardX / outwardLength;
                const uy = outwardY / outwardLength;
                const vx = -uy;
                const vy = ux;
                const spread = contactPoints.map(point => (point.x - center.x) * vx + (point.y - center.y) * vy);
                const base = {{x: center.x + ux * 20, y: center.y + uy * 20}};
                const initialHalfHeight = Math.max(16, (Math.max(...spread) - Math.min(...spread)) / 2 + 10);
                const shape = layoutState.hydrophobic[group.residue] || {{x: 0, y: 0}};
                if (typeof shape.halfHeight !== 'number') shape.halfHeight = initialHalfHeight;
                if (typeof shape.depth !== 'number') shape.depth = 24;
                layoutState.hydrophobic[group.residue] = shape;
                const bracketGroup = document.createElementNS(ns, 'g');
                ligandLinkGroup.appendChild(bracketGroup);
                const bracketDragTarget = makeDragGroup(dragOverlay, {{
                    x: base.x - shape.halfHeight - shape.depth - 20,
                    y: base.y - shape.halfHeight - shape.depth - 20,
                    width: 2 * (shape.halfHeight + shape.depth + 20),
                    height: 2 * (shape.halfHeight + shape.depth + 20)
                }});
                bracketDragTarget.classList.add('diagram-hydrophobic-target');
                hydrophobicDragTargets.push({{element: bracketDragTarget, residue: group.residue}});
                let bracketLabelGroup = null;
                let bracketLabel = '';
                let bracketLabelText = null;
                let bracketLabelHitArea = null;
                bracketLabel = group.residue.slice(0, 1) + group.residue.slice(1, 3).toLowerCase() + group.residue.slice(3);
                bracketLabelGroup = document.createElementNS(ns, 'g');
                ligandLabelGroup.appendChild(bracketLabelGroup);
                bracketLabelHitArea = make('rect', {{
                    x: 0, y: 0, width: bracketLabel.length * 9, height: 18,
                    fill: 'transparent',
                    'pointer-events': 'all'
                }}, bracketLabelGroup);
                bracketLabelText = make('text', {{
                    x: 0, y: 0,
                    'text-anchor': ux > 0.25 ? 'start' : (ux < -0.25 ? 'end' : 'middle'),
                    fill: colors.hydrophobic, 'font-size': 14, 'font-weight': 700,
                    stroke: '#ffffff', 'stroke-width': 4, 'paint-order': 'stroke',
                    'pointer-events': 'none'
                }}, bracketLabelGroup, bracketLabel);
                const bracketPath = make('path', {{
                    d: '', fill: 'none', stroke: colors.hydrophobic, 'stroke-width': 2.5,
                    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                    'pointer-events': 'none'
                }}, bracketGroup);
                const makeShapeHandle = (title, cursor) => {{
                    const handle = make('circle', {{
                        cx: 0, cy: 0, r: 5, fill: '#ffffff', stroke: colors.hydrophobic,
                        'stroke-width': 1.8, class: 'hydrophobic-edit-handle', 'pointer-events': 'all'
                    }}, bracketDragTarget);
                    handle.style.cursor = cursor;
                    make('title', {{}}, handle, title);
                    return handle;
                }};
                const startHandle = makeShapeHandle('Drag to adjust bracket length', 'ns-resize');
                const endHandle = makeShapeHandle('Drag to adjust bracket length', 'ns-resize');
                const curveHandle = makeShapeHandle('Drag to adjust bracket curvature', 'grab');
                const bracketHitArea = bracketDragTarget.firstElementChild;
                const updateHydrophobicShape = () => {{
                    const halfHeight = shape.halfHeight;
                    const depth = shape.depth;
                    const shoulder = depth / 3;
                    const start = {{x: base.x + vx * halfHeight + ux * shoulder,
                        y: base.y + vy * halfHeight + uy * shoulder}};
                    const middle = {{x: base.x + ux * depth, y: base.y + uy * depth}};
                    const end = {{x: base.x - vx * halfHeight + ux * shoulder,
                        y: base.y - vy * halfHeight + uy * shoulder}};
                    const controlOffset = halfHeight * 0.62;
                    const pathData = depth < 1
                        ? `M ${{start.x}} ${{start.y}} L ${{end.x}} ${{end.y}}`
                        : [
                            `M ${{start.x}} ${{start.y}}`,
                            `C ${{start.x + ux * depth * 0.65}} ${{start.y + uy * depth * 0.65}} ${{middle.x + vx * controlOffset}} ${{middle.y + vy * controlOffset}} ${{middle.x}} ${{middle.y}}`,
                            `C ${{middle.x - vx * controlOffset}} ${{middle.y - vy * controlOffset}} ${{end.x + ux * depth * 0.65}} ${{end.y + uy * depth * 0.65}} ${{end.x}} ${{end.y}}`
                        ].join(' ');
                    bracketPath.setAttribute('d', pathData);
                    startHandle.setAttribute('cx', String(start.x));
                    startHandle.setAttribute('cy', String(start.y));
                    endHandle.setAttribute('cx', String(end.x));
                    endHandle.setAttribute('cy', String(end.y));
                    curveHandle.setAttribute('cx', String(middle.x));
                    curveHandle.setAttribute('cy', String(middle.y));
                    const extentX = Math.abs(vx) * halfHeight + Math.abs(ux) * (depth + 20) + 10;
                    const extentY = Math.abs(vy) * halfHeight + Math.abs(uy) * (depth + 20) + 10;
                    bracketHitArea.setAttribute('x', String(base.x - extentX));
                    bracketHitArea.setAttribute('y', String(base.y - extentY));
                    bracketHitArea.setAttribute('width', String(extentX * 2));
                    bracketHitArea.setAttribute('height', String(extentY * 2));
                    if (bracketLabelText && bracketLabelHitArea) {{
                        const labelX = middle.x + ux * 16;
                        const labelY = middle.y + uy * 16 + 4;
                        bracketLabelText.setAttribute('x', String(labelX));
                        bracketLabelText.setAttribute('y', String(labelY));
                        bracketLabelHitArea.setAttribute('x', String(labelX - bracketLabel.length * 4.5));
                        bracketLabelHitArea.setAttribute('y', String(labelY - 14));
                    }}
                }};
                const applyHydrophobicOffset = offset => {{
                    bracketGroup.setAttribute('transform', `translate(${{offset.x}} ${{offset.y}})`);
                    bracketDragTarget.setAttribute('transform',
                        `translate(${{layoutState.ligand.x + offset.x}} ${{layoutState.ligand.y + offset.y}})`);
                    if (bracketLabelGroup) bracketLabelGroup.setAttribute(
                        'transform', `translate(${{offset.x}} ${{offset.y}})`
                    );
                }};
                applyHydrophobicOffset(shape);
                updateHydrophobicShape();
                const setHydrophobicOffset = offset => {{
                    shape.x = offset.x;
                    shape.y = offset.y;
                    applyHydrophobicOffset(shape);
                    saveLayout();
                }};
                addDragTarget(bracketDragTarget, () => layoutState.hydrophobic[group.residue], setHydrophobicOffset);
                if (bracketLabelGroup) {{
                    addDragTarget(bracketLabelGroup, () => layoutState.hydrophobic[group.residue], setHydrophobicOffset);
                }}
                const bindShapeHandle = (handle, parameter, direction) => {{
                    handle.addEventListener('pointerdown', event => {{
                        if (event.button !== 0) return;
                        event.preventDefault();
                        event.stopPropagation();
                        const start = svgPoint(event);
                        const initial = shape[parameter];
                        handle.setPointerCapture(event.pointerId);
                        const move = pointerEvent => {{
                            const current = svgPoint(pointerEvent);
                            const deltaX = current.x - start.x;
                            const deltaY = current.y - start.y;
                            const change = deltaX * direction.x + deltaY * direction.y;
                            shape[parameter] = parameter === 'halfHeight'
                                ? Math.max(8, Math.min(140, initial + change))
                                : Math.max(0, Math.min(120, initial + change));
                            updateHydrophobicShape();
                            saveLayout();
                        }};
                        const finish = pointerEvent => {{
                            handle.removeEventListener('pointermove', move);
                            handle.removeEventListener('pointerup', finish);
                            handle.removeEventListener('pointercancel', finish);
                            if (handle.hasPointerCapture(pointerEvent.pointerId)) {{
                                handle.releasePointerCapture(pointerEvent.pointerId);
                            }}
                        }};
                        handle.addEventListener('pointermove', move);
                        handle.addEventListener('pointerup', finish);
                        handle.addEventListener('pointercancel', finish);
                    }});
                }};
                bindShapeHandle(startHandle, 'halfHeight', {{x: vx, y: vy}});
                bindShapeHandle(endHandle, 'halfHeight', {{x: -vx, y: -vy}});
                bindShapeHandle(curveHandle, 'depth', {{x: ux, y: uy}});
            }});
            residueLayouts.forEach((layout, residue) => {{
                if (layout.isHydrophobicOnly) {{
                    return;
                }}
                const name = residue.slice(0, 1) + residue.slice(1, 3).toLowerCase() + residue.slice(3);
                const nameText = make('text', {{
                    x: layout.center.x, y: Math.max(...layout.fragmentPoints.map(point => point.y)) + 24,
                    'text-anchor': 'middle',
                    fill: '#334155', 'font-size': 12, 'font-weight': 700,
                    stroke: '#ffffff', 'stroke-width': 3, 'paint-order': 'stroke'
                }}, layout.labelGroup, name);
                layout.setNameText(nameText);
            }});

            const legendItems = [
                ['Polar candidate', 'polar'],
                ['Hydrophobic', 'hydrophobic'],
                ['Salt bridge', 'salt_bridge'],
                ['π interaction', 'pi_stacking'],
                ['Cation-π', 'cation_pi'],
                ['Contact', 'contact']
            ];
            let legendX = 18;
            legendItems.forEach(([label, kind]) => {{
                const color = colors[kind];
                if (kind === 'hydrophobic') {{
                    make('path', {{
                        d: `M ${{legendX + 14}} 560 C ${{legendX + 4}} 560 ${{legendX + 4}} 588 ${{legendX + 14}} 588`,
                        fill: 'none', stroke: color, 'stroke-width': 2.2, 'stroke-linecap': 'round'
                    }});
                }} else {{
                    make('line', {{
                        x1: legendX, y1: 574, x2: legendX + 18, y2: 574,
                        stroke: color, 'stroke-width': 2,
                        'stroke-dasharray': ['polar', 'salt_bridge', 'pi_stacking', 'cation_pi'].includes(kind) ? '5,3' : 'none'
                    }});
                }}
                make('text', {{x: legendX + 23, y: 578, fill: '#475569', 'font-size': 11}}, svg, label);
                legendX += label.length * 7 + 48;
            }});
            dragTargets.forEach(({{element, getOffset, setOffset}}) => {{
                element.addEventListener('pointerdown', event => {{
                    if (event.button !== 0) return;
                    event.preventDefault();
                    const start = svgPoint(event);
                    const initial = {{...getOffset()}};
                    element.setPointerCapture(event.pointerId);
                    element.style.cursor = 'grabbing';
                    const move = pointerEvent => {{
                        const current = svgPoint(pointerEvent);
                        setOffset({{
                            x: initial.x + current.x - start.x,
                            y: initial.y + current.y - start.y
                        }});
                    }};
                    const finish = pointerEvent => {{
                        element.removeEventListener('pointermove', move);
                        element.removeEventListener('pointerup', finish);
                        element.removeEventListener('pointercancel', finish);
                        if (element.hasPointerCapture(pointerEvent.pointerId)) {{
                            element.releasePointerCapture(pointerEvent.pointerId);
                        }}
                        element.style.cursor = 'grab';
                    }};
                    element.addEventListener('pointermove', move);
                    element.addEventListener('pointerup', finish);
                    element.addEventListener('pointercancel', finish);
                }});
            }});
        }};

        window.setViewerStyle = function(showSurface, showCartoon, showSticks) {{
            if (!viewer) return;
            let recStyle = {{}};
            if (showCartoon) recStyle.cartoon = {{color: '#A0A0A0', opacity: 0.8}};
            viewer.setStyle({{model: 0}}, recStyle);
            setProteinSurface(showSurface);
            if (viewer.getModel(1)) {{
                if (showSticks) {{
                    viewer.setStyle({{model: 1}}, {{
                        stick: {{colorscheme: 'cyanCarbon', radius: 0.2}}
                    }});
                }} else {{
                    viewer.setStyle({{model: 1}}, {{hidden: true}});
                }}
            }}
            viewer.render();
        }};
    </script>
</body>
</html>
"""

class MolViewer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(f"QFrame#panel {{ background: {P.surface}; border: 1px solid {P.border}; border-radius: 10px; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self.web = QWebEngineView()
        self.web.page().setBackgroundColor(QColor(P.surface))
        lay.addWidget(self.web)
        self.web.setHtml(HTML_TEMPLATE)

    def load_receptor(self, text_data: str, fmt: str = "pdb") -> None:
        safe_text = json.dumps(text_data)
        self.web.page().runJavaScript(f"window.loadReceptor({safe_text}, '{fmt}');")

    def load_ligand(self, text_data: str, fmt: str = "sdf") -> None:
        safe_text = json.dumps(text_data)
        self.web.page().runJavaScript(f"window.loadLigand({safe_text}, '{fmt}');")

    def load_complex(self, rec_text: str, lig_text: str, rec_fmt: str = "pdbqt", lig_fmt: str = "sdf",
                     surface: bool = False, cartoon: bool = True, sticks: bool = True) -> None:
        safe_rec = json.dumps(rec_text)
        safe_lig = json.dumps(lig_text)
        self.web.page().runJavaScript(
            f"window.loadComplex({safe_rec}, {safe_lig}, '{rec_fmt}', '{lig_fmt}', "
            f"{str(surface).lower()}, {str(cartoon).lower()}, {str(sticks).lower()});"
        )

    def show_2d_interactions(self, molecule: Chem.Mol, interactions: list[DiagramInteraction],
                             residue_structures: list[ResidueStructure], thresholds: dict[str, float]) -> None:
        diagram_molecule = Chem.RemoveHs(molecule)
        Chem.Kekulize(diagram_molecule, clearAromaticFlags=True)
        molecule_data = _draw_molecule_data(diagram_molecule, 420, 280)
        residue_data = []
        for structure in residue_structures:
            fragment = Chem.Mol(structure.molecule)
            structure_data = _draw_molecule_data(fragment, 180, 120)
            structure_data["residue"] = structure.residue
            residue_data.append(structure_data)
        interaction_data = [
            {
                "kind": item.kind,
                "residue": item.residue,
                "ligand_atom": item.ligand_atom,
                "receptor_atom": item.receptor_atom,
                "distance": item.distance,
            }
            for item in interactions
        ]
        molecule_json = json.dumps(molecule_data)
        residue_json = json.dumps(residue_data)
        interactions_json = json.dumps(interaction_data)
        thresholds_json = json.dumps(thresholds)
        self.web.page().runJavaScript(
            f"window.show2DView({molecule_json}, {residue_json}, {interactions_json}, {thresholds_json});"
        )

    def export_2d_png(self, callback: Callable[[str | None], None]) -> None:
        self.web.page().runJavaScript(
            "if (typeof window.export2DPNG === 'function') { window.export2DPNG(); } "
            "else { window.export2DPNGError = 'The diagram exporter is unavailable.'; }"
        )
        self._poll_2d_png_export(callback, 0)

    def _poll_2d_png_export(self, callback: Callable[[str | None], None], attempt: int) -> None:
        script = (
            "window.exported2DPNG || "
            "(window.export2DPNGError ? 'ERROR: ' + window.export2DPNGError : null)"
        )
        self.web.page().runJavaScript(
            script,
            lambda result: self._handle_2d_png_export(callback, attempt, result),
        )

    def _handle_2d_png_export(
        self, callback: Callable[[str | None], None], attempt: int, result: str | None
    ) -> None:
        if isinstance(result, str) and result:
            callback(result)
            return
        if attempt >= 100:
            callback(None)
            return
        QTimer.singleShot(50, lambda: self._poll_2d_png_export(callback, attempt + 1))

    def apply_settings(self, surface: bool, cartoon: bool, sticks: bool) -> None:
        self.web.page().runJavaScript(f"window.setViewerStyle({str(surface).lower()}, {str(cartoon).lower()}, {str(sticks).lower()});")

    def add_box(self, center: tuple[float, ...], size: tuple[float, ...]) -> None:
        center_json = json.dumps({"x": center[0], "y": center[1], "z": center[2]})
        size_json = json.dumps({"x": size[0], "y": size[1], "z": size[2]})
        self.web.page().runJavaScript(f"window.addBox({center_json}, {size_json});")

    def add_reference(self, text_data: str, fmt: str = "sdf") -> None:
        self.web.page().runJavaScript(f"window.addReference({json.dumps(text_data)}, {json.dumps(fmt)});")

    def clear_shapes(self) -> None:
        self.web.page().runJavaScript("if (viewer) { viewer.removeAllShapes(); viewer.render(); }")
