---
name: kemet-riesgo
description: >-
  La puerta entre una orden propuesta y tu plataforma. Comprueba cada orden de kemet/orden.json contra
  kemet/config.json, la agenda de datos del día, lo que ya has operado hoy y el reloj de Globex, y da
  PASS o BLOCK con el motivo: stop obligatorio y del lado correcto, pérdida al stop dentro del riesgo por
  operación, suma del día dentro de la pérdida máxima del día, no más de tres operaciones (tres fallos y
  paras), contratos dentro del tope de la cuenta, fuera de las ventanas de datos y de la apertura
  09:30–09:45, dentro del horario de entradas, antes de la hora de estar plano y de la hora límite de la
  firma, Globex abierto, sin duplicados. Una orden de cierre nunca se bloquea por los límites del día. Lleva
  el día en kemet/estado/dia.json: qué pusiste, qué cerraste, cuánto queda. Úsala cuando el usuario diga
  «comprueba mi orden», «puedo entrar», «cuánto llevo arriesgado hoy», «me queda margen», «apunta que he
  cerrado con -120», «cómo va el día», o siempre después de kemet-tamano y antes de poner nada.
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
| `kemet/orden.json` | las órdenes propuestas (kemet-tamano); una con `"cierre": true` solo saca de una posición |
| `kemet/config.json` | los límites de tu cuenta y los tuyos (kemet-tamano `config`); sin él, valores por defecto y lo dice |
| `kemet/agenda.json` | los datos del día (kemet-plan `agenda`): ventanas de ±10 minutos, ±20 si `fuerte` |
| `kemet/estado/dia.json` | lo que has puesto y cerrado hoy; lo escribe `registrar` |
| `kemet/estado/riesgo.json` | los veredictos del último `check`, con la huella de cada orden |

## Entradas y cierres

Una **entrada** abre o añade posición. Un **cierre** (`"cierre": true`) solo saca de una. Salir siempre
tiene que ser posible: a un cierre se le mira el formato y que Globex esté abierto; todo lo demás se
convierte en aviso, nunca en BLOCK.

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

Cómo cuentan los números:

- La **pérdida al stop** es contratos × |entrada menos stop| × valor del punto del micro (2 $ en MNQ, 5 $ en
  MES, 100 $ en MCL, 10 $ en MGC); del mini si el símbolo es el mini.
- El **día** suma el riesgo de las operaciones abiertas (su pérdida al stop) y la pérdida realizada neta de
  las cerradas, según `dia.json`. Por eso importa apuntar: `registrar --abrir` al poner la orden,
  `registrar --resultado` al cerrarla.
- La **huella** es un sha1 de los campos de la orden (símbolo, lado, contratos, tipo, precio, stop,
  objetivo, cierre). Una orden editada tiene otra huella y necesita otro `check`.
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
- Nada de este pack envía órdenes a ningún bróker ni a ninguna firma de fondeo. Las operaciones las pone el usuario en su plataforma, con su stop.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
