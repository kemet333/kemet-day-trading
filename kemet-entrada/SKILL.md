---
name: kemet-entrada
description: >-
  El momento de la entrada. Vigila vela a vela la ruptura del balance inicial
  en futuros (ES, NQ, CL, GC): construye el IB con la primera hora de la sesión
  regular (o 15 o 30 minutos), espera a que cierre cada vela de 5 minutos de
  Yahoo (gratis, con retraso) y dice el disparo en la primera vela que CIERRA
  por encima del IB alto (largo) o por debajo del IB bajo (corto). Una mecha
  no dispara. Dice formando y cuánto falta, esperando y a cuántos puntos,
  disparado con la hora, la barra y el precio, o caducado, y escribe
  kemet/entrada.json para kemet-salida. Nunca envía una orden. Úsala cuando el
  usuario diga "avísame cuando entrar", "vigila el NQ", "ha roto el balance
  inicial", "ha salido del rango de la primera hora", "cuándo entro", "estado
  de la entrada", o después de kemet-niveles y kemet-plan, antes de
  kemet-salida.
argument-hint: "check [--mercado NQ] [--ib-minutos 60] [--escribir] | watch [--hasta 15:00] [--cada 30]"
---

# kemet-entrada

Convierte una regla en un momento: la vela que la confirma. Lee velas de 5 minutos, construye el balance
inicial de la primera hora y espera a que cada vela termine. Un precio que asoma por encima del IB en mitad de
una vela no es una entrada; una vela que cierra fuera, sí. Entonces dice la hora y el precio, los deja escritos
para kemet-salida y se para. No compra ni vende nada. La mayoría de los que hacen day trading pierde dinero, y
una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde vive este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/entrada.py" check                       # NQ o el mercado de kemet/config.json, IB de 60 minutos
python3 "${CLAUDE_SKILL_DIR}/entrada.py" check --escribir            # y guarda kemet/entrada.json
python3 "${CLAUDE_SKILL_DIR}/entrada.py" check --mercado ES --ib-minutos 30
python3 "${CLAUDE_SKILL_DIR}/entrada.py" watch --hasta 15:00         # una línea por vela cerrada, para en el disparo
python3 "${CLAUDE_SKILL_DIR}/entrada.py" watch --escribir            # en segundo plano, guarda el disparo cuando llegue
python3 "${CLAUDE_SKILL_DIR}/entrada.py" check --ahora "2026-11-11 10:45" --offline tests/fixtures/yahoo
```

Otros flags: `--json` (el documento completo), `--ahora "AAAA-MM-DD HH:MM"` (hora de Nueva York: fija el reloj y
permite repetir un día), `--offline RUTA` (un JSON de Yahoo guardado, `.json` o `.json.gz`, o la carpeta
`tests/fixtures/yahoo`), `--cada 30` (segundos entre lecturas cuando Yahoo va por detrás). `watch` con `--ahora`
o `--offline` corre con un reloj simulado y repite el día vela a vela sin esperar.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/config.json` | `mercado`, `sin_entradas_antes` (09:45) y `sin_entradas_despues` (15:00), hora de Nueva York. Opcional: sin él usa esos valores y lo dice |
| Yahoo Finance | las velas de 5 minutos del contrato (`range=5d`, o `60d` para repetir un día antiguo): gratis, sin clave, unos 10 minutos de retraso |
| `kemet/entrada.json` | con `check --escribir`, o cuando `watch --escribir` dispara: mercado, fecha, estado, motivo, lado, hora, barra, precio, IB (alto, bajo, ancho, minutos) |

## La regla

- **Balance inicial (IB).** El máximo y el mínimo de los primeros 60 minutos de la sesión regular: las doce
  velas de 09:30 a 10:30 NY en ES y NQ (09:00 a 10:00 en CL, 08:20 a 09:20 en GC). `--ib-minutos 15` o `30`
  acortan el IB; el resto de la regla no cambia.
- **El disparo** es la primera vela de 5 minutos cerrada después del IB que cierra por encima del IB alto
  (largo) o por debajo del IB bajo (corto). Una mecha fuera no dispara. Un cierre exacto en el nivel no dispara.
  El lado es el del cierre.
- **La hora** es la del cierre de esa vela (la vela de 10:40 cierra a las 10:45). **El precio** es su cierre,
  al tick. La **barra** cuenta desde la apertura, empezando en 1 (la de 10:40 es la barra 15 en índices).
- **Solo cuentan velas cerradas.** Una vela está cerrada cuando el reloj pasa su inicio más 5 minutos y Yahoo la
  ha enviado; si acaba de cerrar y aún no ha llegado, `watch` la espera un minuto como mucho y lo dice.
- **Una operación al día**: la primera. Los cierres fuera posteriores no cuentan para nada.
- **Horas.** Sin entradas antes de las 09:45 ni después de las 15:00 (config). En una sesión recortada el corte
  se adelanta al cierre menos cinco minutos.
- **Qué dice.** Cerrado (Globex cerrado: fin de semana, festivo) y cuándo abre. Formando antes de que cierre el
  IB, con el IB provisional y cuánto falta. Esperando, con el último cierre y a cuántos puntos está de cada
  lado. Disparado. Caducado.
- **Sin filtro.** La regla no decide qué días se opera. Lo que habría hecho en las sesiones anteriores lo enseñan
  kemet-maquina y su historia, y eso conviene verlo antes de arriesgar: en muchas sesiones es un coin flip.

## Pasos

1. Confirma el mercado con el usuario (o el de `kemet/config.json`) y que kemet-plan no tenga la franja en rojo.
2. Ejecuta `entrada.py check`. Dile el estado en una línea: formando y cuánto falta, esperando y a cuántos
   puntos, disparado a qué hora y precio, o caducado.
3. Para esperar el disparo, Claude puede dejar `entrada.py watch --escribir --hasta 15:00` en segundo plano, o
   `entrada.py check --escribir` en un `/loop` cada 5 minutos. `watch` se despierta justo después del cierre de
   cada vela, imprime una línea por vela y termina con código 0 en el disparo (escribe `kemet/entrada.json`) o
   con 1 al caducar. El ordenador tiene que seguir despierto: un portátil dormido lo pausa y, al despertar, se
   pone al día tarde.
4. Cuando dispare, di la hora y el precio, y que no se ha enviado nada. Si el disparo tiene más de una vela, dilo
   también: una entrada tardía es otra operación.
5. Pasa a kemet-salida para poner el stop y el objetivo ANTES de que el usuario toque su plataforma.
6. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en
   su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Con `--offline tests/fixtures/yahoo`. El IB de 09:30 a 10:30 va de 28.199 a 28.426 (227 puntos). A las 10:40 la
vela de 10:35 acaba de cerrar dentro del IB:

```
NQ, miércoles 11/11/2026, 16:40 Madrid / 10:40 NY · ruptura del IB de 60 minutos sobre velas de 5 minutos de Yahoo (gratis, unos 10 minutos de retraso)
IB 09:30 a 10:30: alto 28.426, bajo 28.199, 227 puntos (12 velas), medio 28.312,50.
ESPERANDO  último cierre 28.392 (vela de 10:35), a 34 puntos del IB alto 28.426 y a 193 del IB bajo 28.199.
Nada que hacer hasta que una vela cierre fuera del IB. No se ha enviado ninguna orden.
```

A las 10:45 la vela de 10:40 ha cerrado en 28.429,75, por encima del IB alto (`check --ahora "2026-11-11 10:45"`):

```
NQ, miércoles 11/11/2026, 16:45 Madrid / 10:45 NY · ruptura del IB de 60 minutos sobre velas de 5 minutos de Yahoo (gratis, unos 10 minutos de retraso)
IB 09:30 a 10:30: alto 28.426, bajo 28.199, 227 puntos (12 velas), medio 28.312,50.
DISPARADO largo a las 10:45 NY en 28.429,75: la vela de 10:40 (barra 15) cerró en 28.429,75, por encima del IB alto 28.426.
Este es el momento de la entrada, si la tomas. No se ha enviado ninguna orden.
Siguiente: stop y objetivo antes de pulsar nada, con kemet-salida (salida.py plan).
```

`watch --ahora "2026-11-11 10:20" --offline tests/fixtures/yahoo --escribir` repite el día vela a vela:

```
10:15  cierre 28.316,25  IB provisional 28.199 a 28.426 (10 de 12)
10:20  cierre 28.293,25  IB provisional 28.199 a 28.426 (11 de 12)
10:25  cierre 28.375,50  IB cerrado: 28.199 a 28.426, 227 puntos
10:30  cierre 28.366,25  a 59,75 del IB alto 28.426 y a 167,25 del IB bajo 28.199
10:35  cierre 28.392  a 34 del IB alto 28.426 y a 193 del IB bajo 28.199
10:40  cierre 28.429,75  cierre por encima del IB alto 28.426: DISPARADO largo a las 10:45 en 28.429,75 (barra 15)
Escrito kemet/entrada.json.
```

Visto desde las 16:30, el tool añade qué pasó después: máximo 28.697, mínimo 28.413,75 y último cierre
28.484,25; con el stop y el objetivo por defecto de kemet-salida (medio del IB y 1R), el objetivo 28.547 se
habría tocado a las 11:00 y el stop no. Un día no dice nada de la regla.

El miércoles 28 de octubre de 2026 ninguna vela cerró fuera del IB (29.767,25 a 29.952,75) antes de las 15:00;
`check --ahora "2026-10-28 15:05"` dice `CADUCADO` y `watch` termina con código 1.

## Reglas

- Vela a vela, sobre velas de 5 minutos de Yahoo: gratis, no oficiales, con retraso. Dilo cuando un minuto importe.
- Un disparo es información, no una orden ni una promesa. Nada aquí afirma que la regla gane.
- Los dos lados: largo por encima, corto por debajo. El lado es el del cierre.
- Un disparo por día. Los cierres fuera posteriores no lo reinician.
- Nunca se adelanta un disparo porque una vela "vaya a cerrar fuera".
- Igual en ES, NQ, CL y GC, cada uno con su sesión regular.

## Lo que nunca hace

Nunca envía una orden, nunca calcula contratos, nunca pone el stop (eso es kemet-salida), nunca mueve el IB a
posteriori y nunca cuenta una vela que no ha cerrado. Un `watch` en segundo plano no ejecuta nada más: no hay
nadie ahí para decir que sí.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes a ningún bróker ni a ninguna firma de fondeo. Las operaciones las pone el usuario en su plataforma, con su stop.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
