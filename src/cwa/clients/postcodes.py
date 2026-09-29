"""Resolve UK postcodes and outcodes (town-name geocoding is not supported)."""

import re
from urllib.parse import quote

from pydantic import BaseModel, Field, ValidationError

from cwa.clients.http import HTTPClient, UpstreamError


class Location(BaseModel):
    outcode: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def normalize_outcode(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?", value):
        raise ValueError("Provide a valid UK outcode, for example RG1")
    return value


class PostcodesClient:
    def __init__(self, http: HTTPClient) -> None:
        self.http = http

    def resolve(self, place: str) -> Location:
        """Resolve a postcode or outcode; reject unsupported place names."""
        compact = re.sub(r"\s+", "", place.upper())
        full = re.fullmatch(r"([A-Z]{1,2}\d[A-Z\d]?)(\d[A-Z]{2})", compact)
        if full:
            value = f"{full[1]} {full[2]}"
            endpoint = "postcodes"
        else:
            value = normalize_outcode(compact)
            endpoint = "outcodes"
        payload = self.http.get_json(f"https://api.postcodes.io/{endpoint}/{quote(value)}")
        try:
            data = payload["result"]
            return Location(
                outcode=data["outcode"], latitude=data["latitude"], longitude=data["longitude"]
            )
        except (KeyError, TypeError, ValidationError) as exc:
            raise UpstreamError("Postcode service returned no valid location") from exc
