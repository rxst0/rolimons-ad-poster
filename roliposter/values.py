"""Value-aware helpers: compare offer vs request value and score ads."""
from dataclasses import dataclass

from .config import Ad, ValueSettings
from .items import ItemCatalog


@dataclass
class AdValue:
    offer_value: int
    request_value: int | None       # None when the request is tags only
    offer_demand_avg: float | None  # None when no offered item has demand assigned
    projected_offer: list[str]
    projected_request: list[str]

    @property
    def overpay_percent(self) -> float | None:
        """How much more value is offered than requested (positive = you overpay)."""
        if not self.request_value:
            return None
        return (self.offer_value - self.request_value) / self.request_value * 100


def evaluate_ad(ad: Ad, catalog: ItemCatalog) -> AdValue:
    offer = [i for i in (catalog.get(x) for x in ad.offer_item_ids) if i]
    request = [i for i in (catalog.get(x) for x in ad.request_item_ids) if i]
    demands = [i.demand for i in offer if i.demand >= 0]
    return AdValue(
        offer_value=sum(i.default_value for i in offer),
        request_value=sum(i.default_value for i in request) if request else None,
        offer_demand_avg=sum(demands) / len(demands) if demands else None,
        projected_offer=[i.name for i in offer if i.projected],
        projected_request=[i.name for i in request if i.projected],
    )


def is_overpaying(av: AdValue, settings: ValueSettings) -> bool:
    pct = av.overpay_percent
    return pct is not None and pct > settings.overpay_warn_percent


def value_warnings(ad: Ad, av: AdValue, settings: ValueSettings) -> list[str]:
    warnings = []
    if is_overpaying(av, settings):
        warnings.append(
            f"Ad '{ad.name}' offers {av.offer_value:,} but requests only {av.request_value:,} "
            f"({av.overpay_percent:+.0f}% overpay, threshold {settings.overpay_warn_percent:g}%)."
        )
    if av.projected_request:
        warnings.append(f"Ad '{ad.name}' requests projected item(s): {', '.join(av.projected_request)}.")
    return warnings


def pick_weight(av: AdValue) -> float:
    """Ads offering higher-demand items tend to get more trade offers, so weight them up."""
    demand = av.offer_demand_avg if av.offer_demand_avg is not None else 1.0
    return max(0.5, demand + 1.0)
