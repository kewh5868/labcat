# Research and evidence boundaries

The `Plan` dataclass and JSON schema accept a closed set of preference enums.
Parsing rejects extra fields, duplicate keys, surrounding prose and unsupported
values. Plans cannot supply measurements, citations, URLs, tools or policy.
`bounded_context` retains bounded untrusted hints and drops report prose and URLs.

`science.request_violation` and the pure intake helpers check research boundaries,
including negation and harmful-use context. These lexical checks complement the
absence of unsafe tools; they are not a general sanitizer. Retrieved-text screening
rejects instructions and attempted evidence promotion, including normalized text.
A failed request or unresolved intake outcome returns no scientific records.

This snapshot does not retrieve evidence, rank materials or run model inference.
A later approved public adapter must validate source records and provenance before
any scientific values can enter reports. User text and model memory are never
scientific evidence, even when they include a numeric value or a citation.
