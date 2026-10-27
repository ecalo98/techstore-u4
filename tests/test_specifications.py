"""Pruebas del Specification Pattern y de las reglas de descuento."""
from decimal import Decimal

from app.domain import Customer, Money, Order, OrderItem
from app.specifications import (
    ActiveCustomerSpec,
    ActivePromotionSpec,
    MinimumAmountSpec,
    MinimumUnitsSpec,
    VIPCustomerSpec,
    any_discount,
    discount_amount,
    discount_rate,
    five_percent,
    ten_percent,
    total_with_discount,
)
from cargar_csv import load_fixture


def pedido(vip=False, promo=False, activo=True, lineas=()):
    o = Order(Customer("C", vip, activo), "T", has_promotion=promo)
    for qty, price in lineas:
        o.add_item(OrderItem("S", qty, Money(Decimal(price))))
    return o


# ---------- reglas simples ----------
def test_monto_minimo_es_estricto():
    spec = MinimumAmountSpec(Decimal("500"))
    assert not spec.is_satisfied_by(pedido(lineas=[(1, "500.00")]))
    assert spec.is_satisfied_by(pedido(lineas=[(1, "500.01")]))


def test_unidades_minimas_incluyen_el_limite():
    spec = MinimumUnitsSpec(4)
    assert not spec.is_satisfied_by(pedido(lineas=[(3, "1")]))
    assert spec.is_satisfied_by(pedido(lineas=[(4, "1")]))


def test_unidades_se_suman_entre_renglones():
    assert MinimumUnitsSpec(4).is_satisfied_by(pedido(lineas=[(2, "1"), (2, "1")]))


def test_vip_promocion_y_cliente_activo():
    assert VIPCustomerSpec().is_satisfied_by(pedido(vip=True))
    assert not VIPCustomerSpec().is_satisfied_by(pedido())
    assert ActivePromotionSpec().is_satisfied_by(pedido(promo=True))
    assert not ActiveCustomerSpec().is_satisfied_by(pedido(activo=False))


# ---------- composición AND / OR / NOT ----------
def test_and_or_not():
    vip, promo = VIPCustomerSpec(), ActivePromotionSpec()
    o_vip = pedido(vip=True)
    assert (vip & ~promo).is_satisfied_by(o_vip)
    assert not (vip & promo).is_satisfied_by(o_vip)
    assert (vip | promo).is_satisfied_by(o_vip)
    assert not (~vip | promo).is_satisfied_by(o_vip)
    assert (~(vip & promo)).is_satisfied_by(o_vip)


def test_specification_no_modifica_el_pedido():
    o = pedido(vip=True, lineas=[(4, "200")])
    antes = (o.status, o.units, o.total, list(o.items), list(o.events))
    any_discount.is_satisfied_by(o)
    assert antes == (o.status, o.units, o.total, list(o.items), list(o.events))


# ---------- reglas de descuento con los datos del paquete ----------
def test_o001_descuento_vip_10():
    o = load_fixture()["O001"]
    assert ten_percent.is_satisfied_by(o)
    assert discount_rate(o) == Decimal("0.10")
    assert discount_amount(o).amount == Decimal("210.00")
    assert total_with_discount(o).amount == Decimal("1890.00")


def test_o002_no_vip_sin_descuento():
    assert discount_rate(load_fixture()["O002"]) == Decimal("0")


def test_o005_promocion_activa_bloquea():
    o = load_fixture()["O005"]
    assert not ten_percent.is_satisfied_by(o)
    assert not five_percent.is_satisfied_by(o)
    assert discount_rate(o) == Decimal("0")


def test_o006_descuento_alterno_5():
    o = load_fixture()["O006"]
    assert not ten_percent.is_satisfied_by(o)
    assert five_percent.is_satisfied_by(o)
    assert discount_rate(o) == Decimal("0.05")
    assert discount_amount(o).amount == Decimal("900.00")
    assert total_with_discount(o).amount == Decimal("17100.00")


def test_o010_umbral_estricto_exactamente_500():
    o = load_fixture()["O010"]
    assert o.total.amount == Decimal("500.00")
    assert discount_rate(o) == Decimal("0")


def test_o011_vip_con_3_unidades_sin_descuento():
    o = load_fixture()["O011"]
    assert o.customer.is_vip and o.units == 3
    assert discount_rate(o) == Decimal("0")


def test_prioridad_10_sobre_5_cuando_ambas_aplican():
    o = pedido(vip=True, lineas=[(5, "1200.00")])  # 6000, VIP, 5 uds, sin promo
    assert ten_percent.is_satisfied_by(o) and five_percent.is_satisfied_by(o)
    assert discount_rate(o) == Decimal("0.10")


def test_5000_exacto_no_califica_para_5():
    o = pedido(lineas=[(1, "5000.00")])
    assert not five_percent.is_satisfied_by(o)
    assert not any_discount.is_satisfied_by(o)


def test_pedido_vacio_sin_descuento():
    assert discount_rate(load_fixture()["O007"]) == Decimal("0")
