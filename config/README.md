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

`required-ui-families.json` records the Google Sans and variable family names
retained after removing OEM registrations caused SystemUI to fail on the device.
The build rejects missing registrations. This does not guarantee that every
configuration will work on other ROM versions; boot and rendering still need
device verification.
