"""Data models for the Email Parcel Tracking integration."""

from dataclasses import dataclass
from datetime import date, datetime

from .const import STATUS_RANK


@dataclass(slots=True)
class Shipment:
    """One parcel across its lifecycle (retailer confirmation → courier)."""

    uid: str = ""
    order_number: str | None = None
    tracking_number: str | None = None
    retailer: str | None = None
    courier: str | None = None
    status: str | None = None
    eta: date | None = None
    updated: datetime | None = None

    @property
    def carrier_label(self) -> str | None:
        """Current handler: the courier once known, else the retailer."""
        return self.courier or self.retailer

    def to_dict(self) -> dict[str, str | None]:
        """Return a JSON-serialisable representation for the Store."""
        return {
            "uid": self.uid,
            "order_number": self.order_number,
            "tracking_number": self.tracking_number,
            "retailer": self.retailer,
            "courier": self.courier,
            "status": self.status,
            "eta": self.eta.isoformat() if self.eta else None,
            "updated": self.updated.isoformat() if self.updated else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | None]) -> Shipment:
        """Rebuild a Shipment from stored JSON."""
        eta = data.get("eta")
        updated = data.get("updated")
        return cls(
            uid=data.get("uid") or "",
            order_number=data.get("order_number"),
            tracking_number=data.get("tracking_number"),
            retailer=data.get("retailer"),
            courier=data.get("courier"),
            status=data.get("status"),
            eta=date.fromisoformat(eta) if eta else None,
            updated=datetime.fromisoformat(updated) if updated else None,
        )

    def merge(self, other: Shipment) -> None:
        """Merge a newer parsed update in place (identity/uid preserved)."""
        for attr in ("order_number", "tracking_number", "retailer", "courier", "eta"):
            value = getattr(other, attr)
            if value is not None:
                setattr(self, attr, value)
        if other.status is not None and self._status_advances(other.status):
            self.status = other.status
        if other.updated is not None and (
            self.updated is None or other.updated > self.updated
        ):
            self.updated = other.updated

    def _status_advances(self, new: str) -> bool:
        """Whether ``new`` should replace the current status."""
        if self.status is None:
            return True
        return STATUS_RANK.get(new, -1) >= STATUS_RANK.get(self.status, -1)
