from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from promise import Promise

from ....checkout.models import CheckoutDelivery
from ....checkout.problems import (
    CHANNEL_SLUG,
    CHECKOUT_LINE_PROBLEM_TYPE,
    CHECKOUT_PROBLEM_TYPE,
    COUNTRY_CODE,
    PRODUCT_ID,
    VARIANT_ID,
    get_checkout_lines_problems,
    get_checkout_problems,
)
from ....product.models import ProductChannelListing
from ....warehouse.models import Reservation, Stock
from ....warehouse.reservations import is_reservation_enabled
from ...core.dataloaders import DataLoader
from ...product.dataloaders import (
    ProductChannelListingByProductIdAndChannelSlugLoader,
)
from ...site.dataloaders import get_site_promise
from ...warehouse.dataloaders import (
    StocksWithAvailableQuantityByProductVariantIdAndChannelSlugLoader,
    StocksWithAvailableQuantityByProductVariantIdCountryCodeAndChannelLoader,
)
from .checkout_delivery import CheckoutDeliveryByIdLoader
from .checkout_infos import (
    CheckoutInfoByCheckoutTokenLoader,
    CheckoutLinesInfoByCheckoutTokenLoader,
)
from .models import CheckoutByTokenLoader


class CheckoutLinesProblemsByCheckoutIdLoader(
    DataLoader[str, dict[str, list[CHECKOUT_LINE_PROBLEM_TYPE]]]
):
    context_key = "checkout_lines_problems_by_checkout_id"

    def batch_load(self, keys):
        def _resolve_problems(data):
            checkout_infos, checkout_lines, site = data

            checkout_infos_map = {
                checkout_info.checkout.pk: checkout_info
                for checkout_info in checkout_infos
            }
            variant_data_list, product_data_list, checkout_line_ids = (
                self._collect_line_keys(checkout_lines, checkout_infos_map)
            )

            include_shipping_zones = (
                site.settings.use_legacy_shipping_zone_stock_availability
            )
            variant_stocks = self._load_variant_stocks(
                variant_data_list, include_shipping_zones
            )
            product_channel_listings = (
                ProductChannelListingByProductIdAndChannelSlugLoader(
                    self.context
                ).load_many(product_data_list)
            )

            def _with_stocks(data):
                variant_stocks, product_channel_listings = data
                variant_stock_map: dict[
                    tuple[VARIANT_ID, CHANNEL_SLUG, COUNTRY_CODE], Iterable[Stock]
                ] = dict(zip(variant_data_list, variant_stocks, strict=False))
                product_channel_listings_map: dict[
                    tuple[PRODUCT_ID, CHANNEL_SLUG], ProductChannelListing
                ] = dict(zip(product_data_list, product_channel_listings, strict=False))

                stock_ids = {
                    stock.id
                    for stocks in variant_stock_map.values()
                    for stock in stocks
                }
                reservations_enabled = bool(stock_ids) and is_reservation_enabled(
                    site.settings
                )
                reserved_quantity_by_stock = (
                    self._fetch_reserved_quantity_by_stock(stock_ids)
                    if reservations_enabled
                    else {}
                )
                own_reserved_by_line_id = (
                    self._fetch_own_reservations_by_line_id(
                        checkout_line_ids, stock_ids
                    )
                    if reservations_enabled and checkout_line_ids
                    else {}
                )

                problems = {}
                for checkout_info, lines in zip(
                    checkout_infos, checkout_lines, strict=False
                ):
                    effective_reserved_qty_by_stock = self._effective_reserved(
                        reserved_quantity_by_stock, lines, own_reserved_by_line_id
                    )
                    problems[checkout_info.checkout.pk] = get_checkout_lines_problems(
                        checkout_info,
                        lines,
                        variant_stock_map,
                        product_channel_listings_map,
                        reserved_quantity_by_stock=effective_reserved_qty_by_stock,
                    )
                return [problems.get(key, []) for key in keys]

            return Promise.all([variant_stocks, product_channel_listings]).then(
                _with_stocks
            )

        checkout_infos = CheckoutInfoByCheckoutTokenLoader(self.context).load_many(keys)
        lines = CheckoutLinesInfoByCheckoutTokenLoader(self.context).load_many(keys)
        site = get_site_promise(self.context)
        return Promise.all([checkout_infos, lines, site]).then(_resolve_problems)

    @staticmethod
    def _collect_line_keys(checkout_lines, checkout_infos_map):
        variant_data_set: set[tuple[VARIANT_ID, CHANNEL_SLUG, COUNTRY_CODE]] = set()
        product_data_set: set[tuple[PRODUCT_ID, CHANNEL_SLUG]] = set()
        checkout_line_ids: list[UUID] = []
        for lines in checkout_lines:
            for line in lines:
                checkout_line_ids.append(line.line.pk)
                variant_data_set.add(
                    (
                        line.variant.id,
                        line.channel.slug,
                        checkout_infos_map[line.line.checkout_id].checkout.country,
                    )
                )
                product_data_set.add((line.product.id, line.channel.slug))
        return list(variant_data_set), list(product_data_set), checkout_line_ids

    def _load_variant_stocks(self, variant_data_list, include_shipping_zones):
        if include_shipping_zones:
            cc_loader = StocksWithAvailableQuantityByProductVariantIdCountryCodeAndChannelLoader(  # noqa: E501
                self.context
            )
            return cc_loader.load_many(
                [
                    (variant_id, country_code, channel_slug)
                    for variant_id, channel_slug, country_code in variant_data_list
                ]
            )
        channel_loader = (
            StocksWithAvailableQuantityByProductVariantIdAndChannelSlugLoader(
                self.context
            )
        )
        return channel_loader.load_many(
            [
                (variant_id, channel_slug)
                for variant_id, channel_slug, _country_code in variant_data_list
            ]
        )

    def _fetch_reserved_quantity_by_stock(self, stock_ids):
        reserved_quantity_by_stock: dict[int, int] = defaultdict(int)
        rows = (
            Stock.objects.using(self.database_connection_name)
            .filter(id__in=stock_ids)
            .annotate_reserved_quantity()
            .values_list("id", "reserved_quantity")
        )
        for stock_id, reserved in rows:
            reserved_quantity_by_stock[stock_id] = reserved
        return reserved_quantity_by_stock

    def _fetch_own_reservations_by_line_id(self, checkout_line_ids, stock_ids):
        own_reserved_by_line_id: defaultdict[UUID, dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        rows = (
            Reservation.objects.using(self.database_connection_name)
            .filter(
                checkout_line_id__in=checkout_line_ids,
                stock_id__in=stock_ids,
            )
            .not_expired()
            .values_list("checkout_line_id", "stock_id", "quantity_reserved")
        )
        for line_id, stock_id, quantity in rows:
            own_reserved_by_line_id[line_id][stock_id] += quantity
        return own_reserved_by_line_id

    @staticmethod
    def _effective_reserved(reserved_quantity_by_stock, lines, own_reserved_by_line_id):
        """Subtract the checkout's own reservations from the per-stock totals.

        This ensures the user is not blocked by their own pending reservations.
        """
        effective = dict(reserved_quantity_by_stock)
        for line in lines:
            for stock_id, quantity in own_reserved_by_line_id.get(
                line.line.pk, {}
            ).items():
                effective[stock_id] = effective.get(stock_id, 0) - quantity
        return effective


class CheckoutProblemsByCheckoutIdDataloader(
    DataLoader[str, dict[str, list[CHECKOUT_PROBLEM_TYPE]]]
):
    context_key = "checkout_problems_by_checkout_id"

    def batch_load(self, keys):
        def _with_assigned_delivery(checkouts):
            def _resolve_problems(
                data: tuple[
                    list[dict[str, list[CHECKOUT_LINE_PROBLEM_TYPE]]],
                    list[CheckoutDelivery | None],
                ],
            ):
                checkouts_lines_problems, checkouts_deliveries = data
                checkout_problems = defaultdict(list)
                checkout_delivery_map = {
                    delivery.pk: delivery
                    for delivery in checkouts_deliveries
                    if delivery
                }
                for checkout_lines_problems, checkout in zip(
                    checkouts_lines_problems,
                    checkouts,
                    strict=False,
                ):
                    checkout_problems[checkout.pk] = get_checkout_problems(
                        checkout,
                        checkout_delivery_map.get(checkout.assigned_delivery_id),
                        checkout_lines_problems,
                    )

                return [checkout_problems.get(key, []) for key in keys]

            assigned_delivery_ids = [
                checkout.assigned_delivery_id
                for checkout in checkouts
                if checkout.assigned_delivery_id
            ]
            checkout_delivery_dataloader = CheckoutDeliveryByIdLoader(self.context)
            line_problems_dataloader = CheckoutLinesProblemsByCheckoutIdLoader(
                self.context
            )
            return Promise.all(
                [
                    line_problems_dataloader.load_many(keys),
                    checkout_delivery_dataloader.load_many(assigned_delivery_ids),
                ]
            ).then(_resolve_problems)

        return (
            CheckoutByTokenLoader(self.context)
            .load_many(keys)
            .then(_with_assigned_delivery)
        )
