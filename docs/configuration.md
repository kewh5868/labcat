# Configuration and capability status

`labcat status` describes this snapshot; its `candidates` list is empty. The
`audit` style includes validated settings, implemented features and next steps.
`labcat check-config` validates preferences without network access.

An optional TOML file can override known ranking, presentation and model fields.
Ranking weights must be finite values between zero and one and sum to one.
Presentation uses bounded choices; arbitrary paths, markup and policy changes
are rejected. `provider = "none"` remains the TOML default and only accepted
model setting. Future connection management will be a separate explicit action.
Report appearance preferences do not mean PDF or Word export exists yet.

```toml
[presentation]
style = "audit"
format = "json"
verbosity = "detailed"
```

```bash
labcat --config preferences.toml status
```

Only approved public adapters may eventually supply material properties. User
text, ranking weights, model output and saved preferences cannot establish facts.
