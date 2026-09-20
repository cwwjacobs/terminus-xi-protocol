# xiPrismAgent Design Pack

This pack captures the current state of Prism as discussed and clarified in the architecture work.

## What is inside
- `xiPrismAgent_completed.py` — the completed first implementation of Prism as a spatial/angle refraction primitive
- `schemas/prism_input.schema.json`
- `schemas/prism_split.schema.json`
- `schemas/prism_boundary_event.schema.json`
- example JSONs for each schema
- `docs/PRISM_ROADMAP.md`

## What Prism is now
Prism should be understood in layers:

### Prism v0.1 — Spatial Refraction Primitive
This is the current implementation:
- inspect a node through an angle/lens
- extract what matters
- preserve provenance
- support spatial/layout-aware retrieval use cases

### Prism v0.2 — Output Refraction
This is the next step:
- evaluate emitted artifacts, traces, and candidate rows
- split them into interpretable channels such as:
  - goal alignment
  - grounding integrity
  - risk pressure
  - genericity
  - novelty
  - focus/coherence
  - audit completeness

### Prism v0.3 — Boundary Protocol
This converts channel scores into operational events:
- inside_gold
- amber_drift
- red_lock
- grey_warning
- violet_warning

### Prism v1.0 — Voxel/Vault View Layer
This is the later visualization/governance layer:
- voxelized audit views
- spectral oversight
- human review cockpit
- paper/demo layer

## Why this pack exists
The completed first Prism file is useful, but it is only one slice of the larger Prism idea. This pack preserves:
- the current implementation
- the clarified role of Prism in the system
- the next schemas required to let Prism become a true refraction layer

## Placement in the stack
Recommended placement:

1. actor emits output
2. Artifactor fingerprints it
3. Prism refracts it
4. Prism emits split + boundary event
5. acceptance/adjudication decides:
   - continue
   - repair
   - review
   - quarantine
   - reject

## Design doctrine
- keep Prism in the architecture now
- do not make full Prism UI / voxelization a hard v1 dependency
- use deterministic rules for hard stops
- use graded/scored channels for interpretation
- let Prism shape corpus admission and governance, not just presentation
