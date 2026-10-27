"""API REST de TechStore U4.

Los controladores son delgados: buscan el pedido, llaman al método del
dominio y devuelven un DTO. Las reglas de negocio viven en app/domain.py y
las excepciones de dominio se traducen a HTTP en UN solo lugar (abajo).
"""
from decimal import Decimal, InvalidOperation

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domain import (
    Customer,
    DomainException,
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    Order,
    OrderItem,
    OrderItemLimitExceeded,
)
from app.specifications import (
    any_discount,
    discount_amount,
    discount_rate,
    total_with_discount,
)
from cargar_csv import load_fixture

app = FastAPI(
    title="TechStore U4",
    description="Núcleo de negocio de pedidos: estados, descuentos y eventos.",
    version="1.0.0",
)

# Repositorio en memoria (se pierde al cerrar el programa).
orders: dict[str, Order] = load_fixture()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class ShipRequest(BaseModel):
    tracking_number: str = ""


class CancelRequest(BaseModel):
    reason: str = ""


class CreateOrderRequest(BaseModel):
    id: str
    customer_id: str
    is_vip: bool = False
    active: bool = True
    has_promotion: bool = False


class AddItemRequest(BaseModel):
    sku: str
    quantity: int
    unit_price: str  # texto para construir Decimal sin pasar por float


class EventDTO(BaseModel):
    name: str
    order_id: str
    occurred_at: str
    detail: str = ""


class OrderDTO(BaseModel):
    id: str
    customer_id: str
    status: str
    units: int
    total: str
    currency: str
    has_promotion: bool
    events: list[EventDTO]


class DiscountDTO(BaseModel):
    id: str
    eligible: bool
    rate: str
    discount: str
    total: str
    total_with_discount: str


def to_dto(order: Order) -> OrderDTO:
    return OrderDTO(
        id=order.id,
        customer_id=order.customer.id,
        status=order.status.value,
        units=order.units,
        total=str(order.total.amount),
        currency=order.total.currency,
        has_promotion=order.has_promotion,
        events=[
            EventDTO(
                name=e.name,
                order_id=e.order_id,
                occurred_at=e.occurred_at.isoformat(),
                detail=e.detail,
            )
            for e in order.events
        ],
    )


def get_order_or_404(order_id: str) -> Order:
    order = orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"No existe el pedido {order_id}")
    return order


# ---------------------------------------------------------------------------
# Traducción de excepciones de dominio -> HTTP semántico
# ---------------------------------------------------------------------------
@app.exception_handler(InvalidOrderTransition)
async def on_invalid_transition(_: Request, exc: InvalidOrderTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InvalidOrderData)
async def on_invalid_data(_: Request, exc: InvalidOrderData):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(OrderItemLimitExceeded)
async def on_limit_exceeded(_: Request, exc: OrderItemLimitExceeded):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(DomainException)
async def on_domain_exception(_: Request, exc: DomainException):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
@app.get("/orders", response_model=list[OrderDTO], tags=["pedidos"])
def list_orders():
    return [to_dto(o) for o in orders.values()]


@app.get("/orders/{order_id}", response_model=OrderDTO, tags=["pedidos"])
def get_order(order_id: str):
    return to_dto(get_order_or_404(order_id))


@app.get("/orders/{order_id}/discount", response_model=DiscountDTO, tags=["descuentos"])
def evaluate_discount(order_id: str):
    """Evalúa las Specifications de descuento SIN modificar el pedido."""
    order = get_order_or_404(order_id)
    return DiscountDTO(
        id=order.id,
        eligible=any_discount.is_satisfied_by(order),
        rate=str(discount_rate(order)),
        discount=str(discount_amount(order).amount),
        total=str(order.total.amount),
        total_with_discount=str(total_with_discount(order).amount),
    )


# ---------------------------------------------------------------------------
# Comandos (cambian estado => POST)
# ---------------------------------------------------------------------------
@app.post("/orders", response_model=OrderDTO, status_code=201, tags=["pedidos"])
def create_order(body: CreateOrderRequest):
    if body.id in orders:
        raise HTTPException(status_code=409, detail=f"Ya existe el pedido {body.id}")
    order = Order(
        customer=Customer(body.customer_id, body.is_vip, body.active),
        id=body.id,
        has_promotion=body.has_promotion,
    )
    orders[order.id] = order
    return to_dto(order)


@app.post("/orders/{order_id}/items", response_model=OrderDTO, tags=["pedidos"])
def add_item(order_id: str, body: AddItemRequest):
    order = get_order_or_404(order_id)
    try:
        price = Decimal(body.unit_price)
    except InvalidOperation:
        raise InvalidOrderData("Precio inválido")
    order.add_item(OrderItem(body.sku, body.quantity, Money(price)))
    return to_dto(order)


@app.post("/orders/{order_id}/confirm", response_model=OrderDTO, tags=["estados"])
def confirm_order(order_id: str):
    order = get_order_or_404(order_id)
    order.confirm()
    return to_dto(order)


@app.post("/orders/{order_id}/ship", response_model=OrderDTO, tags=["estados"])
def ship_order(order_id: str, body: ShipRequest | None = None):
    order = get_order_or_404(order_id)
    order.ship(body.tracking_number if body else "")
    return to_dto(order)


@app.post("/orders/{order_id}/cancel", response_model=OrderDTO, tags=["estados"])
def cancel_order(order_id: str, body: CancelRequest | None = None):
    order = get_order_or_404(order_id)
    order.cancel(body.reason if body else "")
    return to_dto(order)


@app.post("/orders/{order_id}/deliver", response_model=OrderDTO, tags=["estados"])
def deliver_order(order_id: str):
    order = get_order_or_404(order_id)
    order.deliver()
    return to_dto(order)


@app.post("/orders/{order_id}/return", response_model=OrderDTO, tags=["estados"])
def return_order(order_id: str):
    order = get_order_or_404(order_id)
    order.return_order()
    return to_dto(order)


# ---------------------------------------------------------------------------
# Utilidad de laboratorio
# ---------------------------------------------------------------------------
@app.post("/reset", tags=["utilidades"])
def reset_fixtures():
    """Vuelve a cargar los CSV (útil para repetir casos en Swagger)."""
    orders.clear()
    orders.update(load_fixture())
    return {"reloaded": len(orders)}
