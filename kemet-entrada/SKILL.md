---
name: kemet-entrada
description: >-
  La regla de entrada, vela a vela. Vigila la ruptura del balance inicial
  en futuros (ES, NQ, CL, GC) y en acciones de EE. UU. (TSLA, AAPL, cualquier
  ticker): construye el IB con la primera hora de la sesión regular (los
  primeros 15 minutos en una acción; también 30), espera a que cierre cada vela de 5 minutos de
  Yahoo (gratis, con retraso) y dice el disparo en la primera vela que CIERRA
  por encima del IB alto (largo) o por debajo del IB bajo (corto). Una mecha
  no dispara. Dice formando y cuánto falta, esperando y a cuántos puntos,
  disparado con la hora, la barra y el precio, o caducado, y escribe
  kemet/entrada.json para kemet-salida. Nunca envía una orden. Úsala cuando el
  usuario diga "avísame cuando entrar", "vigila el NQ", "vigila TSLA", "ha
  roto el balance inicial", "ha salido del rango de la primera hora", "ha roto
  el rango de apertura", "cuándo entro", "estado de la entrada", "qué ha
  disparado de la watchlist", o después de kemet-niveles, kemet-plan o
  kemet-scanner, antes de kemet-salida.
argument-hint: "check [--mercado NQ|TSLA] [--ib-minutos 60|15] [--escribir] | watch [--hasta 15:00] [--cada 30] | watchlist"
---

# kemet-entrada

Convierte una regla en un momento: la vela que la confirma. Lee velas de 5 minutos, construye el balance
inicial de la primera hora (de los primeros 15 minutos en una acción) y espera a que cada vela termine. Un precio que asoma por encima del IB en mitad de
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
python3 "${CLAUDE_SKILL_DIR}/entrada.py" check --mercado TSLA         # una acción de EE. UU.: IB de 15 minutos, reloj de la NYSE
python3 "${CLAUDE_SKILL_DIR}/entrada.py" watchlist                    # una línea por símbolo de kemet/watchlist.json (kemet-scanner)
```

Otros flags: `--json` (el documento completo), `--ahora "AAAA-MM-DD HH:MM"` (hora de Nueva York: fija el reloj y
permite repetir un día), `--offline RUTA` (un JSON de Yahoo guardado, `.json` o `.json.gz`, o la carpeta
`tests/fixtures/yahoo`), `--cada 30` (segundos entre lecturas cuando Yahoo va por detrás). `watch` con `--ahora`
o `--offline` corre con un reloj simulado y repite el día vela a vela sin esperar. `--mercado` (o `--simbolo`)
acepta un futuro por su código o su micro (NQ, MNQ, ES, CL, GC) o un ticker de acciones de EE. UU. (TSLA, `BRK.B`).

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/config.json` | `mercado`, `sin_entradas_antes` (09:45) y `sin_entradas_despues` (15:00), hora de Nueva York. Opcional: sin él usa esos valores y lo dice |
| Yahoo Finance | las velas de 5 minutos del contrato (`range=5d`, o `60d` para repetir un día antiguo): gratis, sin clave, unos 10 minutos de retraso |
| `kemet/entrada.json` | con `check --escribir`, o cuando `watch --escribir` dispara: mercado, instrumento (futuro o accion), fecha, estado, motivo, lado, hora, barra, precio, IB (alto, bajo, ancho, minutos) |
| `kemet/watchlist.json` | la escribe kemet-scanner; `watchlist` recorre `aciertos[].simbolo` y da el estado de cada uno. Sin el archivo, lo dice y termina con código 1 |

## La regla

- **Balance inicial (IB).** El máximo y el mínimo de los primeros 60 minutos de la sesión regular: las doce
  velas de 09:30 a 10:30 NY en ES y NQ (09:00 a 10:00 en CL, 08:20 a 09:20 en GC). `--ib-minutos 15` o `30`
  acortan el IB; el resto de la regla no cambia.
- **Acciones de EE. UU.** `--mercado TSLA` (cualquier ticker). El IB por defecto son los primeros 15 minutos, 09:30
  a 09:45, tres velas, como la ruptura del rango de apertura; `--ib-minutos 30` o `60` lo alargan. El día es la fecha
  de Nueva York, sin sesión nocturna. La sesión va de 09:30 a 16:00 (13:00 en los días recortados de la NYSE, y el
  corte de entradas se adelanta a las 12:55). El reloj es el de la NYSE: fin de semana y festivos. Las distancias van
  en dólares por acción y los precios de Yahoo se redondean al céntimo. Lo demás no cambia: una operación al día, la
  primera, el lado del cierre, sin entradas antes de las 09:45 ni después de las 15:00.
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
- **Qué dice.** Cerrado (Globex o la NYSE cerrados: fin de semana, festivo) y cuándo abre. Formando antes de que cierre el
  IB, con el IB provisional y cuánto falta. Esperando, con el último cierre y a cuántos puntos está de cada
  lado. Disparado. Caducado.
- **Sin filtro.** La regla no decide qué días se opera. Lo que habría hecho en las sesiones anteriores lo enseñan
  kemet-maquina y su historia, y eso conviene verlo antes de arriesgar: en muchas sesiones es un coin flip.

## Pasos

1. Confirma el mercado con el usuario (o el de `kemet/config.json`) y que kemet-plan no tenga la franja en rojo.
2. Ejecuta `entrada.py check`. Dile el estado en una línea: formando y cuánto falta, esperando y a cuántos
   puntos, disparado a qué hora y precio, o caducado. Si kemet-scanner ha dejado una `kemet/watchlist.json`,
   `entrada.py watchlist` da una línea por símbolo; el que interese se sigue con `check --mercado SIMBOLO --escribir`.
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
La regla escrita se acaba de cumplir; es una regla, no una recomendación. No se ha enviado ninguna orden.
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

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026

Con `--mercado TSLA --offline tests/fixtures/yahoo` (fixture real `TSLA-60d-5m.json.gz`, 60 sesiones). En una acción
el IB es el de los primeros 15 minutos, 09:30 a 09:45, tres velas: 386,35 a 392,67 (6,32 $). A las 10:10 la vela de
10:05 acaba de cerrar en 392,12, dentro por 0,55 $ (`check --mercado TSLA --ahora "2026-11-11 10:10"`):

```
TSLA, miércoles 11/11/2026, 16:10 Madrid / 10:10 NY · ruptura del IB de 15 minutos sobre velas de 5 minutos de Yahoo (gratis, puede ir con retraso)
IB 09:30 a 09:45: alto 392,67, bajo 386,35, 6,32 $ (3 velas), medio 389,51.
ESPERANDO  último cierre 392,12 (vela de 10:05), a 0,55 $ del IB alto 392,67 y a 5,77 del IB bajo 386,35.
Nada que hacer hasta que una vela cierre fuera del IB. No se ha enviado ninguna orden.
Sin kemet/config.json: valores por defecto (entradas de 09:45 a 15:00 NY).
```

A las 10:15 la vela de 10:10 ha cerrado en 393,08, por encima del IB alto:

```
TSLA, miércoles 11/11/2026, 16:15 Madrid / 10:15 NY · ruptura del IB de 15 minutos sobre velas de 5 minutos de Yahoo (gratis, puede ir con retraso)
IB 09:30 a 09:45: alto 392,67, bajo 386,35, 6,32 $ (3 velas), medio 389,51.
DISPARADO largo a las 10:15 NY en 393,08: la vela de 10:10 (barra 9) cerró en 393,08, por encima del IB alto 392,67.
La regla escrita se acaba de cumplir; es una regla, no una recomendación. No se ha enviado ninguna orden.
Siguiente: stop y objetivo antes de pulsar nada, con kemet-salida (salida.py plan).
```

`watch --mercado TSLA --ahora "2026-11-11 09:40" --offline tests/fixtures/yahoo --escribir` repite la mañana:

```
09:35  cierre 390,48  IB provisional 386,35 a 392,67 (2 de 3)
09:40  cierre 388,07  IB cerrado: 386,35 a 392,67, 6,32 $
09:45  cierre 387,46  a 5,21 del IB alto 392,67 y a 1,11 del IB bajo 386,35
09:50  cierre 387,24  a 5,43 del IB alto 392,67 y a 0,89 del IB bajo 386,35
09:55  cierre 389,81  a 2,86 del IB alto 392,67 y a 3,46 del IB bajo 386,35
10:00  cierre 389,55  a 3,12 del IB alto 392,67 y a 3,20 del IB bajo 386,35
10:05  cierre 392,12  a 0,55 del IB alto 392,67 y a 5,77 del IB bajo 386,35
10:10  cierre 393,08  cierre por encima del IB alto 392,67: DISPARADO largo a las 10:15 en 393,08 (barra 9)
Escrito kemet/entrada.json.
```

Visto desde las 16:30, el tool añade qué pasó: máximo 395,43, mínimo 388,75 y último cierre 390,80; con el stop y el
objetivo por defecto de kemet-salida (medio del IB, 389,51, y 1R, 396,65), el objetivo no llegó (el máximo del día se
quedó a 1,22 $ a las 11:00) y el stop se habría tocado a las 15:55, en la última vela antes de estar plano. El mismo
día la regla salió bien en NQ y mal en TSLA: un día no dice nada de la regla.

Con una watchlist de kemet-scanner (`watchlist --offline tests/fixtures/yahoo --ahora "2026-11-11 10:15"`):

```
Watchlist kemet/watchlist.json (modo orb, 3 símbolos), 16:15 Madrid / 10:15 NY · ruptura del balance inicial, 60 min en futuros y 15 en acciones salvo --ib-minutos
TSLA   DISPARADO largo a las 10:15 NY en 393,08 (vela de 10:10, barra 9); IB de 15 min 386,35 a 392,67; stop por defecto 389,51, objetivo 1R 396,65.
AAPL   DISPARADO largo a las 09:50 NY en 353,68 (vela de 09:45, barra 4); IB de 15 min 349,33 a 353,43; stop por defecto 351,38, objetivo 1R 355,98.
NQ     FORMANDO  IB en formación, 9 de 12 velas cerradas; se cierra a las 10:30 (faltan 15 minutos).
Sin kemet/config.json: valores por defecto (entradas de 09:45 a 15:00 NY).
2 disparos. No se ha enviado ninguna orden. Para seguir uno: entrada.py check --mercado SIMBOLO --escribir y después kemet-salida.
```

Sin `kemet/watchlist.json` dice que no hay y termina con código 1.

## Reglas

- Vela a vela, sobre velas de 5 minutos de Yahoo: gratis, no oficiales, con retraso. Dilo cuando un minuto importe.
- Un disparo es información, no una orden ni una promesa. Nada aquí afirma que la regla gane.
- Los dos lados: largo por encima, corto por debajo. El lado es el del cierre.
- Un disparo por día. Los cierres fuera posteriores no lo reinician.
- Nunca se adelanta un disparo porque una vela "vaya a cerrar fuera".
- Igual en ES, NQ, CL y GC, cada uno con su sesión regular, y en una acción de EE. UU. con los primeros 15 minutos
  y el reloj de la NYSE.

## Lo que nunca hace

Nunca envía una orden, nunca calcula contratos, nunca pone el stop (eso es kemet-salida), nunca mueve el IB a
posteriori y nunca cuenta una vela que no ha cerrado. Un `watch` en segundo plano no ejecuta nada más: no hay
nadie ahí para decir que sí.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
