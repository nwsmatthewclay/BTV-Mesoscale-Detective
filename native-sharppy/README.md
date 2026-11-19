# BTV NSHARP for Windows

**For restricted NWS workstations, use the portable Windows build.** It is built by GitHub Actions and does not require Python, Conda, SHARPpy, an installer, or administrator privileges.

See [Portable BTV NSHARP](../portable-sharppy/README.md) for the download and run instructions. The build workflow is [Build BTV NSHARP Portable (Windows)](../.github/workflows/build-portable-nsharp.yml).

## Legacy developer setup

The `install-windows.ps1` script below is retained only for developer machines where installing Miniforge/Conda and Python packages is permitted. **Do not use this setup on a locked-down workstation.**

The legacy setup creates a Conda environment with Python 3.10, NumPy <2, SHARPpy 1.4.0, and PySide2. It installs the BTV CWA model data sources under the user's profile.

## BTV model feeds

The BTV data-source file provides:
- BTV CWA RRFS (Latest)
- BTV CWA GFS (Latest)
- BTV CWA RAP (Latest)
- BTV CWA HRRR (Latest)

These use Penn State's public BUFKIT distribution service. Model availability, station coverage, and forecast hours depend on the provider's current publication.

## Workstation caveat

The portable application is unsigned and may be blocked by Windows SmartScreen or agency endpoint protection. Do not bypass NWS security controls; request review/allowlisting through the appropriate IT process. This is an alpha project, not an officially supported NWS software distribution.
