from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from ...webhook.error_codes import WebhookErrorCode
from ...webhook.event_types import WebhookEventAsyncType

if TYPE_CHECKING:
    from ...site.models import SiteSettings


CHANNEL_STOCK_EVENTS = frozenset(
    {
        WebhookEventAsyncType.PRODUCT_VARIANT_OUT_OF_STOCK_IN_CHANNEL,
        WebhookEventAsyncType.PRODUCT_VARIANT_BACK_IN_STOCK_IN_CHANNEL,
        WebhookEventAsyncType.PRODUCT_VARIANT_OUT_OF_STOCK_FOR_CLICK_AND_COLLECT,
        WebhookEventAsyncType.PRODUCT_VARIANT_BACK_IN_STOCK_FOR_CLICK_AND_COLLECT,
    }
)


class NotifyUserEventValidationMixin:
    @classmethod
    def validate_events(cls, events, site_settings: "SiteSettings"):
        # NOTIFY_USER needs to be the only one event registered per webhook.
        # This solves issue temporarily. NOTIFY_USER will be deprecated in the future.
        if WebhookEventAsyncType.NOTIFY_USER in events and len(events) > 1:
            raise ValidationError(
                {
                    "async_events": ValidationError(
                        "The NOTIFY_USER webhook cannot be combined with other events.",
                        code=WebhookErrorCode.INVALID_NOTIFY_WITH_SUBSCRIPTION.value,
                    )
                }
            )
        if (
            site_settings is not None
            and site_settings.use_legacy_shipping_zone_stock_availability
        ):
            legacy_conflicting = CHANNEL_STOCK_EVENTS.intersection(events)
            if legacy_conflicting:
                raise ValidationError(
                    {
                        "async_events": ValidationError(
                            "Channel-scoped stock availability events cannot be "
                            "used while `useLegacyShippingZoneStockAvailability` "
                            "is enabled in site settings.",
                            code=WebhookErrorCode.INVALID_WITH_LEGACY_STOCK_AVAILABILITY.value,
                        )
                    }
                )
        return events
