# xiCharter

## System Layers

The system is composed of three distinct layers.

### ixcm (ixcModules)
ixcm modules are functional units that perform specific transformations or computations.

They:
- implement capability
- do not enforce system-level rules
- are reusable and composable

Examples:
- ixcm_score_trace
- ixcm_trace_validate_check
- ixcm_adjudicate_pick

### xiAgents
xiAgents are deterministic wrappers that control the execution of ixcm modules.

They:
- enforce invariants
- manage retries and escalation
- validate outputs
- attach provenance
- decide acceptance, rejection, or routing

xiAgents do not implement capability; they govern its use.

### xiCharter
The xiCharter defines the system's operational law.

It:
- defines invariants
- defines allowed behavior
- defines failure conditions
- defines what must never drift

The xiCharter is the highest authority and must be obeyed by all xiAgents.

## Core Distinction

ixcm implements capability.  
xiAgent enforces its use.  
xiCharter defines the law.

## Operational Position

xiAgents are not autonomous personas, free-roaming planners, or general chatbots. They are bounded runtime control wrappers responsible for enforcing law at stage boundaries.

A xiAgent must:
- accept constrained inputs
- apply explicit invariants and stage rules
- normalize or transform outputs into canonical form
- reject invalid, unsafe, or out-of-bounds state
- preserve provenance and auditability
- pass forward a controlled artifact

## System Posture

The system favors:
- deterministic execution where possible
- explicit rejection over silent corruption
- bounded escalation over uncontrolled retry
- visible failure over hidden drift
- canonical outputs over permissive ambiguity

## Fixed Boundary Rule

No unvalidated artifact may cross a stage boundary.

## Drift Rule

Drift must be surfaced, not normalized.
Recovery may be invoked, but recovery must return to normal operating posture after stability is restored.

## Failure Rule

Failure must be:
- explicit
- logged
- attributable to a stage
- retained for audit where appropriate

## Contradiction Rule

Contradictory reasoning is a loud failure condition and must not be promoted.

## Review Rule

Borderline outputs with unusual placement signals may be retained with review flags, but may not be silently promoted.
