from mesoscale.discover_models import RAP_FILENAME_RE
from mesoscale.discover_models import RRFS_CYCLE_DIR_RE, RRFS_FILENAME_RE


def test_rrfs_pressure_level_filename():
    match = RRFS_FILENAME_RE.fullmatch("rrfs.t12z.prslev.3km.f018.conus.grib2")
    assert match.groups() == ("12", "prslev", "018")


def test_rrfs_surface_and_subhourly_filenames():
    surface = RRFS_FILENAME_RE.fullmatch("rrfs.t03z.2dfld.3km.f006.conus.grib2")
    subhourly = RRFS_FILENAME_RE.fullmatch("rrfs.t21z.2dfld.subh.3km.f003.conus.grib2")
    assert surface.groups() == ("03", "2dfld", "006")
    assert subhourly.groups() == ("21", "2dfld.subh", "003")


def test_rrfs_cycle_directory_is_two_digits():
    assert RRFS_CYCLE_DIR_RE.fullmatch("00")
    assert RRFS_CYCLE_DIR_RE.fullmatch("21")
    assert not RRFS_CYCLE_DIR_RE.fullmatch("conus")
    assert not RRFS_CYCLE_DIR_RE.fullmatch("20261112")


def test_rap_operational_filename_families():
    early = RAP_FILENAME_RE.fullmatch("rap.t12z.awp130bgrbf00.grib2")
    later = RAP_FILENAME_RE.fullmatch("rap.t12z.awp130pgrbf18.grib2")
    fallback = RAP_FILENAME_RE.fullmatch("rap.t12z.awip32f18.grib2")
    assert early.groups() == ("12", "awp130bgrb", "00")
    assert later.groups() == ("12", "awp130pgrb", "18")
    assert fallback.groups() == ("12", "awip32", "18")
    assert RAP_FILENAME_RE.fullmatch("rap.t12z.wrfprs.f18.grib2") is None
