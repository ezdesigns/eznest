# External components

The application imports independently obtained packages from PyPI:

- spyrrow 0.9.0: https://github.com/PaulDL-RS/spyrrow
- Sparrow upstream: https://github.com/JeroenGar/sparrow — MIT.
- jagua-rs upstream: https://github.com/JeroenGar/jagua-rs — MPL-2.0.
- Shapely 2.1.2: https://github.com/shapely/shapely — see its distribution license and GEOS notices.
- NumPy 2.5.3: https://github.com/numpy/numpy — see its distribution license and bundled library notices.

The Windows package includes the unmodified Python 3.12 runtime, PyInstaller bootloader, and the pinned wheels above. Their installed distribution metadata and license notices are preserved. PyInstaller's bootloader distribution exception is included with its notices. No binaries or source from MX Production Suite are part of this application.

licenses/upstream-sources.json records exact upstream URLs and SHA-256 values for the spyrrow source dependency lockfile (including platform-specific and build dependencies). licenses/rust-dependencies contains their published notices. The spyrrow 0.9.0 source lockfile is included as spyrrow-Cargo.lock. Sparrow is pinned to the exact Git revision in that lockfile.

jagua-rs is an unmodified MPL-2.0 component. Its covered source is included in licenses/jagua-rs-0.7.0-source.crate (a gzip tar archive), alongside its license notices. This preserves access to that component's source independently of the original eznest application code.

Shapely's separate GEOS 3.13.1 runtime remains in _internal/shapely.libs, with the wheel's LGPL-2.1 GEOS notices. Its unmodified upstream source is included as licenses/geos-3.13.1-source.tar.bz2, obtained from https://download.osgeo.org/geos/geos-3.13.1.tar.bz2 (SHA-256 df2c50503295f325e7c8d7b783aca8ba4773919cde984193850cf9e361dfd28c). Interface-compatible GEOS DLLs may be replaced in that folder; source build instructions are at https://libgeos.org/usage/download/.

NumPy's bundled numerical-library notices are retained with its license. Runtime library notices are in the corresponding licenses subfolders. Preserve all notices and covered source when redistributing the package.
