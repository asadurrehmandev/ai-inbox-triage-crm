"""Money shapes from the held-out notes. Recognition is by format, not by sender."""

import pytest

from app.budget import extract_budget


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("budget's 5k-ish, flexible", "$5,000"),
        ("Our budget is €3.000 for the first phase.", "€3,000"),
        ("We have around $12k set aside for it.", "$12,000"),
        ("We have set aside £15,000 – £20,000 depending on scope.", "£15,000–£20,000"),
        ("Tenemos un presupuesto de 4.000 USD.", "$4,000"),
        ("Notre budget est d'environ 8 000 €.", "€8,000"),
        ("Rechnung über 1.200,00 €.", "€1,200"),
        ("I can pay $80/hr for roughly 20 hours.", "$80/hr"),
        ("Budget is USD 25,000.", "$25,000"),
        ("got like 2 grand for it", "$2,000"),
        ("予算は50万円です。", "¥500,000"),
        ("thinking 3-4 thousand dollars for it", "$3,000–$4,000"),
        ("somewhere between 15 and 20k for v1", "$15,000–$20,000"),
        ("roughly fifteen hundred quid to spend", "£1,500"),
        ("orçamento de R$ 20.000", "R$20,000"),
        ("presupuesto de 120.000 MXN", "MXN120,000"),
        ("We can spend 4800 dollars.", "$4,800"),
        ("We have 10k subscribers and 2,500 customers. Budget TBD.", None),
        ("Could you send a quote? We have 10k followers. Budget TBD.", None),
    ],
)
def test_budget_shapes(text, expected):
    assert extract_budget(text) == expected
