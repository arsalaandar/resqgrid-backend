
from io import BytesIO

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.services.photo_gps import distance_meters, extract_photo_gps


def make_jpeg_with_gps(
    latitude=(34, 5, 1),
    latitude_ref="N",
    longitude=(74, 47, 50),
    longitude_ref="E",
):
    """Create a JPEG containing GPS EXIF metadata."""
    image = Image.new("RGB", (20, 20), color="white")
    exif = Image.Exif()

    gps_ifd = {
        1: latitude_ref,
        2: tuple(IFDRational(value, 1) for value in latitude),
        3: longitude_ref,
        4: tuple(IFDRational(value, 1) for value in longitude),
    }

    exif[34853] = gps_ifd

    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_distance_meters_returns_zero_for_same_coordinates():
    distance = distance_meters(
        34.0837, 74.7973, 34.0837, 74.7973
    )
    assert distance == 0


def test_distance_meters_accepts_point_within_100_metres():
    distance = distance_meters(
        34.0837, 74.7973, 34.0842, 74.7973
    )
    assert distance < 100


def test_distance_meters_detects_point_beyond_100_metres():
    distance = distance_meters(
        34.0837, 74.7973, 34.0848, 74.7973
    )
    assert distance > 100


@pytest.mark.parametrize(
    "coordinates",
    [
        (91, 74.7973, 34.0837, 74.7973),
        (-91, 74.7973, 34.0837, 74.7973),
        (34.0837, 181, 34.0837, 74.7973),
        (34.0837, 74.7973, 34.0837, float("nan")),
    ],
)
def test_distance_meters_rejects_invalid_coordinates(coordinates):
    with pytest.raises(ValueError):
        distance_meters(*coordinates)


def test_extract_photo_gps_reads_real_exif_metadata():
    image_bytes = make_jpeg_with_gps()

    latitude, longitude = extract_photo_gps(image_bytes)

    assert latitude == pytest.approx(34 + 5 / 60 + 1 / 3600)
    assert longitude == pytest.approx(74 + 47 / 60 + 50 / 3600)


def test_extract_photo_gps_handles_south_and_west():
    image_bytes = make_jpeg_with_gps(
        latitude=(12, 30, 0),
        latitude_ref="S",
        longitude=(45, 15, 0),
        longitude_ref="W",
    )

    latitude, longitude = extract_photo_gps(image_bytes)

    assert latitude == pytest.approx(-12.5)
    assert longitude == pytest.approx(-45.25)


def test_extract_photo_gps_rejects_jpeg_without_gps():
    image = Image.new("RGB", (20, 20), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    with pytest.raises(ValueError):
        extract_photo_gps(buffer.getvalue())


def test_extract_photo_gps_rejects_invalid_image_bytes():
    with pytest.raises(ValueError):
        extract_photo_gps(b"this is not an image")


def test_extract_photo_gps_rejects_invalid_coordinate_reference():
    image_bytes = make_jpeg_with_gps(latitude_ref="X")

    with pytest.raises(ValueError):
        extract_photo_gps(image_bytes)


def test_extract_photo_gps_rejects_out_of_range_coordinates():
    image_bytes = make_jpeg_with_gps(
        latitude=(91, 0, 0),
        latitude_ref="N",
    )

    with pytest.raises(ValueError):
        extract_photo_gps(image_bytes)
