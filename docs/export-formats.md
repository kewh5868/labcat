# Saved report exports

`render_download` exports saved report sections as text, JSON, PDF or Word without
running research. The exports preserve source citations, missing-data caveats,
selected views and archived source identities. Presentation preferences can change
layout and typography; they cannot rerank saved evidence or add scientific values.

PDF and Word support are optional extras. Bundled DejaVu fonts and their license
provide scientific text rendering. JSON keeps structured results and rejects invalid
or oversized content. Text and JSON do not require document rendering packages.

The export module also provides bounded preview/download routers for integration;
full application routing and the research CLI follow separately. Preview material
is labeled as layout placeholders with no research performed. Browser-facing
session and origin protection are validated when the complete API is introduced.
