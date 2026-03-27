# ABC Atlas Cell Type Taxonomy Reference

Whole Mouse Brain taxonomy (Yao et al. 2023). Hierarchy: **Class → Subclass → Supertype → Cluster** (34 → 338 → 1,201 → 5,322).

## Contents
- Neuronal classes and subclasses
- Non-neuronal classes and subclasses
- Ontology cross-references
- Available taxonomies

## Neuronal Classes

### Glutamatergic (excitatory) neurons

| Class | Subclasses | Brain regions |
|---|---|---|
| **IT (intratelencephalic)** | L2/3 IT, L4/5 IT, L5 IT, L6 IT, L6 IT Car3, Car3-IT | Isocortex, hippocampus |
| **ET (extratelencephalic)** | L5 ET, L5/6 NP, L6 CT, L6b | Isocortex (deep layers) |
| **CT (corticothalamic)** | L6 CT | Layer 6 cortex → thalamus |
| **NP (near-projecting)** | L5/6 NP | Deep cortical layers |
| **DG (dentate gyrus)** | DG | Hippocampus dentate gyrus |
| **CA (cornu ammonis)** | CA1, CA2, CA3 | Hippocampal formation |
| **SUB (subiculum)** | SUB-ProS | Subiculum/prosubiculum |
| **Amygdala excitatory** | BLA, BMA, LA, PA | Amygdala nuclei |
| **Hippocampal-Entorhinal** | PPP, NP SUB, CT SUB | Hippocampal/entorhinal |
| **Thalamus excitatory** | Habenular, PVT, various thalamic | Thalamic nuclei |
| **Hypothalamus excitatory** | Hypothal Glut (multiple) | Hypothalamus |
| **Midbrain excitatory** | MB Glut (multiple) | Midbrain regions |
| **Hindbrain excitatory** | MY Glut, Pons Glut | Medulla, pons |
| **Cerebellum excitatory** | Granule, UBC | Cerebellar cortex |

### GABAergic (inhibitory) neurons

| Class | Subclasses | Characteristics |
|---|---|---|
| **CGE-derived** | Lamp5, Lamp5 Lhx6, Sncg, Vip | Caudal ganglionic eminence origin |
| **MGE-derived** | Pvalb, Sst, Sst Chodl, Chandelier | Medial ganglionic eminence origin |
| **LGE-derived** | MSN D1, MSN D2, MSN-related | Lateral ganglionic eminence; striatal |
| **Amygdala inhibitory** | CEA, MEA, Intercalated | Central/medial amygdala |
| **Hypothalamus inhibitory** | Hypothal GABA (multiple) | Hypothalamic inhibitory |
| **Midbrain inhibitory** | MB GABA (multiple) | Midbrain GABAergic |
| **Hindbrain inhibitory** | MY GABA, Pons GABA | Medulla, pons |
| **Cerebellar inhibitory** | Purkinje, Golgi, molecular layer interneurons | Cerebellar cortex |

### Other neurotransmitter types

| Class | Subclasses | Notes |
|---|---|---|
| **Cholinergic** | Chat (multiple subtypes) | Basal forebrain, brainstem |
| **Dopaminergic** | TH+ subtypes (MB DA) | Substantia nigra, VTA |
| **Serotonergic** | 5HT subtypes | Raphe nuclei |
| **Glycinergic** | Various hindbrain | Spinal cord, brainstem |

## Non-Neuronal Classes

| Class | Subclasses | Notes |
|---|---|---|
| **Astrocyte** | Astro-TE, Astro-NT, Bergmann | Region-specific subtypes; Bergmann = cerebellum |
| **Oligodendrocyte** | Oligo (multiple), OPC | Mature + precursor cells |
| **Microglia** | Micro-PVM | Includes perivascular macrophages |
| **Vascular** | Endo, VLMC, Pericyte, SMC | Endothelial, vascular leptomeningeal, smooth muscle |
| **Ependymal** | Epend, Tanycyte | Ventricular lining |
| **Immune** | Macro, Lymph | Non-microglial immune cells |

## Ontology Cross-References

The Allen taxonomy maps to standard ontologies:

| System | Use | Example |
|---|---|---|
| **CL (Cell Ontology)** | Cell type identity | CL:0000540 = neuron, CL:0000617 = GABAergic neuron |
| **UBERON** | Brain region anatomy | UBERON:0001950 = neocortex, UBERON:0002421 = hippocampus |
| **MONDO** | Disease associations | MONDO:0004975 = Alzheimer's disease |
| **EFO** | Assay types | EFO:0008913 = 10x 3' v3, EFO:0700016 = MERFISH |

## Available Taxonomies

| Taxonomy | Species | Region | Key publication |
|---|---|---|---|
| Whole Mouse Brain Consensus | Mouse | Whole brain | Yao et al. 2023 |
| Whole Human Brain | Human | Whole brain | Siletti et al. 2023 |
| Mammalian Primary Motor Cortex | Human, Mouse, Marmoset | M1 | Bakken et al. 2021 |
| Human Neocortex | Human | 8 cortical areas | — |
| SEA-AD (Alzheimer's) | Human | MTG | — |
| Cross-Species Basal Ganglia | Human, Macaque, Marmoset | Basal ganglia | — |
| Mouse Isocortex + Hippocampus | Mouse | Cortex + hippocampus | Tasic et al. 2018 |

## Programmatic Access

```python
# pip install abc_atlas_access
from abc_atlas_access.abc_atlas_cache import AbcProjectCache

cache = AbcProjectCache.from_s3_cache()  # No credentials needed (AWS public dataset)
# Access cell metadata, gene expression, spatial coordinates, taxonomy mappings
```

Data is in AnnData (.h5ad) format. Key fields in `obs` (cell metadata):
- `cluster_id`, `subclass`, `class`, `supertype` — taxonomy assignment
- `anatomical_region`, `brain_region_ontology_term_id` — location
- `donor_id`, `organism`, `assay` — sample metadata
