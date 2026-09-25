# Names and crystal-structure boundaries

Chemical names are retrieved from approved public endpoints and kept in bounded,
target-specific receipts. An exact composition match does not establish an
experimental phase, bulk equivalence, or a core/shell role. A missing or ambiguous
name remains unresolved. Saved report rankings and measurements are unchanged.

The Python structure store checks report membership, exact source identity and
composition, public access, response budgets, and validated CIF geometry before
caching or returning structures. Independent components retain separate identities
and can have partial availability. Retrieved instructions and arbitrary raw-file
links cannot grant access or become source evidence. Corrupted caches fail closed.

This snapshot adds the data and validation APIs. Browser routes and the interactive
structure viewer are delivered in later stages. Unit fixtures and transport mocks
exercise provenance and isolation; they do not claim authenticated live retrieval
or native desktop coverage.
