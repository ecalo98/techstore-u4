"""Pruebas del dominio: Value Objects, invariantes, estados y eventos."""
from decimal import Decimal

import pytest

from app.domain import (
    Customer,
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    Order,
    OrderItem,
    OrderItemLimitExceeded,
    OrderStatus,
)
from cargar_csv import load_fixture


def nuevo_pedido(vip=False, activo=True, promo=False, oid="T1"):
    return Order(customer=Customer("C", vip, activo), id=oid, has_promotion=promo)


def item(qty=1, price="100.00", sku="SKU001"):
    return OrderItem(sku, qty, Money(Decimal(price)))


# ---------------- Money ----------------
def test_money_negativo():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("-1"))


def test_money_rechaza_float():
    with pytest.raises(InvalidOrderData):
        Money(600.0)


def test_money_rechaza_no_finito():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("NaN"))


def test_money_add_no_modifica_operandos():
    a, b = Money(Decimal("100")), Money(Decimal("50"))
    assert a.add(b) == Money(Decimal("150"))
    assert a.amount == Decimal("100") and b.amount == Decimal("50")


def test_money_monedas_distintas():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("1"), "MXN").add(Money(Decimal("1"), "USD"))


def test_money_es_inmutable():
    m = Money(Decimal("10"))
    with pytest.raises(Exception):
        m.amount = Decimal("99")


def test_money_igualdad_por_valor():
    assert Money(Decimal("100")) == Money(Decimal("100"))


# ---------------- OrderItem ----------------
@pytest.mark.parametrize("qty", [0, -3])
def test_item_cantidad_invalida(qty):
    with pytest.raises(InvalidOrderData):
        item(qty=qty)


def test_item_sku_vacio():
    with pytest.raises(InvalidOrderData):
        OrderItem("  ", 1, Money(Decimal("1")))


def test_item_subtotal_calculado():
    assert item(qty=2, price="600.00").subtotal.amount == Decimal("1200.00")


# ---------------- Fixture / cargador ----------------
def test_pedido_o001_inicia_draft():
    orders = load_fixture()
    assert orders["O001"].status.value == "DRAFT"
    assert orders["O001"].units == 4
    assert orders["O001"].total.amount == Decimal("2100.00")


def test_se_cargan_16_pedidos_todos_draft():
    orders = load_fixture()
    assert len(orders) == 16
    assert all(o.status == OrderStatus.DRAFT for o in orders.values())


# ---------------- Límite de 20 unidades ----------------
def test_20_unidades_exactas_permitidas():
    assert load_fixture()["O008"].units == 20


def test_21_unidades_rechazadas_y_no_modifica_items():
    o = load_fixture()["O009"]
    antes = (len(o.items), o.units)
    with pytest.raises(OrderItemLimitExceeded):
        o.add_item(item(qty=2, sku="SKU003", price="120.00"))
    assert (len(o.items), o.units) == antes


def test_limite_cuenta_unidades_no_renglones():
    o = nuevo_pedido()
    o.add_item(item(qty=10, sku="A"))
    o.add_item(item(qty=10, sku="B"))  # 2 renglones, 20 unidades: permitido
    with pytest.raises(OrderItemLimitExceeded):
        o.add_item(item(qty=1, sku="C"))


def test_no_agrega_items_fuera_de_draft():
    o = nuevo_pedido()
    o.add_item(item())
    o.confirm()
    with pytest.raises(InvalidOrderTransition):
        o.add_item(item())


def test_solo_mxn():
    o = nuevo_pedido()
    with pytest.raises(InvalidOrderData):
        o.add_item(OrderItem("X", 1, Money(Decimal("1"), "USD")))


# ---------------- confirmar ----------------
def test_confirmar_pedido_vacio():
    o = load_fixture()["O007"]
    with pytest.raises(InvalidOrderData):
        o.confirm()
    assert o.status == OrderStatus.DRAFT and o.events == []


def test_confirmar_cliente_inactivo():
    o = load_fixture()["O003"]
    with pytest.raises(InvalidOrderData):
        o.confirm()
    assert o.status == OrderStatus.DRAFT and o.events == []


def test_confirmar_exitoso_registra_evento():
    o = load_fixture()["O013"]
    o.confirm()
    assert o.status == OrderStatus.CONFIRMED
    assert [e.name for e in o.events] == ["OrderConfirmed"]
    assert o.events[0].order_id == "O013"


def test_confirmacion_doble_no_agrega_evento():
    o = load_fixture()["O013"]
    o.confirm()
    with pytest.raises(InvalidOrderTransition):
        o.confirm()
    assert o.status == OrderStatus.CONFIRMED
    assert len(o.events) == 1


# ---------------- enviar ----------------
@pytest.mark.parametrize("guia", ["", "   ", None])
def test_envio_sin_guia(guia):
    o = load_fixture()["O012"]
    o.confirm()
    with pytest.raises(InvalidOrderData):
        o.ship(guia)
    assert o.status == OrderStatus.CONFIRMED
    assert [e.name for e in o.events] == ["OrderConfirmed"]


def test_envio_desde_draft_rechazado():
    o = load_fixture()["O012"]
    with pytest.raises(InvalidOrderTransition):
        o.ship("G-1")
    assert o.events == []


def test_envio_exitoso():
    o = load_fixture()["O012"]
    o.confirm()
    o.ship("GUIA-123")
    assert o.status == OrderStatus.SHIPPED
    assert [e.name for e in o.events] == ["OrderConfirmed", "OrderShipped"]
    assert o.events[-1].detail == "GUIA-123"


# ---------------- cancelar ----------------
def test_cancelar_desde_shipped_rechazado():
    o = load_fixture()["O014"]
    o.confirm()
    o.ship("G-9")
    with pytest.raises(InvalidOrderTransition):
        o.cancel("ya no lo quiero")
    assert o.status == OrderStatus.SHIPPED
    assert [e.name for e in o.events] == ["OrderConfirmed", "OrderShipped"]


def test_cancelar_sin_motivo():
    o = load_fixture()["O014"]
    o.confirm()
    with pytest.raises(InvalidOrderData):
        o.cancel("  ")
    assert o.status == OrderStatus.CONFIRMED


def test_cancelar_desde_draft_rechazado():
    o = load_fixture()["O014"]
    with pytest.raises(InvalidOrderTransition):
        o.cancel("motivo")


def test_cancelar_exitoso():
    o = load_fixture()["O014"]
    o.confirm()
    o.cancel("Cliente cambió de opinión")
    assert o.status == OrderStatus.CANCELLED
    assert o.events[-1].name == "OrderCancelled"
    assert o.events[-1].detail == "Cliente cambió de opinión"


# ---------------- entregar / devolver ----------------
def test_entregar_y_devolver_requieren_shipped():
    o = load_fixture()["O016"]
    with pytest.raises(InvalidOrderTransition):
        o.deliver()
    with pytest.raises(InvalidOrderTransition):
        o.return_order()
    o.confirm()
    with pytest.raises(InvalidOrderTransition):
        o.deliver()
    assert len(o.events) == 1


def test_flujo_entrega():
    o = load_fixture()["O016"]
    o.confirm(); o.ship("G-1"); o.deliver()
    assert o.status == OrderStatus.DELIVERED
    assert [e.name for e in o.events] == ["OrderConfirmed", "OrderShipped", "OrderDelivered"]


def test_flujo_devolucion():
    o = load_fixture()["O015"]
    o.confirm(); o.ship("G-2"); o.return_order()
    assert o.status == OrderStatus.RETURNED
    assert o.events[-1].name == "OrderReturned"


@pytest.mark.parametrize("terminal", ["deliver", "return_order"])
def test_estados_terminales_no_aceptan_mas_operaciones(terminal):
    o = load_fixture()["O016"]
    o.confirm(); o.ship("G"); getattr(o, terminal)()
    n = len(o.events)
    for op, args in [("confirm", ()), ("ship", ("G",)), ("cancel", ("x",)),
                     ("deliver", ()), ("return_order", ())]:
        with pytest.raises(InvalidOrderTransition):
            getattr(o, op)(*args)
    assert len(o.events) == n
