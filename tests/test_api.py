"""Pruebas HTTP de la API (FastAPI TestClient)."""
import pytest
from fastapi.testclient import TestClient

from app import api
from cargar_csv import load_fixture


@pytest.fixture
def client():
    api.orders.clear()
    api.orders.update(load_fixture())  # estado limpio para cada prueba
    return TestClient(api.app)


def test_404_pedido_inexistente(client):
    r = client.post("/orders/NOEXISTE/confirm")
    assert r.status_code == 404


def test_get_pedido(client):
    r = client.get("/orders/O001")
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["units"], body["total"]) == ("DRAFT", 4, "2100.00")


def test_listar_16_pedidos(client):
    assert len(client.get("/orders").json()) == 16


def test_confirmar_ok_200(client):
    r = client.post("/orders/O013/confirm")
    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED"
    assert [e["name"] for e in r.json()["events"]] == ["OrderConfirmed"]


def test_confirmar_dos_veces_409(client):
    client.post("/orders/O013/confirm")
    r = client.post("/orders/O013/confirm")
    assert r.status_code == 409
    assert len(client.get("/orders/O013").json()["events"]) == 1


def test_confirmar_pedido_vacio_422(client):
    assert client.post("/orders/O007/confirm").status_code == 422


def test_confirmar_cliente_inactivo_422(client):
    assert client.post("/orders/O003/confirm").status_code == 422


def test_enviar_sin_guia_422(client):
    client.post("/orders/O012/confirm")
    assert client.post("/orders/O012/ship").status_code == 422
    assert client.post("/orders/O012/ship", json={"tracking_number": ""}).status_code == 422
    assert client.get("/orders/O012").json()["status"] == "CONFIRMED"


def test_enviar_con_guia_200(client):
    client.post("/orders/O012/confirm")
    r = client.post("/orders/O012/ship", json={"tracking_number": "G-1"})
    assert r.status_code == 200 and r.json()["status"] == "SHIPPED"


def test_cancelar_desde_shipped_409(client):
    client.post("/orders/O014/confirm")
    client.post("/orders/O014/ship", json={"tracking_number": "G-2"})
    r = client.post("/orders/O014/cancel", json={"reason": "tarde"})
    assert r.status_code == 409
    assert client.get("/orders/O014").json()["status"] == "SHIPPED"


def test_cancelar_sin_motivo_422(client):
    client.post("/orders/O014/confirm")
    assert client.post("/orders/O014/cancel").status_code == 422


def test_cancelar_ok(client):
    client.post("/orders/O014/confirm")
    r = client.post("/orders/O014/cancel", json={"reason": "Error de captura"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"


def test_entregar_y_devolver(client):
    for oid, op, final in [("O016", "deliver", "DELIVERED"), ("O015", "return", "RETURNED")]:
        client.post(f"/orders/{oid}/confirm")
        client.post(f"/orders/{oid}/ship", json={"tracking_number": "G"})
        r = client.post(f"/orders/{oid}/{op}")
        assert r.status_code == 200 and r.json()["status"] == final


def test_agregar_21_unidades_422(client):
    r = client.post("/orders/O009/items",
                    json={"sku": "SKU003", "quantity": 2, "unit_price": "120.00"})
    assert r.status_code == 422
    assert client.get("/orders/O009").json()["units"] == 19


def test_agregar_item_ok(client):
    r = client.post("/orders/O009/items",
                    json={"sku": "SKU003", "quantity": 1, "unit_price": "120.00"})
    assert r.status_code == 200 and r.json()["units"] == 20


def test_crear_pedido_y_duplicado(client):
    body = {"id": "O100", "customer_id": "C001", "is_vip": True}
    assert client.post("/orders", json=body).status_code == 201
    assert client.post("/orders", json=body).status_code == 409


def test_descuento_endpoint(client):
    r = client.get("/orders/O001/discount").json()
    assert r["eligible"] is True and r["rate"] == "0.10"
    assert r["total_with_discount"] == "1890.00"
    assert client.get("/orders/O001").json()["status"] == "DRAFT"  # no modifica


def test_descuento_pedido_inexistente_404(client):
    assert client.get("/orders/XYZ/discount").status_code == 404


def test_openapi_documenta_endpoints(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/orders/{order_id}/confirm" in paths
    assert "post" in paths["/orders/{order_id}/confirm"]
    assert client.get("/docs").status_code == 200
