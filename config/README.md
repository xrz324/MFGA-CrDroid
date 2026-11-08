# Font Checks

`upstream.json` pins the SELFUSE release URL, SHA256, and archive font directory.
Update the URL and SHA256 together when syncing upstream. The build imports only
font files; upstream scripts and XML are never used. The Android 12 fallback Emoji
font is excluded because this module targets Android 13 and newer.

`module.json` contains fixed module metadata. `build.py` generates `module.prop`
inside the ZIP. CI supplies `MODULE_VERSION` from the release tag (without `v`)
or a development build identifier, and `MODULE_VERSION_CODE` from
`1717180004 + github.run_number`. Local builds default to `dev-local` and
version code `1717180004`; both values can be overridden with those variables.

`system-fonts.json` lists existing references supplied by the ROM, including
optional references retained in the upstream legacy `fonts.xml`. It is not a
list of fonts bundled in this module. When changing these references, review
the target ROM's font configuration before updating this list.

`metric-fonts.json` supplies numeric metrics and axes for generated, empty Product
fonts. Google Sans Flex uses the pinned upstream SysFont profile; the other
profiles come from the local ROM reference dump. `NEW/` is excluded from Git and
is not a build input.

Primary fonts preserve the original XML weight mapping. The build verifies their
source weights, normalizes installed metadata to 200/300/400/700, and aligns
Roboto line metrics. The default `400.ttf` must be internally 400/Regular because
Android can derive a named family's base weight from intrinsic font metadata.
Tall glyphs remain in complete `MFGAOverflow-*` fallback copies; ordinary fonts
recompute their bounds without changing outlines or advances.

Framework XML registers static styles directly, while legacy XML and Product
families retain variable metric providers. The build checks static mappings,
fallback coverage, and variable axes against the actual font files.

`required-ui-families.json` lists required Google Sans and variable SystemUI
families. The build rejects missing registrations.

`python3 build.py` downloads the pinned upstream archive, verifies its SHA256,
adapts the real fonts, and validates the converted metrics, styles, glyphs,
coverage, and XML references before packaging. Any failure stops the Actions build.
