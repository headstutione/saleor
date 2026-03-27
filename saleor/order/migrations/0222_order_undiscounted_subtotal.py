from decimal import Decimal

from django.db import migrations, models
from django.db.models import OuterRef, Subquery, Sum


BATCH_SIZE = 1000


def populate_undiscounted_subtotals(apps, schema_editor):
    Order = apps.get_model("order", "Order")
    OrderLine = apps.get_model("order", "OrderLine")

    last_pk = 0
    while True:
        batch_pks = list(
            Order.objects.filter(pk__gt=last_pk)
            .order_by("pk")
            .values_list("pk", flat=True)[:BATCH_SIZE]
        )
        if not batch_pks:
            break

        net_subq = Subquery(
            OrderLine.objects.filter(order_id=OuterRef("pk"))
            .values("order_id")
            .annotate(s=Sum("undiscounted_total_price_net_amount"))
            .values("s")[:1]
        )
        gross_subq = Subquery(
            OrderLine.objects.filter(order_id=OuterRef("pk"))
            .values("order_id")
            .annotate(s=Sum("undiscounted_total_price_gross_amount"))
            .values("s")[:1]
        )

        orders = list(
            Order.objects.filter(pk__in=batch_pks).annotate(
                _und_net=net_subq,
                _und_gross=gross_subq,
            )
        )
        for order in orders:
            order.undiscounted_subtotal_net_amount = order._und_net or Decimal("0")
            order.undiscounted_subtotal_gross_amount = order._und_gross or Decimal("0")

        Order.objects.bulk_update(
            orders,
            ["undiscounted_subtotal_net_amount", "undiscounted_subtotal_gross_amount"],
        )
        last_pk = batch_pks[-1]


class Migration(migrations.Migration):
    dependencies = [
        ("order", "0221_remove_digital_orderevents"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="undiscounted_subtotal_net_amount",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0"),
                max_digits=20,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="undiscounted_subtotal_gross_amount",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0"),
                max_digits=20,
            ),
        ),
        migrations.RunPython(
            populate_undiscounted_subtotals,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
