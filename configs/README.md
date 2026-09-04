# Configs

Versioned, non-secret scientific parameter sets.

Rules:

- A parameter set is versioned and immutable once a run has cited it. A change
  is a new version, never an edit in place.
- Every parameter set validates against `schemas/parameter-set.schema.json`.
  Unknown scientific-parameter fields are rejected, not ignored.
- No credentials, tokens, endpoints, or file paths outside the repository
  belong here.
- A run records the resolved value of every parameter it used, including
  defaults. Hidden defaults are not permitted (WP-10 task 2).
- Coverage-versus-quality and other tuning choices are made on the development
  split only (WP-07 task 11).

No parameter set exists yet. Values remain undefined until the contracts in
section 6 and the gates in section 10 are implemented.
