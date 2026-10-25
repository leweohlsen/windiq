from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.losses import Losses


T = TypeVar("T", bound="Site")


@_attrs_define
class Site:
    """
    Attributes:
        id (str):
        name (str):
        mast_id (str):
        shear_exponent (float): Höhenexponent α für die Höhenumrechnung
        losses (Losses):
        uncertainty (float): Gesamtunsicherheit U als Anteil (0,10 = 10 %)
        version (int): Version des Datensatzes
        updated_at (str): Zeitpunkt der letzten Änderung (ISO 8601)
    """

    id: str
    name: str
    mast_id: str
    shear_exponent: float
    losses: Losses
    uncertainty: float
    version: int
    updated_at: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        mast_id = self.mast_id

        shear_exponent = self.shear_exponent

        losses = self.losses.to_dict()

        uncertainty = self.uncertainty

        version = self.version

        updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "mast_id": mast_id,
                "shear_exponent": shear_exponent,
                "losses": losses,
                "uncertainty": uncertainty,
                "version": version,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.losses import Losses  # noqa: PLC0415

        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        mast_id = d.pop("mast_id")

        shear_exponent = d.pop("shear_exponent")

        losses = Losses.from_dict(d.pop("losses"))

        uncertainty = d.pop("uncertainty")

        version = d.pop("version")

        updated_at = d.pop("updated_at")

        site = cls(
            id=id,
            name=name,
            mast_id=mast_id,
            shear_exponent=shear_exponent,
            losses=losses,
            uncertainty=uncertainty,
            version=version,
            updated_at=updated_at,
        )

        site.additional_properties = d
        return site

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
