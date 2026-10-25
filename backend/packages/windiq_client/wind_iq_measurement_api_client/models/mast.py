from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Mast")


@_attrs_define
class Mast:
    """
    Attributes:
        id (str):
        name (str):
        latitude (float):
        longitude (float):
        measurement_height_m (float): Messhöhe über Grund in Metern
        operator (str):
        commissioned_at (str):
    """

    id: str
    name: str
    latitude: float
    longitude: float
    measurement_height_m: float
    operator: str
    commissioned_at: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        latitude = self.latitude

        longitude = self.longitude

        measurement_height_m = self.measurement_height_m

        operator = self.operator

        commissioned_at = self.commissioned_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "measurement_height_m": measurement_height_m,
                "operator": operator,
                "commissioned_at": commissioned_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        latitude = d.pop("latitude")

        longitude = d.pop("longitude")

        measurement_height_m = d.pop("measurement_height_m")

        operator = d.pop("operator")

        commissioned_at = d.pop("commissioned_at")

        mast = cls(
            id=id,
            name=name,
            latitude=latitude,
            longitude=longitude,
            measurement_height_m=measurement_height_m,
            operator=operator,
            commissioned_at=commissioned_at,
        )

        mast.additional_properties = d
        return mast

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
