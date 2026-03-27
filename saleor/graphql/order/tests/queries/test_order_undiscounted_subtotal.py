import graphene
from prices import Money, TaxedMoney

from .....core.prices import quantize_price
from .....core.taxes import zero_taxed_money
from ....tests.utils import get_graphql_content


ORDER_UNDISCOUNTED_SUBTOTAL_QUERY = """
    query OrderUndiscountedSubtotal($id: ID!) {
        order(id: $id) {
            undiscountedSubtotal {
                gross {
                    amount
                    currency
                }
                net {
                    amount
                    currency
                }
            }
            lines {
                undiscountedTotalPrice {
                    gross {
                        amount
                    }
                    net {
                        amount
                    }
                }
            }
        }
    }
"""


def test_undiscounted_subtotal_equals_sum_of_line_undiscounted_totals(
    staff_api_client, permission_group_manage_orders, order_with_lines
):
    # given
    order = order_with_lines
    permission_group_manage_orders.user_set.add(staff_api_client.user)
    variables = {"id": graphene.Node.to_global_id("Order", order.pk)}

    # when
    response = staff_api_client.post_graphql(ORDER_UNDISCOUNTED_SUBTOTAL_QUERY, variables)

    # then
    content = get_graphql_content(response)
    data = content["data"]["order"]
    assert data is not None

    order.refresh_from_db()
    expected = zero_taxed_money(order.currency)
    for line in order.lines.all():
        line.refresh_from_db()
        expected += line.undiscounted_total_price
    expected = quantize_price(expected, order.currency)
    assert order.undiscounted_subtotal == expected

    api_subtotal = data["undiscountedSubtotal"]
    currency = api_subtotal["gross"]["currency"]
    api_taxed = TaxedMoney(
        net=Money(api_subtotal["net"]["amount"], currency),
        gross=Money(api_subtotal["gross"]["amount"], currency),
    )
    assert api_taxed == expected
    order.refresh_from_db()
    assert order.undiscounted_subtotal == api_taxed

    line_sum = zero_taxed_money(currency)
    for line_data in data["lines"]:
        line_sum += TaxedMoney(
            net=Money(line_data["undiscountedTotalPrice"]["net"]["amount"], currency),
            gross=Money(
                line_data["undiscountedTotalPrice"]["gross"]["amount"], currency
            ),
        )
    assert quantize_price(line_sum, currency) == expected
