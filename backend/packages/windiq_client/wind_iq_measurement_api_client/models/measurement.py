from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Measurement")


@_attrs_define
class Measurement:
    """
    Attributes:
        timestamp (str): Beginn der Messstunde, ISO 8601 mit Zeitzonenangabe
        wind_speed (float | None | str): Mittlere Windgeschwindigkeit der Stunde auf Messhöhe
        unit (str): Einheit von `wind_speed`
        wind_direction_deg (int): Windrichtung in Grad (0 = Nord)
        version (int): Version des Werts
        updated_at (str): Zeitpunkt der letzten Änderung dieses Werts (ISO 8601)
    """

    timestamp: str
    wind_speed: float | None | str
    unit: str
    wind_direction_deg: int
    version: int
    updated_at: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        timestamp = self.timestamp

        wind_speed: float | None | str
        wind_speed = self.wind_speed

        unit = self.unit

        wind_direction_deg = self.wind_direction_deg

        version = self.version

        updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "timestamp": timestamp,
                "wind_speed": wind_speed,
                "unit": unit,
                "wind_direction_deg": wind_direction_deg,
                "version": version,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        timestamp = d.pop("timestamp")

        def _parse_wind_speed(data: object) -> float | None | str:
            if data is None:
                return data
            return cast(float | None | str, data)

        wind_speed = _parse_wind_speed(d.pop("wind_speed"))

        unit = d.pop("unit")

        wind_direction_deg = d.pop("wind_direction_deg")

        version = d.pop("version")

        updated_at = d.pop("updated_at")

        measurement = cls(
            timestamp=timestamp,
            wind_speed=wind_speed,
            unit=unit,
            wind_direction_deg=wind_direction_deg,
            version=version,
            updated_at=updated_at,
        )

        measurement.additional_properties = d
        return measurement

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
