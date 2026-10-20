# Building Sonar Edge

Use Windows x64 with Python 3.12, Node.js, Inno Setup 6.7.3, and the Windows
.NET Framework C# compiler. Create a virtual environment and install
`requirements-desktop.txt`. Put Microsoft's signed Evergreen WebView2
bootstrapper at `packaging/MicrosoftEdgeWebview2Setup.exe`.

```powershell
python -m unittest discover -q
node test_visuals.cjs
node test_widget_fit.cjs
node test_iframe_reconnect.cjs
node test_actions.cjs
node test_device_lists.cjs
python build_native.py
python build_installer.py
python build_installer.py --test
python verify_release.py
python verify_installer.py
```

`SONAR_EDGE_ISCC` can point to ISCC.exe if Inno Setup is installed elsewhere.
The installer lifecycle test uses an isolated installation, Startup Apps entry,
Start menu group, and settings folder; it never uninstalls the real app.

## Releasing an update

1. Change `VERSION` in `app_version.py`, make the changes, and run the checks.
2. Push to `main` and verify that the **Build and release** workflow succeeds.
3. Push the matching tag, such as `v1.0.1`, or run the workflow manually with
   **Publish** selected. The workflow builds and publishes the Setup EXE,
   portable ZIP, and SHA256SUMS.txt in GitHub Releases.

Use a new version for each release. The in-app updater reads the latest
stable public release, verifies GitHub's SHA-256 digest for the installer,
and starts Setup only after the user chooses Download & install. Drafts,
prereleases, older versions, missing hashes, and mismatched assets are rejected.
The updater's configured repository defaults to `fivekeyelements/SonarEdge`.

Repeating a publish run for an already public version verifies that its three
release files exist and skips publishing successfully. The workflow summary
states that the existing downloads were kept; changes from that run are not
published. An incomplete public release still fails for inspection. Draft
releases can still receive their assets before being published.

Do not commit personal preferences, album art, custom backgrounds, logs,
downloaded installers, build output, credentials, or local runtime caches.
The app is independent of SteelSeries, CORSAIR, and MusicBee. The MusicBee
helper is original source in `musicbee/`; its DLL is built locally.
