"""Ejecuta los escenarios E01-E15 de datos/escenarios.csv y genera la bitácora.

Cada escenario usa un load_fixture() NUEVO, así ninguno contamina al siguiente.
Uso:  python run_scenarios.py            (imprime y escribe docs/bitacora_escenarios.*)
"""
import csv
import json
from decimal import Decimal
from pathlib import Path

from app.domain import DomainException, Money, OrderItem
from app.specifications import discount_amount, discount_rate, total_with_discount
from cargar_csv import load_fixture, rows

DOCS = Path(__file__).parent / "docs"


def evento_txt(order, n_antes):
    nuevos = [e.name for e in order.events[n_antes:]]
    return ", ".join(nuevos) if nuevos else "(sin evento)"


def ejecutar(caso):
    """Devuelve (estado_inicial, operación, resultado_real, eventos, cumple)."""
    order = load_fixture()[caso["pedido_id"]]
    accion, objetivo = caso["accion"], caso["objetivo"]
    estado_ini = order.status.value
    pre = f"{order.customer.id} {'VIP' if order.customer.is_vip else 'no VIP'}, " \
          f"{'activo' if order.customer.active else 'INACTIVO'}, {order.units} uds, " \
          f"total {order.total.amount} MXN, promo={'sí' if order.has_promotion else 'no'}"

    if accion == "evaluar_descuento":
        rate = discount_rate(order)
        res = (f"Descuento {int(rate * 100)}% = {discount_amount(order).amount} MXN; "
               f"total final {total_with_discount(order).amount} MXN")
        return pre, estado_ini, "evaluar descuento (Specifications)", res, \
            "(sin evento: solo evalúa)", f"{int(rate * 100)}%" == objetivo

    if accion == "agregar SKU003 x2":
        precios = {x["sku"]: Decimal(x["precio_mxn"]) for x in rows("productos.csv")}
        try:
            order.add_item(OrderItem("SKU003", 2, Money(precios["SKU003"])))
            res, ok = "ACEPTADO (inesperado)", False
        except DomainException as exc:
            res = f"RECHAZADO {type(exc).__name__}: {exc}. Quedan {order.units} uds"
            ok = objetivo == "rechazo"
        return pre, estado_ini, "add_item(SKU003 x2)", res, "(sin evento)", ok

    # Operaciones de estado: confirmar / enviar / cancelar / entregar / devolver
    pasos = {
        "confirmar": [("confirm", ())],
        "confirmar dos veces": [("confirm", ()), ("confirm", ())],
        "confirmar y enviar sin guia": [("confirm", ()), ("ship", (""))],
        "confirmar, enviar y cancelar": [("confirm", ()), ("ship", ("GUIA-E13",)),
                                          ("cancel", ("Cambio de opinión",))],
        "confirmar, enviar y devolver": [("confirm", ()), ("ship", ("GUIA-E14",)),
                                          ("return_order", ())],
        "confirmar, enviar y entregar": [("confirm", ()), ("ship", ("GUIA-E15",)),
                                          ("deliver", ())],
    }[accion]
    log, rechazo = [], None
    for metodo, args in pasos:
        if not isinstance(args, tuple):
            args = (args,)
        n = len(order.events)
        try:
            getattr(order, metodo)(*args)
            log.append(f"{metodo}() OK → {order.status.value} [{evento_txt(order, n)}]")
        except DomainException as exc:
            rechazo = f"{metodo}() RECHAZADO {type(exc).__name__}: {exc}"
            log.append(rechazo + f" [sin evento; sigue {order.status.value}]")
            break
    eventos = ", ".join(e.name for e in order.events) or "(ninguno)"
    ok = (rechazo is not None) if objetivo.startswith("rechazo") else (rechazo is None)
    res = " | ".join(log) + f" ⇒ estado final {order.status.value}"
    return pre, estado_ini, accion, res, eventos, ok


def main():
    filas, todos_ok = [], True
    for caso in rows("escenarios.csv"):
        pre, ini, op, res, ev, ok = ejecutar(caso)
        todos_ok &= ok
        filas.append({"caso": caso["caso_id"], "pedido": caso["pedido_id"],
                      "precondiciones": pre, "estado_inicial": ini, "operacion": op,
                      "objetivo": caso["objetivo"], "resultado_real": res,
                      "eventos": ev, "explicacion": caso["pista"],
                      "cumple_objetivo": ok})
    for f in filas:
        marca = "OK " if f["cumple_objetivo"] else "FALLA"
        print(f"[{marca}] {f['caso']} {f['pedido']} | {f['operacion']} | objetivo={f['objetivo']}")
        print(f"        pre: {f['precondiciones']}")
        print(f"        real: {f['resultado_real']}")
        print(f"        eventos: {f['eventos']}")
    print(f"\n{sum(f['cumple_objetivo'] for f in filas)}/{len(filas)} escenarios cumplen el objetivo")

    DOCS.mkdir(exist_ok=True)
    (DOCS / "bitacora_escenarios.json").write_text(
        json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")
    with (DOCS / "bitacora_escenarios.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader(); w.writerows(filas)
    return 0 if todos_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
