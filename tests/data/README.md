# Test data provenance

| File | Source | Used for |
| --- | --- | --- |
| `1AFS_A_clean.pdb` | RCSB PDB entry 1AFS (rat 3-alpha-hydroxysteroid dehydrogenase), chain A protein atoms only, via the pdb2pqr test data | receptor preparation; known cofactor-dependent redocking case |
| `1AFS_TES.sdf` | Crystal testosterone (TES, chain A) of 1AFS with bond orders assigned from the testosterone SMILES | reference ligand |
| `1IEP_receptorH.pdb` | RCSB PDB entry 1IEP (Abl kinase + imatinib), receptor as distributed in the AutoDock Vina example data | passing redocking benchmark |
| `1IEP_ligand_STI.sdf` | Crystal imatinib from the same AutoDock Vina example (Apache-2.0) | reference ligand |

PDB archive data are released under CC0. The Vina example files come from https://github.com/ccsb-scripps/AutoDock-Vina (Apache-2.0).
