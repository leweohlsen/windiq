from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.power_curve_point import PowerCurvePoint


T = TypeVar("T", bound="Turbine")


@_attrs_define
class Turbine:
    """
    Attributes:
        id (str):
        name (str):
        rated_power_kw (float):
        hub_height_m (float):
        rotor_diameter_m (float):
        cut_in_wind_speed_ms (float):
        cut_out_wind_speed_ms (float):
        power_curve (list[PowerCurvePoint]): Stützpunkte in 1-m/s-Schritten
        version (int): Version des Datensatzes
        updated_at (str): Zeitpunkt der letzten Änderung (ISO 8601)
    """

    id: str
    name: str
    rated_power_kw: float
    hub_height_m: float
    rotor_diameter_m: float
    cut_in_wind_speed_ms: float
    cut_out_wind_speed_ms: float
    power_curve: list[PowerCurvePoint]
    version: int
    updated_at: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        rated_power_kw = self.rated_power_kw

        hub_height_m = self.hub_height_m

        rotor_diameter_m = self.rotor_diameter_m

        cut_in_wind_speed_ms = self.cut_in_wind_speed_ms

        cut_out_wind_speed_ms = self.cut_out_wind_speed_ms

        power_curve = []
        for power_curve_item_data in self.power_curve:
            power_curve_item = power_curve_item_data.to_dict()
            power_curve.append(power_curve_item)

        version = self.version

        updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "rated_power_kw": rated_power_kw,
                "hub_height_m": hub_height_m,
                "rotor_diameter_m": rotor_diameter_m,
                "cut_in_wind_speed_ms": cut_in_wind_speed_ms,
                "cut_out_wind_speed_ms": cut_out_wind_speed_ms,
                "power_curve": power_curve,
                "version": version,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.power_curve_point import PowerCurvePoint  # noqa: PLC0415

        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        rated_power_kw = d.pop("rated_power_kw")

        hub_height_m = d.pop("hub_height_m")

        rotor_diameter_m = d.pop("rotor_diameter_m")

        cut_in_wind_speed_ms = d.pop("cut_in_wind_speed_ms")

        cut_out_wind_speed_ms = d.pop("cut_out_wind_speed_ms")

        power_curve = []
        _power_curve = d.pop("power_curve")
        for power_curve_item_data in _power_curve:
            power_curve_item = PowerCurvePoint.from_dict(power_curve_item_data)

            power_curve.append(power_curve_item)

        version = d.pop("version")

        updated_at = d.pop("updated_at")

        turbine = cls(
            id=id,
            name=name,
            rated_power_kw=rated_power_kw,
            hub_height_m=hub_height_m,
            rotor_diameter_m=rotor_diameter_m,
            cut_in_wind_speed_ms=cut_in_wind_speed_ms,
            cut_out_wind_speed_ms=cut_out_wind_speed_ms,
            power_curve=power_curve,
            version=version,
            updated_at=updated_at,
        )

        turbine.additional_properties = d
        return turbine

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
