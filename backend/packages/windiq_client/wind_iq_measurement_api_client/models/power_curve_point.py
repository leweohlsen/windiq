from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="PowerCurvePoint")


@_attrs_define
class PowerCurvePoint:
    """
    Attributes:
        wind_speed_ms (float): Windgeschwindigkeit auf Nabenhöhe in m/s
        power_kw (float): Elektrische Leistung in kW
    """

    wind_speed_ms: float
    power_kw: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        wind_speed_ms = self.wind_speed_ms

        power_kw = self.power_kw

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "wind_speed_ms": wind_speed_ms,
                "power_kw": power_kw,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        wind_speed_ms = d.pop("wind_speed_ms")

        power_kw = d.pop("power_kw")

        power_curve_point = cls(
            wind_speed_ms=wind_speed_ms,
            power_kw=power_kw,
        )

        power_curve_point.additional_properties = d
        return power_curve_point

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
