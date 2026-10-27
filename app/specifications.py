"""Specification Pattern para las reglas de descuento de TechStore.

Una Specification solo EVALÚA (verdadero/falso); nunca modifica el pedido.
Operadores:  &  = AND   |  = OR   ~  = NOT
"""
from decimal import ROUND_HALF_UP, Decimal

from app.domain import Money, Order


class Specification:
    def is_satisfied_by(self, order: Order) -> bool:
        raise NotImplementedError

    def __and__(self, other: "Specification") -> "Specification":
        return AndSpec(self, other)

    def __or__(self, other: "Specification") -> "Specification":
        return OrSpec(self, other)

    def __invert__(self) -> "Specification":
        return NotSpec(self)


# -- combinadores -----------------------------------------------------------
class AndSpec(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left, self.right = left, right

    def is_satisfied_by(self, order: Order) -> bool:
        return self.left.is_satisfied_by(order) and self.right.is_satisfied_by(order)


class OrSpec(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left, self.right = left, right

    def is_satisfied_by(self, order: Order) -> bool:
        return self.left.is_satisfied_by(order) or self.right.is_satisfied_by(order)


class NotSpec(Specification):
    def __init__(self, inner: Specification):
        self.inner = inner

    def is_satisfied_by(self, order: Order) -> bool:
        return not self.inner.is_satisfied_by(order)


# -- reglas simples ---------------------------------------------------------
class MinimumAmountSpec(Specification):
    """Total ESTRICTAMENTE mayor al umbral (> y no >=)."""

    def __init__(self, threshold: Decimal):
        self.threshold = threshold

    def is_satisfied_by(self, order: Order) -> bool:
        return order.total.amount > self.threshold


class VIPCustomerSpec(Specification):
    def is_satisfied_by(self, order: Order) -> bool:
        return order.customer.is_vip


class MinimumUnitsSpec(Specification):
    """Al menos N unidades (>=), contando unidades y no renglones."""

    def __init__(self, minimum: int):
        self.minimum = minimum

    def is_satisfied_by(self, order: Order) -> bool:
        return order.units >= self.minimum


class ActivePromotionSpec(Specification):
    def is_satisfied_by(self, order: Order) -> bool:
        return order.has_promotion


class ActiveCustomerSpec(Specification):
    """Quinta regla: el cliente puede operar (activo)."""

    def is_satisfied_by(self, order: Order) -> bool:
        return order.customer.active


# -- reglas de negocio compuestas -------------------------------------------
# 10 %: VIP + total > 500 + >= 4 unidades + SIN promoción
ten_percent = (
    MinimumAmountSpec(Decimal("500"))
    & VIPCustomerSpec()
    & MinimumUnitsSpec(4)
    & ~ActivePromotionSpec()
)

# 5 %: total > 5000 + SIN promoción
five_percent = MinimumAmountSpec(Decimal("5000")) & ~ActivePromotionSpec()

# Elegible para algún descuento (OR de ambas reglas)
any_discount = ten_percent | five_percent


def discount_rate(order: Order) -> Decimal:
    """Porcentaje aplicable. Si se cumplen ambas reglas, gana el 10 %."""
    if ten_percent.is_satisfied_by(order):
        return Decimal("0.10")
    if five_percent.is_satisfied_by(order):
        return Decimal("0.05")
    return Decimal("0")


def discount_amount(order: Order) -> Money:
    """Monto del descuento (2 decimales). No modifica el pedido."""
    raw = order.total.amount * discount_rate(order)
    return Money(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def total_with_discount(order: Order) -> Money:
    return Money(order.total.amount - discount_amount(order).amount)
