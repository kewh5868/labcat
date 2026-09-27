# Embedded runtime notices

The Docker application redistributes the following pinned upstream binaries:

- Goose 1.50.0, Apache License 2.0: `GOOSE-LICENSE`.
  Source and release: https://github.com/aaif-goose/goose/tree/v1.50.0
- OpenAI Codex 0.154.0, Apache License 2.0: `CODEX-LICENSE` and `CODEX-NOTICE`.
  Source and release: https://github.com/openai/codex/tree/rust-v0.154.0
- Claude Code 2.1.274, unmodified Anthropic native binary: `CLAUDE-CODE-NOTICE`.
  Official release manifest: https://downloads.claude.ai/claude-code-releases/2.1.274/manifest.json
  Use and redistribution follow Anthropic’s applicable terms, not Labcat’s license.
- JSmol/Jmol 16.4.23, GNU LGPL 2.1 or later: `JSMOL-LICENSE` and `JSMOL-NOTICE`.
  Its unmodified browser runtime and source/build-resource archive ship inside
  the application image and Python distributions. See
  [JSmol source distribution](../docs/jsmol-source.md).

The installers verify architecture-specific SHA256 checksums before installing
an executable. Claude Code also uses an exact pinned download size and is
installed without running an upstream shell installer. These upstream projects are separate from Labcat. The
notices do not imply their endorsement of this application. Other package and
scientific dataset attributions remain alongside their respective assets.
