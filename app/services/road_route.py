"""Read driving distance, time and geometry from a configured OSRM server."""

import json
import logging
from urllib.error import URLError
from urllib.request import urlopen

from app.core.config import settings

logger = logging.getLogger(__name__)


def driving_route(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng):
    if not settings.OSRM_URL:
        return None

    points = f"{pickup_lng},{pickup_lat};{dropoff_lng},{dropoff_lat}"
    url = f"{settings.OSRM_URL.rstrip('/')}/route/v1/driving/{points}"
    try:
        with urlopen(f"{url}?overview=full&geometries=geojson", timeout=4) as response:
            result = json.load(response)
        if result.get("code") != "Ok":
            return None
        route = result["routes"][0]
        coordinates = route["geometry"]["coordinates"]
        return (
            float(route["distance"]),
            max(1, round(route["duration"])),
            [[lat, lng] for lng, lat in coordinates],
        )
    except (URLError, OSError, ValueError, TypeError, KeyError, IndexError):
        logger.warning("OSRM route unavailable")
        return None
