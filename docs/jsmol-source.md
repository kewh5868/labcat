# JSmol source distribution

Labcat redistributes the unmodified JSmol 16.4.23 browser runtime under
GNU LGPL 2.1 or later. The [notice](../third_party/JSMOL-NOTICE) and
[license](../third_party/JSMOL-LICENSE) accompany the desktop installation
bundles and Docker image. Upstream copyright/component notices also remain
beside the runtime and within its source files.

The following files are included in the wheel, source distribution and Docker
image under `labcat/static/structure-viewer/vendor/`:

- `SOURCE.tar.gz`: the unmodified source and build-resource subset.
- `SOURCE-MANIFEST.json`: the exact selected file names and SHA-256 hashes,
  upstream archive hashes, selection rules and packaged archive hash.
- `LICENSE.txt` and `COPYRIGHT.txt`: verbatim upstream notices.
- `manifest.json`: version and hashes of the unmodified browser runtime files.

The repository originals are in `frontend/public/structure-viewer/vendor/`.
The installer image contains these same files; they do not require a source-code
download after installation. When the viewer is enabled, the bundled source
archive is also available at the application's
`/structure-viewer/vendor/SOURCE.tar.gz` address. Disabling viewer routes does
not remove the source files from the installed package/image.

## Exact source subset

The archive retains the complete upstream `jmol-16.4.23/src`, `tools`, `jars` and
`manifest` trees; build README, copyright, license and changelog; Java2Script
compiler resources; unminified `site-resources/jsmol/js` wrappers; jQuery source;
JavaScript support classes; and the small `Jmol-j2s-site.zip` build resource.
Original file bytes are preserved. Source build dependencies and embedded
library resources stay included, even when the Labcat viewer does not call
those features.

Demonstration web pages and datasets outside `src`, prebuilt application JARs,
and duplicate prebuilt `jsmol.zip` archives are omitted. These are distribution
omissions, not edits to the runtime or its source. Nothing in this source
archive is used as a material candidate, measurement, citation or report result.

The upstream source release's build README describes the Eclipse/Java2Script
and Ant workflow. The subset preserves all source/build files that release
supplies; it does not add absent project configuration or claim to rebuild
the upstream binaries. Labcat's helper reproducibly repackages the verified
release source with normalized archive metadata.

## Repackage or verify locally

Obtain the matching binary ZIP and full source TAR.GZ from the
[official 16.4.23 release directory](https://sourceforge.net/projects/jmol/files/Jmol/Version%2016.4/Jmol%2016.4.23/).
The helper accepts only the pinned archive hashes recorded in the source
manifest. It uses local files and does not download or execute upstream code.

```sh
python scripts/vendor_jsmol_source.py \
  --binary-archive /path/to/Jmol-16.4.23-binary.zip \
  --source-archive /path/to/Jmol-16.4.23-full.tar.gz
```

Add `--check` to verify the shipped runtime, regenerate the source archive in
a temporary directory and compare its bytes/hash manifest without changing
the repository. Both command variants leave the vendored runtime untouched.
Archive timestamps, ownership and permissions are normalized; every included
source file retains its upstream content bytes. Git attributes preserve
vendored line endings across macOS, Windows and Linux checkouts.
