# Public response fixture

`nomad-silicon.json` is an anonymous NOMAD v1 response retrieved on 2026-09-09
from `https://nomad-lab.eu/prod/v1/api/v1/entries/query`. Its echoed query and
required fields document the request. It contains public, non-embargoed entries,
including zero band gaps and disagreeing reported gaps for validation tests.

This file is only test input. Production research requests live public sources
and never load this response as a candidate list. Test mutations exercise invalid
data; they are not scientific assertions or demonstration results.

The [official NOMAD results schema](https://github.com/FAIRmat-NFDI/nomad/blob/develop/nomad/datamodel/results.py)
defines the returned band-gap values in joules.
