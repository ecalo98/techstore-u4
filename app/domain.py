"""Núcleo de dominio de TechStore (Unidad 4).

Este módulo NO conoce FastAPI, CSV ni bases de datos: se puede ejecutar y
probar solo en memoria. Aquí viven las invariantes, la máquina de estados
y los Domain Events.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

MAX_UNITS = 20
CURRENCY = "MXN"


# ---------------------------------------------------------------------------
# Excepciones de dominio (violaciones de reglas de negocio, no fallas técnicas)
# ---------------------------------------------------------------------------
class DomainException(Exception):
    """Raíz de todas las violaciones de reglas del negocio."""


class OrderException(DomainException):
    """Violaciones relacionadas con pedidos."""


class InvalidOrderData(OrderException):
    """Datos inválidos: monto negativo, cantidad <= 0, sin artículos, etc."""


class InvalidOrderTransition(OrderException):
    """Operación no permitida desde el estado actual del pedido."""


class OrderItemLimitExceeded(OrderException):
    """El pedido superaría el máximo de 20 unidades."""


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Money:
    """Importe inmutable. Compara por valor: Money(100) == Money(100)."""

    amount: Decimal
    currency: str = CURRENCY

    def __post_init__(self):
        # Rechazar float evita errores de representación binaria (0.1 + 0.2).
        if not isinstance(self.amount, Decimal):
            raise InvalidOrderData("El monto debe ser Decimal, no float/int")
        if not self.amount.is_finite() or self.amount < 0:
            raise InvalidOrderData("Monto inválido")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("Monedas distintas")
        return Money(self.amount + other.amount, self.currency)


@dataclass(frozen=True)
class Customer:
    id: str
    is_vip: bool = False
    active: bool = True


@dataclass(frozen=True)
class OrderItem:
    sku: str
    quantity: int
    unit_price: Money

    def __post_init__(self):
        if not self.sku.strip() or self.quantity <= 0:
            raise InvalidOrderData("Artículo inválido")

    @property
    def subtotal(self) -> Money:
        # Se calcula, nunca se captura a mano: evita discrepancias.
        return Money(self.unit_price.amount * self.quantity, self.unit_price.currency)


# ---------------------------------------------------------------------------
# Estados y eventos
# ---------------------------------------------------------------------------
class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


@dataclass(frozen=True)
class DomainEvent:
    """Hecho ya ocurrido. Inmutable y con marca de tiempo."""

    name: str
    order_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str = ""  # guía de envío o motivo de cancelación, cuando aplica


# ---------------------------------------------------------------------------
# Entidad / Aggregate Root
# ---------------------------------------------------------------------------
@dataclass
class Order:
    customer: Customer
    id: str
    has_promotion: bool = False
    status: OrderStatus = OrderStatus.DRAFT
    items: list[OrderItem] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)

    # -- consultas ----------------------------------------------------------
    @property
    def units(self) -> int:
        """SUMA de unidades (no el número de renglones)."""
        return sum(item.quantity for item in self.items)

    @property
    def total(self) -> Money:
        amount = sum((x.subtotal.amount for x in self.items), Decimal("0"))
        return Money(amount)

    # -- artículos ----------------------------------------------------------
    def add_item(self, item: OrderItem) -> None:
        if self.status != OrderStatus.DRAFT:
            raise InvalidOrderTransition("Solo DRAFT admite artículos")
        if self.units + item.quantity > MAX_UNITS:
            raise OrderItemLimitExceeded(f"Máximo {MAX_UNITS} unidades")
        if item.unit_price.currency != CURRENCY:
            raise InvalidOrderData("Solo MXN")
        self.items.append(item)

    # -- máquina de estados: validar -> cambiar estado -> registrar evento ---
    def _require_status(self, expected: OrderStatus, action: str) -> None:
        if self.status != expected:
            raise InvalidOrderTransition(
                f"No se puede {action} un pedido en estado {self.status.value}; "
                f"se requiere {expected.value}"
            )

    def _emit(self, name: str, detail: str = "") -> None:
        self.events.append(DomainEvent(name, self.id, detail=detail))

    def confirm(self) -> None:
        self._require_status(OrderStatus.DRAFT, "confirmar")
        if not self.items:
            raise InvalidOrderData("No se puede confirmar un pedido sin artículos")
        if not self.customer.active:
            raise InvalidOrderData("No se puede confirmar: el cliente está inactivo")
        self.status = OrderStatus.CONFIRMED
        self._emit("OrderConfirmed")

    def ship(self, tracking_number: str) -> None:
        self._require_status(OrderStatus.CONFIRMED, "enviar")
        if not tracking_number or not tracking_number.strip():
            raise InvalidOrderData("El envío requiere un número de guía")
        self.status = OrderStatus.SHIPPED
        self._emit("OrderShipped", tracking_number.strip())

    def cancel(self, reason: str) -> None:
        self._require_status(OrderStatus.CONFIRMED, "cancelar")
        if not reason or not reason.strip():
            raise InvalidOrderData("La cancelación requiere un motivo")
        self.status = OrderStatus.CANCELLED
        self._emit("OrderCancelled", reason.strip())

    def deliver(self) -> None:
        self._require_status(OrderStatus.SHIPPED, "entregar")
        self.status = OrderStatus.DELIVERED
        self._emit("OrderDelivered")

    def return_order(self) -> None:
        self._require_status(OrderStatus.SHIPPED, "devolver")
        self.status = OrderStatus.RETURNED
        self._emit("OrderReturned")
