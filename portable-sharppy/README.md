# BTV NSHARP Portable for Windows

This build packages the upstream SHARPpy 1.4.0 Qt desktop application and its Python/Qt runtime into a Windows application folder. The target workstation does **not** need Python, Conda, SHARPpy, or an installer.

## Download and run

1. Download the latest `BTV-NSHARP-Windows-Portable.zip` from the repository's GitHub Actions artifact or Releases page.
2. Extract the ZIP to a folder where executable applications are permitted.
3. Run `BTV-NSHARP.exe`.
4. In SHARPpy, open **Data Sources** and select BTV CWA RRFS (Latest), GFS (Latest), RAP (Latest), or HRRR (Latest).

The bundle is a portable **one-folder** application. Keep the complete extracted folder together; do not move only the EXE out of its supporting files. The launcher copies the two BTV data-source files into the user's normal SHARPpy data-source directory at first launch. It does not install Python packages or write to system directories.

## Build

GitHub Actions builds on `windows-latest` using the pinned Conda environment in `environment-windows.yml`. It runs an import/data-source smoke test, packages the GUI with PyInstaller, then zips the complete application folder.

## Operational notes

- The application uses the official SHARPpy 1.4.0 GUI and diagnostic routines.
- BUFKIT feeds are retrieved directly from Penn State's public BUFKIT distribution service; internet access is required for live model data.
- This is an alpha, unsigned executable. Windows SmartScreen or NWS endpoint protection may warn or block it. Do not bypass agency security controls; request review/allowlisting through the appropriate NWS IT process.
- This package is not an officially supported NWS software distribution.
