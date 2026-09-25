# Embedded runtime notices

The Docker application redistributes the following pinned upstream binaries:

- Goose 1.50.0, Apache License 2.0: `GOOSE-LICENSE`.
  Source and release: https://github.com/aaif-goose/goose/tree/v1.50.0
- OpenAI Codex 0.154.0, Apache License 2.0: `CODEX-LICENSE` and `CODEX-NOTICE`.
  Source and release: https://github.com/openai/codex/tree/rust-v0.154.0
- JSmol/Jmol 16.4.23, GNU LGPL 2.1 or later: `JSMOL-LICENSE` and `JSMOL-NOTICE`.
  Its unmodified browser runtime and source/build-resource archive ship inside
  the application image and Python distributions. See
  [JSmol source distribution](../docs/jsmol-source.md).

The installer verifies architecture-specific archive checksums before extracting
an executable. These upstream projects are separate from Labcat. The
notices do not imply their endorsement of this application. Other package and
scientific dataset attributions remain alongside their respective assets.
