from io import BytesIO
from math import (
    atan2,
    cos,
    isfinite,
    radians,
    sin,
    sqrt,
)

from PIL import ExifTags, Image, UnidentifiedImageError

GPS_IFD_TAG = 34853
EARTH_RADIUS_METERS = 6_371_000


def _dms_to_decimal(
    values,
    reference: str,
) -> float:
    """Convert GPS degrees, minutes and seconds to decimal coordinates."""

    if len(values) != 3:
        raise ValueError("Invalid GPS coordinate format.")

    try:
        degrees, minutes, seconds = (float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid GPS coordinate values.") from exc

    if not all(isfinite(value) for value in (degrees, minutes, seconds)):
        raise ValueError("GPS coordinates must be finite numbers.")

    # Degrees must be non-negative in DMS representation.
    if degrees < 0:
        raise ValueError("Invalid GPS degree value.")

    if not (0 <= minutes < 60 and 0 <= seconds < 60):
        raise ValueError("Invalid GPS coordinate values.")

    decimal = degrees + minutes / 60 + seconds / 3600

    if not isfinite(decimal):
        raise ValueError("GPS coordinate must be finite.")

    if reference in ("S", "W"):
        decimal = -decimal
    elif reference not in ("N", "E"):
        raise ValueError("Invalid GPS direction reference.")

    return decimal


def extract_photo_gps(
    image_bytes: bytes,
) -> tuple[float, float]:
    """
    Extract latitude and longitude from embedded EXIF GPS metadata.

    Returns:
        Tuple containing (latitude, longitude).

    Raises:
        ValueError if GPS coordinates are missing, malformed,
        or outside valid geographic ranges.
    """

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            exif = image.getexif()

            if not exif or GPS_IFD_TAG not in exif:
                raise ValueError("Photo does not contain embedded GPS coordinates.")

            gps_ifd = exif.get_ifd(GPS_IFD_TAG)

            # Convert numeric EXIF GPS tag IDs to readable names.
            gps = {
                ExifTags.GPSTAGS.get(tag, tag): value for tag, value in gps_ifd.items()
            }

            required = (
                "GPSLatitude",
                "GPSLatitudeRef",
                "GPSLongitude",
                "GPSLongitudeRef",
            )

            if any(tag not in gps for tag in required):
                raise ValueError("Photo has incomplete embedded GPS coordinates.")

            latitude_reference = gps["GPSLatitudeRef"]
            longitude_reference = gps["GPSLongitudeRef"]

            # Normalize EXIF reference values.
            if isinstance(latitude_reference, bytes):
                latitude_reference = latitude_reference.decode("ascii", errors="strict")

            if isinstance(longitude_reference, bytes):
                longitude_reference = longitude_reference.decode(
                    "ascii", errors="strict"
                )

            latitude = _dms_to_decimal(
                gps["GPSLatitude"],
                str(latitude_reference).strip().upper(),
            )

            longitude = _dms_to_decimal(
                gps["GPSLongitude"],
                str(longitude_reference).strip().upper(),
            )

            if not isfinite(latitude) or not -90 <= latitude <= 90:
                raise ValueError("Invalid GPS latitude.")

            if not isfinite(longitude) or not -180 <= longitude <= 180:
                raise ValueError("Invalid GPS longitude.")

            return latitude, longitude

    except ValueError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        KeyError,
        TypeError,
        ZeroDivisionError,
        OverflowError,
        UnicodeError,
    ) as exc:
        raise ValueError("Unable to read valid GPS metadata from this photo.") from exc


def distance_meters(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    """
    Calculate approximate surface distance between two GPS points
    using the Haversine formula.

    Coordinates must be finite numeric values in valid geographic ranges.
    """

    values = (
        latitude1,
        longitude1,
        latitude2,
        longitude2,
    )

    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        for value in values
    ):
        raise ValueError("Coordinates must be finite numeric values.")

    if not (
        -90 <= latitude1 <= 90
        and -90 <= latitude2 <= 90
        and -180 <= longitude1 <= 180
        and -180 <= longitude2 <= 180
    ):
        raise ValueError("Coordinates are outside valid geographic ranges.")

    lat1 = radians(latitude1)
    lat2 = radians(latitude2)

    delta_lat = radians(latitude2 - latitude1)
    delta_lon = radians(longitude2 - longitude1)

    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2

    # Protect against floating-point rounding errors.
    a = max(0.0, min(1.0, a))

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a),
    )

    return EARTH_RADIUS_METERS * c
