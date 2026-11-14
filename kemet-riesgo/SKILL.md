---
name: kemet-riesgo
description: >-
  La puerta entre una orden propuesta y tu plataforma. Comprueba cada orden contra tu configuración, la agenda
  de datos del día, lo que ya has operado hoy, y da PASS o BLOCK con el motivo: stop obligatorio y del lado
  correcto, pérdida al stop dentro del riesgo por operación, suma del día dentro de la pérdida máxima, no más
  de tres operaciones, contratos dentro del tope de la cuenta, fuera de las ventanas de datos y de la
  apertura, antes de la hora de estar plano y de la hora límite de la firma, Globex abierto. En acciones con
  la cuenta propia, además: reloj de la NYSE, tamaño, posición, efectivo con colchón, cortos y opciones sin
  permiso. Una orden de cierre nunca se bloquea por los límites del día. Lleva la cuenta del día. Úsala cuando
  el usuario diga «comprueba mi orden», «puedo entrar», «puedo comprar TSLA», «me queda margen», «cuánto llevo
  arriesgado hoy», «apunta que he cerrado con -120», «cómo va el día», o siempre después de kemet-tamano y
  antes de poner nada.
argument-hint: "[check | registrar --abrir | registrar --resultado -120 | hoy]"
---

# kemet-riesgo

Ninguna orden de este pack llega a tu plataforma sin pasar por aquí, y la que no pasa no se pone. Un BLOCK
es final para esa orden: no se negocia, se cambia la orden o se espera. La mayoría de los que hacen day
trading pierde dinero, y una herramienta no cambia eso: estos límites hacen pequeña cada pérdida y cada
día malo, no hacen ganar una operación.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/riesgo.py" check                               # kemet/orden.json; escribe kemet/estado/riesgo.json
python3 "${CLAUDE_SKILL_DIR}/riesgo.py" check --sin-escribir --json         # mirar sin apuntar los veredictos
python3 "${CLAUDE_SKILL_DIR}/riesgo.py" check --ahora "2026-11-11 10:45"    # fija el reloj (hora de Nueva York)
python3 "${CLAUDE_SKILL_DIR}/riesgo.py" registrar --abrir                   # la orden que pasó ya está puesta en tu plataforma
python3 "${CLAUDE_SKILL_DIR}/riesgo.py" registrar --resultado -120 --hora 11:05   # cierra la última abierta con su resultado
python3 "${CLAUDE_SKILL_DIR}/riesgo.py" hoy                                 # el día: operaciones, riesgo abierto, lo que queda
```

Código de salida de `check`: 0 si todo PASS, 1 si algún BLOCK, 2 si hay un error. `hoy` devuelve 1 cuando
toca parar (día agotado o tres operaciones).

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/orden.json` | las órdenes propuestas (kemet-tamano): en contratos (futuros) o en el formato de `place_stock_order` de Alpaca (acciones, `"instrumento": "accion"`); una con `"cierre": true` solo saca de una posición |
| `kemet/config.json` | los límites de tu cuenta y los tuyos (kemet-tamano `config`, de firma o `--propia`); sin él, valores por defecto y lo dice |
| `kemet/agenda.json` | los datos del día (kemet-plan `agenda`): ventanas de ±10 minutos, ±20 si `fuerte` |
| `kemet/estado/dia.json` | lo que has puesto y cerrado hoy; lo escribe `registrar` |
| `kemet/estado/cuenta.json` | lo que te queda de drawdown (kemet-tamano `cuenta`): si un cuarto es menor, `perdida_max_dia` baja a eso; si cambia, el PASS deja de valer para kemet-broker |
| `kemet/estado/broker.json` | lo que kemet-broker colocó hoy en papel: cuenta como operación, en el día (su pérdida al stop) y para los duplicados |
| `kemet/portfolio.json` | (acciones) efectivo y posiciones, de kemet-broker: una venta de lo que tienes es un cierre; sin él, el presupuesto del config |
| `kemet/precios.json` | (acciones) el último precio de kemet-alertas: con menos de 15 minutos y por encima de la entrada del plan, el riesgo se mide desde él |
| `kemet/estado/riesgo.json` | los veredictos del último `check`, con la huella de cada orden |

## Entradas y cierres

Una **entrada** abre o añade posición. Un **cierre** (`"cierre": true`, o en acciones una venta de lo que
tienes en `kemet/portfolio.json`) solo saca de una. Salir siempre tiene que ser posible: a un cierre se le
mira el formato y, en acciones, que la NYSE esté abierta; todo lo demás se convierte en aviso, nunca en BLOCK.
Tres límites para que «cierre» no sirva para abrir: en futuros, un cierre no puede tener más contratos que el
tope de la cuenta; en acciones, una compra marcada como cierre solo lo es si recompra un corto de
`kemet/portfolio.json`; y una venta marcada como cierre de acciones que el pack no tiene apuntadas pasa con el
aviso de comprobar antes la posición con `get_open_position` (si no las tiene, esa venta abre un corto).

## Las comprobaciones

Las órdenes se miran en el orden del archivo, como si cada PASS ya estuviera puesta, así que dos órdenes
que caben por separado y no juntas se detectan.

| comprobación | bloquea cuando |
| --- | --- |
| formato | el símbolo no es un micro ni un mini conocido (MNQ, NQ, MES, ES, MCL, MGC…), el lado no es compra o venta, los contratos no son un entero mayor que 0, el precio no es un número |
| stop | (entradas) sin stop; stop del lado equivocado de la entrada; objetivo detrás de la entrada |
| pérdida | (entradas) contratos × riesgo en puntos × valor del punto, por encima del riesgo por operación (pérdida máxima del día entre `fallos_y_paras`) |
| día | (entradas) riesgo de las abiertas + pérdidas realizadas + esta, por encima de `perdida_max_dia` |
| operaciones | (entradas) ya hay `fallos_y_paras` operaciones hoy: la tercera entra, la cuarta no |
| contratos | (entradas) más micros que `max_micro` (o más minis que `max_mini`) |
| ventana | (entradas) dentro de la ventana de un dato de la agenda, o en los primeros 15 minutos de la sesión regular (09:30–09:45 NY en ES y NQ) |
| horario | (entradas) antes de `sin_entradas_antes`, después de `sin_entradas_despues` (15:00 por defecto), desde `plano_a`, desde la hora límite de la firma (Chicago se convierte a NY) |
| globex | (todas) pausa diaria 17:00–18:00 NY, fin de semana, festivo de CME |
| duplicado | (entradas) la misma orden (misma huella) ya apuntada hoy en `dia.json`, o repetida en el archivo |

Avisos que no bloquean, pero se dicen: la regla de consistencia de la firma (aquí no se puede medir), una
cuenta real (`"papel": false`), la hora límite en Chicago con su equivalente en NY, sin config, sin agenda.

En una acción (cuenta propia; la orden lleva `symbol`, `side` buy|sell, `qty`, `type`, `time_in_force`,
`order_class` bracket, `take_profit_limit_price`, `stop_loss_stop_price`, `plan`, `instrumento`), además:

| comprobación | bloquea cuando |
| --- | --- |
| formato | el símbolo no es un ticker de EE. UU., `side` no es buy o sell, `qty` no es un entero (acciones enteras), `type` no es market o limit, una limit sin `limit_price`, `time_in_force` que no sea day o gtc, un bracket sin sus dos patas; cantidades y precios que no vayan como texto son solo un aviso |
| mercado | (todas) la NYSE cerrada: fin de semana, festivo, antes de las 09:30 o después del cierre (13:00 en días recortados) |
| cuenta | (entradas) la config es de una cuenta de firma: para acciones hace falta `tamano.py config --propia` |
| opciones | un símbolo OCC con `permitir_opciones: false` |
| bloqueado | (entradas) el ticker está en `bloqueados` |
| tamaño | (entradas) acciones × entrada por debajo de `min_orden_usd` o por encima de `max_orden_usd` |
| posición | (entradas) lo que ya tienes del símbolo más esta compra, por encima de `max_posicion_pct` del presupuesto |
| efectivo | (entradas) la compra necesita más efectivo del que hay (margen) o deja el efectivo por debajo del colchón `efectivo_pct` |
| corto | (entradas) vender más de lo que tienes con `permitir_cortos: false` |
| stop, pérdida, día, operaciones, ventana, horario, duplicado | como arriba, con la pérdida al stop = acciones × (entrada menos stop) y sin hora límite de firma. La entrada que mide es el `limit_price` en una limit; a mercado, la del plan o el último precio de `kemet/precios.json` si es fresco y peor |

Sin `kemet/portfolio.json` el efectivo de partida es el presupuesto del config; sin presupuesto no se miden
efectivo ni posición y lo avisa. Las órdenes se simulan en orden: una compra que pasa resta su efectivo a la
siguiente.

Cómo cuentan los números:

- La **pérdida al stop** es contratos × |entrada menos stop| × valor del punto del micro (2 $ en MNQ, 5 $ en
  MES, 100 $ en MCL, 10 $ en MGC); del mini si el símbolo es el mini.
- El **día** suma el riesgo de las operaciones abiertas (su pérdida al stop) y la pérdida realizada neta de
  las cerradas, según `dia.json`. Por eso importa apuntar: `registrar --abrir` al poner la orden,
  `registrar --resultado` al cerrarla.
- La **huella** es un sha1 de los campos de la orden (símbolo, lado, contratos, tipo, precio, stop,
  objetivo, cierre; en una acción, los campos de `place_stock_order` más `cierre`), la misma que calcula
  kemet-broker: un ticket solo sale LISTO si esa huella exacta tiene un PASS de hoy. Una orden editada tiene
  otra huella y necesita otro `check`.
- **Lo colocado hoy** según `kemet/estado/broker.json` (estado colocada o llenada) cuenta como operación del
  día y, si el registro trae su pérdida al stop, en la suma del día; una compra del mismo símbolo ya
  colocada hoy es un duplicado. Lo que ya está apuntado en `dia.json` con la misma huella no se cuenta dos veces.
- El **reloj** es el de Nueva York calculado en la herramienta, con el horario de verano, nunca el de tu
  ordenador. `--ahora` lo fija para repetir un día.

## Pasos

1. Después de `tamano.py orden --escribir`, ejecuta `check`. Si el usuario ha dado los datos del día,
   antes `plan.py agenda` para que las ventanas cuenten.
2. Di el resultado orden por orden, en llano: pérdida al stop, cuánto del día usa, y para un BLOCK el motivo
   y lo que lo arregla (menos contratos, un stop más corto desde kemet-salida, esperar a que pase la
   ventana, o dejarla pasar). Nunca cambies un límite para que pase.
3. Si pasa y el usuario la pone en su plataforma, `registrar --abrir`. Cuando la cierre (stop, objetivo o a
   mano), `registrar --resultado USD --hora HH:MM`. Sin esto la siguiente comprobación no sabe lo que ya
   has arriesgado.
4. Si la orden cambia en algo, `check` otra vez: la huella cambia y el veredicto anterior no vale. Un
   veredicto de ayer tampoco vale hoy.
5. `hoy` antes de cada nueva idea: si dice que toca parar, se cierra la plataforma. Los sistemas que Kemet
   Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en su propio banco;
   no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

La orden de kemet-tamano para la ruptura del balance inicial de ese día (IB 28.199 a 28.426; la vela de
las 10:40 cerró en 28.429,75, por encima) en una Apex 150K EOD financiada (`eod-pa-150`: 1.000 $ al día,
333,33 $ por operación): compra 1 MNQ a 28.429,75, stop en el punto medio del IB 28.312,50, objetivo 1R
28.547, 234,50 $ al stop. Comprobada a las 10:45, cuando cerró esa vela:

```
$ python3 riesgo.py check --ahora "2026-11-11 10:45"
RIESGO · Apex Trader Funding · 150K EOD fondeada (PA) · 2026-11-11 · 16:45 Madrid / 10:45 NY
AVISO: consistencia de la firma: mejor día ≤ 50% del beneficio para cobrar. No se puede medir aquí: mírala en tu panel antes de pedir un cobro
AVISO: sin kemet/agenda.json: no conozco los datos de hoy, solo la ventana de la apertura

PASS  #1 compra 1 MNQ, entrada
          entrada 28.429,75, stop 28.312,50, objetivo 28.547: riesgo 117,25 pts = 234,50 $ por MNQ
          pérdida al stop 234,50 $ (riesgo por operación 333,33 $)
          hoy antes de esta: 0 de 3 operaciones, 0 $ abierto, 0 $ perdido, 0 $ de 1.000 $ del día

1 PASS, 0 BLOCK a las 10:45 NY (simulación).
Todo PASS. Un PASS es una comprobación de reglas, no una recomendación: la pones tú, con su stop, y la apuntas con `registrar --abrir`.
```

El usuario la pone y la apunta; el objetivo se tocó a las 10:55 (máximo de esa vela 28.550,25):

```
$ python3 riesgo.py registrar --abrir --ahora "2026-11-11 10:46"
Abierta a las 10:46 NY: compra 1 MNQ a 28.429,75, stop 28.312,50, riesgo 234,50 $ (huella f2328b1ec6e1)
Apuntado en kemet/estado/dia.json · riesgo abierto 234,50 $ · pérdida realizada 0,00 $
$ python3 riesgo.py registrar --resultado 234.5 --hora 11:00
Cerrada a las 11:00 NY: compra 1 MNQ de las 10:46, resultado 234,50 $
HOY · Apex Trader Funding · 150K EOD fondeada (PA) · 2026-11-11
  1. 10:46 compra 1 MNQ a 28.429,75, stop 28.312,50, riesgo 234,50 $ · cerrada 11:00, 234,50 $
Operaciones: 1 de 3 · pérdidas: 0 · riesgo abierto 0,00 $ · pérdida realizada 0,00 $ (neto 234,50 $)
Queda del día: 1.000,00 $ de 1.000 $ · 2 operaciones más como mucho
```

La misma orden con 2 MNQ y a las 09:40 se bloquea tres veces:

```
$ python3 riesgo.py check --ahora "2026-11-11 09:40" --sin-escribir
BLOCK #1 compra 2 MNQ, entrada
          entrada 28.429,75, stop 28.312,50, objetivo 28.547: riesgo 117,25 pts = 234,50 $ por MNQ
          pérdida al stop 469,00 $ (riesgo por operación 333,33 $)
          hoy antes de esta: 1 de 3 operaciones, 0 $ abierto, 0 $ perdido, 0 $ de 1.000 $ del día
        - pérdida: 2 × 117,25 pts × 2 $/pt = 469,00 $ al stop, más que tu riesgo por operación de 333,33 $
        - ventana: apertura 09:30–09:45 NY, los quince minutos más bruscos del día (son las 09:40)
        - horario: sin entradas antes de las 09:45 NY (son las 09:40)

0 PASS, 1 BLOCK a las 09:40 NY (simulación).
Una orden con BLOCK no se pone. Cambia la orden o espera; las reglas no se tocan a media sesión.
```

Con una agenda que tenga «14:00 Subasta del Tesoro», la misma orden a las 13:52 se bloquea por la ventana
13:50–14:10; con tres operaciones ya apuntadas, por «operaciones: hoy ya hay 3 y tu regla son 3 al día»; a
las 10:50 con la misma orden ya abierta, por duplicado; a las 15:10, por «sin entradas después de las 15:00».
A las 15:58, con el día agotado, una venta de 1 MNQ con `"cierre": true` pasa igual: es un cierre.

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026, cuenta propia

Cuenta propia de 5.000 $, 50 $ por operación y 150 $ al día (`tamano.py config --propia`). La orden de
kemet-tamano para la ruptura del rango de 15 minutos de TSLA ese día (rango 386,35 a 392,67; la vela de las
10:10 cerró a las 10:15 en 393,08; stop en el punto medio 389,51; objetivo 1R 396,65): compra 9 acciones a
mercado, bracket, 32,13 $ al stop. Comprobada a las 10:15:

```
$ python3 riesgo.py check --ahora "2026-11-11 10:15"
RIESGO · Cuenta propia · 5.000 $ · 2026-11-11 · 16:15 Madrid / 10:15 NY
AVISO: sin kemet/agenda.json: no conozco los datos de hoy, solo la ventana de la apertura

PASS  #1 compra 9 TSLA, entrada
          entrada 393,08 $ (entrada del plan), stop 389,51 $, objetivo 396,65 $: riesgo 3,57 $ por acción
          pérdida al stop 32,13 $ (riesgo por operación 50,00 $) · 9 acciones = 3.537,72 $
          hoy antes de esta: 0 de 3 operaciones, 0 $ abierto, 0 $ perdido, 0 $ de 150 $ del día

1 PASS, 0 BLOCK a las 10:15 NY (simulación).
Todo PASS. Un PASS es una comprobación de reglas, no una recomendación: la pones tú, con su stop, y la apuntas con `registrar --abrir`.
```

Ese día TSLA no llegó al objetivo (máximo 395,43) y el stop saltó a las 15:50:

```
$ python3 riesgo.py registrar --abrir --ahora "2026-11-11 10:16"
Abierta a las 10:16 NY: compra 9 TSLA a 393,08, stop 389,51, riesgo 32,13 $ (huella 4cd5e67d8906)
$ python3 riesgo.py registrar --resultado -32.13 --hora 15:50
Cerrada a las 15:50 NY: compra 9 TSLA de las 10:16, resultado -32,13 $
HOY · Cuenta propia · 5.000 $ · 2026-11-11
  1. 10:16 compra 9 TSLA a 393,08, stop 389,51, riesgo 32,13 $ · cerrada 15:50, -32,13 $
Operaciones: 1 de 3 · pérdidas: 1 · riesgo abierto 0,00 $ · pérdida realizada 32,13 $ (neto -32,13 $)
Queda del día: 117,87 $ de 150 $ · 2 operaciones más como mucho
```

La misma orden con 20 acciones se bloquea cuatro veces:

```
$ python3 riesgo.py check --ahora "2026-11-11 10:15" --sin-escribir
BLOCK #1 compra 20 TSLA, entrada
          entrada 393,08 $ (entrada del plan), stop 389,51 $, objetivo 396,65 $: riesgo 3,57 $ por acción
          pérdida al stop 71,40 $ (riesgo por operación 50,00 $) · 20 acciones = 7.861,60 $
          hoy antes de esta: 0 de 3 operaciones, 0 $ abierto, 0 $ perdido, 0 $ de 150 $ del día
        - tamaño: 7.861,60 $, más que tu orden máxima de 4.000 $
        - efectivo: hacen falta 7.861,60 $ y hay 5.000,00 $ de efectivo; eso sería margen (dinero prestado) y no lo permites
        - posición: TSLA sería 7.861,60 $, el 157,2 % de 5.000 $, más que tu tope del 75 % (3.750 $)
        - pérdida: 20 × 3,57 $ por acción = 71,40 $ al stop, más que tu riesgo por operación de 50,00 $

0 PASS, 1 BLOCK a las 10:15 NY (simulación).
Una orden con BLOCK no se pone. Cambia la orden o espera; las reglas no se tocan a media sesión.
```

Con 10 acciones solo salta la posición (3.930,80 $, el 78,6 %). Con `kemet/portfolio.json` a 2.000 $ de
efectivo, la de 9 se bloquea por margen; a 3.900 $, por dejar 362,28 $ bajo el colchón de 500 $. Una venta
de 9 TSLA con `permitir_cortos: false` y nada en la cartera es un corto y se bloquea; con las 9 en
`portfolio.json` es un cierre y pasa aunque el día esté agotado. El jueves 26 de noviembre, Thanksgiving,
cualquier orden de acciones se bloquea por «mercado: NYSE cerrado».

## Reglas

- Un PASS solo dice que la orden cabe en las reglas. No es un sí ni una recomendación.
- Toda cifra sale de la orden, del config, de la agenda o del estado del día. Nada se supone.
- Un stop es una orden, no una promesa: en un mercado rápido se llena peor. La pérdida al stop es la mínima que aceptas, no la máxima posible.
- La regla de consistencia de la firma no se puede medir aquí: se avisa y se mira en el panel.

## Lo que nunca hace

No pone órdenes, no edita una orden para que pase, no afloja un límite, no bloquea un cierre por los
límites del día y no trata un PASS como el sí del usuario.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
