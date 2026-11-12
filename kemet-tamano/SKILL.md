---
name: kemet-tamano
description: >-
  Tamaño por operación en cuentas de fondeo. Convierte tu firma y tu cuenta (Topstep, Apex, Tradeify,
  Alpha Futures, Lucid: 76 cuentas con fecha de comprobación) en kemet/config.json con la regla Kemet
  para quien empieza: pérdida máxima del día = la menor entre el límite diario de la firma y un cuarto
  del drawdown, riesgo por operación = un tercio de eso (tres fallos y paras). Con un stop en puntos dice
  cuántos micros caben; con el plan de kemet-salida escribe UNA orden bracket en micros a kemet/orden.json
  con el tope de la cuenta y lo que queda del día. Un plan que no cabe en 0 contratos es un rechazo con
  motivo, no una orden más pequeña. También la cuenta propia (--propia: presupuesto, pérdida máxima por
  operación y del día) para acciones de EE. UU. o futuros sin firma: tamaño en acciones enteras con los
  topes de posición, orden máxima y efectivo, y la orden bracket en el formato de place_stock_order de
  Alpaca que kemet-broker puede enviar en cuenta papel tras el PASS de kemet-riesgo y tu sí. Úsala cuando el
  usuario diga «cuántos contratos», «cuántos micros caben», «cuántas acciones», «qué tamaño pongo», «tengo
  una Apex 50K», «tengo 5.000 dólares en Alpaca», «mi stop son 18 puntos», «mi stop son 3 dólares»,
  «configura mi cuenta», «qué reglas tiene mi firma», o después de que kemet-salida escriba un plan. Va
  antes de kemet-riesgo; kemet-plan usa la misma regla para el tamaño del plan de sesión.
argument-hint: "[--firma apex --cuenta eod-pa-50 --mercado NQ | --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150 --mercado TSLA] [--stop 18]"
---

# kemet-tamano

Convierte «tengo una Apex 50K y mi stop son 18 puntos» en «4 MNQ», con la regla de tu firma y la regla
Kemet para quien empieza, y «tengo 5.000 dólares y mi stop son 3,57 dólares por acción» en «9 acciones de
TSLA», con tus propios límites. El stop decide el tamaño: cuanto más lejos, menos contratos o acciones. Con
el plan de kemet-salida escribe una orden propuesta; kemet-riesgo la comprueba y la pones tú en tu
plataforma (o kemet-broker, en papel, cuando digas que sí a ese ticket). La
mayoría de los que hacen day trading pierde dinero, y una herramienta no cambia eso: un tamaño que cabe
en el límite del día hace pequeña cada pérdida, no gana la operación.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/tamano.py" listar                                        # firmas y cuentas que conoce
python3 "${CLAUDE_SKILL_DIR}/tamano.py" config --firma apex --cuenta eod-pa-50 --mercado NQ   # escribe kemet/config.json
python3 "${CLAUDE_SKILL_DIR}/tamano.py" config --firma topstep --cuenta combine-50 --semaforo ambar --plano-a 16:00
python3 "${CLAUDE_SKILL_DIR}/tamano.py" config --firma apex --cuenta eod-eval-150 --perdida-dia 900   # tu propio límite del día
python3 "${CLAUDE_SKILL_DIR}/tamano.py" calc --stop 18                                # micros que caben con kemet/config.json
python3 "${CLAUDE_SKILL_DIR}/tamano.py" calc --firma apex --cuenta eod-pa-50 --mercado NQ --stop 18
python3 "${CLAUDE_SKILL_DIR}/tamano.py" calc --drawdown 2000 --diario 1000 --mercado ES --stop 6   # sin firma: tus límites
python3 "${CLAUDE_SKILL_DIR}/tamano.py" orden --escribir                              # kemet/plan.json -> kemet/orden.json
python3 "${CLAUDE_SKILL_DIR}/tamano.py" orden --ahora "2026-11-11 10:45" --json       # fija el reloj (hora de Nueva York)
```

Cuenta propia (acciones de EE. UU., o futuros con tus límites y sin firma):

```bash
python3 "${CLAUDE_SKILL_DIR}/tamano.py" config --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150 --mercado TSLA
python3 "${CLAUDE_SKILL_DIR}/tamano.py" config --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150 --max-posicion-pct 75 --max-orden 4000 --min-orden 5 --efectivo-pct 10
python3 "${CLAUDE_SKILL_DIR}/tamano.py" calc --stop 3.57 --entrada 393.08             # acciones enteras que caben (TSLA del config)
python3 "${CLAUDE_SKILL_DIR}/tamano.py" calc --stop 3.57 --mercado TSLA --presupuesto 5000 --max-perdida-operacion 50   # sin config
python3 "${CLAUDE_SKILL_DIR}/tamano.py" orden --escribir                              # plan de una acción -> orden bracket (formato Alpaca)
python3 "${CLAUDE_SKILL_DIR}/tamano.py" orden --limite 393.00 --escribir              # una orden límite a ese precio (solo --limite: la entrada del plan)
```

`--semaforo verde|ambar|rojo` reduce la pérdida del día a la mitad en ámbar y en rojo. `--zona` solo se
guarda para que las demás skills sepan desde dónde operas. `--max-micro` pone el tope de tu panel cuando la
cuenta no lo publica (Topstep Express Funded) o el tuyo es menor. Con `--propia`: `--permitir-cortos` deja
vender en corto (por defecto no), `--sec-user-agent "Nombre correo@ejemplo.com"` es lo que piden EDGAR y el
House Clerk a kemet-resultados y kemet-congreso (también vale la variable `SEC_USER_AGENT`). `--json`
imprime el documento completo. Código de salida: 0 si hay orden o caben contratos, 1 si es un rechazo, 2 si
hay un error.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `reglas-de-firmas.json` (en esta carpeta) | las 76 cuentas: drawdown y tipo, límite diario, contratos, hora límite, noticias, consistencia, fecha de comprobación |
| `kemet/config.json` | lo escribe `config`; lo leen todas las skills (ejemplos en `config.example.json` y `config.propia.example.json`). `tipo_cuenta` dice si es de firma o propia |
| `kemet/plan.json` | la operación planificada: lado, entrada, stop, objetivo, fecha, hora de estar plano (kemet-salida); de un futuro o de una acción |
| `kemet/estado/dia.json` | lo ya arriesgado hoy: riesgo de las abiertas y pérdidas realizadas (kemet-riesgo `registrar`) |
| `kemet/estado/broker.json` | lo que kemet-broker colocó hoy en papel: cuenta como operación y, si trae su pérdida al stop, en el día |
| `kemet/portfolio.json` | (acciones) el efectivo y las posiciones que lleva kemet-broker; sin él, el presupuesto del config |
| `kemet/precios.json` | (acciones) el último precio de kemet-alertas: si tiene menos de 15 minutos y está por encima de la entrada de un largo, el riesgo se mide desde él |
| `kemet/orden.json` | la orden bracket propuesta que escribe `orden --escribir`: en contratos (`"instrumento": "futuro"`) o en acciones con los campos de Alpaca (`"instrumento": "accion"`) |

## Las reglas

- **Pérdida máxima del día**: la menor entre el límite diario de la firma (si lo tiene) y un cuarto del
  drawdown. En ámbar o rojo, la mitad. Con `--perdida-dia` la fijas tú, nunca por encima del límite diario
  de la firma (si lo supera, rechaza); el config guarda de dónde sale (`perdida_max_dia_origen`).
- **Riesgo por operación**: la pérdida máxima del día entre tres. Tres fallos y paras.
- **Contratos**: el menor de tres límites, en micros enteros: riesgo por operación entre (riesgo en puntos
  por valor del punto del micro), el tope de micros de la cuenta, y lo que queda del día (pérdida máxima
  del día menos el riesgo abierto y lo perdido hoy). Si la cuenta permite minis y caben 10 micros o más,
  dice el equivalente en minis como nota.
- **Hora de estar plano** (`plano_a`): la del contrato (15:55 NY en índices, 14:25 CL, 13:25 GC) o la que
  pidas, nunca después de la hora límite de la firma menos 5 minutos. Topstep la da en Chicago (15:10),
  una hora por detrás de Nueva York: 16:10 NY, así que plano como tarde a las 16:05.
- **Ventana de entradas**: sin entradas antes de las 09:45 ni después de las 15:00 NY.
- **Cuenta propia** (`--propia`): la pérdida máxima del día y el riesgo por operación los pones tú
  (`--max-perdida-dia`, `--max-perdida-operacion`); en ámbar o rojo, la mitad. Tres operaciones al día. Sin
  hora límite de firma: plano a las 15:55 NY. `permitir_cortos`, `permitir_margen` y `permitir_opciones`
  vienen en `false` y `bloqueados` vacío; se cambian en el archivo.
- **Acciones enteras** (cuenta propia, plan de un ticker): el menor de riesgo por operación / riesgo por
  acción (entrada menos stop), `max_posicion_pct` × presupuesto / entrada, `max_orden_usd` / entrada,
  efectivo disponible / entrada (el efectivo de `kemet/portfolio.json` si existe, si no el presupuesto,
  menos el colchón `efectivo_pct`), y lo que queda del día. Menos de `min_orden_usd` es un rechazo. La
  entrada que mide: tu límite con `--limite`; a mercado, la del plan, o el último precio de
  `kemet/precios.json` si tiene menos de 15 minutos y es peor (más alto en un largo): un precio que corrió
  desde el plan pierde más con el mismo stop. Nunca al revés: un precio mejor no sube el tamaño. Un corto
  con `permitir_cortos: false` es un rechazo.
- **Formato de la orden de una acción**: los campos de `place_stock_order` de Alpaca, con cantidades y
  precios como texto: `symbol`, `side` buy|sell, `qty`, `type` market|limit (`limit_price`),
  `time_in_force` day, `order_class` bracket, `take_profit_limit_price`, `stop_loss_stop_price`; más `why`,
  `plan` e `instrumento` como notas. Un futuro sigue en contratos (`simbolo` MNQ, `lado`, `contratos`…) con
  `"instrumento": "futuro"`.

## Pasos

1. Si no hay `kemet/config.json`, pregunta firma, cuenta y fase y ejecuta `listar` si el usuario no
   recuerda el nombre de la suya; después `config`. Dile en una línea la pérdida máxima del día, el riesgo
   por operación y la hora límite, y que las firmas cambian las reglas: la de su panel manda.
2. Para «cuántos contratos», `calc --stop N` con su stop en puntos del contrato. Muestra la tabla: drawdown,
   pérdida máxima del día, riesgo por operación, stop, valor del punto del micro y contratos que caben, y
   debajo la regla de la firma que limita.
3. Con un plan de kemet-salida, `orden --escribir`. Muestra los tres límites, cuál manda, los contratos y la
   pérdida al stop. Un rechazo se dice tal cual, con su motivo; nunca se acorta el stop ni se sube un
   límite para que quepa.
4. Pasa a kemet-riesgo. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan
   filtros y parámetros validados en su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Apex 50K EOD financiada (`--firma apex --cuenta eod-pa-50`): drawdown 2.000 $, límite diario 1.000 $.

```
$ python3 tamano.py config --firma apex --cuenta eod-pa-50 --mercado NQ
Config escrita en kemet/config.json
Cuenta: Apex Trader Funding · 50K EOD fondeada (PA) (financiada) · mercado NQ
Drawdown 2.000 $ (eod_trailing) · límite diario de la firma 1.000 $
Pérdida máxima del día (verde): 500 $ · riesgo por operación: 166,67 $ (tres fallos y paras)
Tope de contratos: 100 micros · 10 minis
Hora límite de la firma: 16:59 America/New_York · plano a las 15:55 NY · sin entradas antes de 09:45 ni después de 15:00 NY
```

Con un stop de 18 puntos:

```
$ python3 tamano.py calc --stop 18
Cuenta: Apex Trader Funding · 50K EOD fondeada (PA)
Drawdown 2.000 $ · límite diario de la firma 1.000 $ · regla Kemet: 25% del drawdown = 500 $
Pérdida máxima de hoy (verde): 500 $ · riesgo por operación: 167 $ (tres fallos y paras)
Stop 18 pts × 2 $/pt del MNQ = 36,00 $ por micro
Contratos: 4 MNQ
```

La ruptura del balance inicial de ese día (fixture real de Yahoo, velas de 5 minutos): balance inicial de
09:30 a 10:30, 28.199 a 28.426 (227 puntos). La primera vela cerrada fuera después de las 10:30 fue la de
las 10:40, que cerró en 28.429,75: largo a 28.429,75 a las 10:45, stop en el punto medio del IB
(28.312,50), objetivo 1R en 28.547, riesgo 117,25 puntos = 234,50 $ por MNQ. El objetivo se tocó a las
10:55. Con ese plan en `kemet/plan.json`:

```
$ python3 tamano.py orden --ahora "2026-11-11 10:45" --escribir
ORDEN · NQ · 2026-11-11 · 16:45 Madrid / 10:45 NY
largo NQ a 28.429,75 (10:45) · stop 28.312,50 · objetivo 28.547 · riesgo 117,25 pts = 234,50 $ por MNQ · R 1,00
Cuenta: Apex Trader Funding · 50K EOD fondeada (PA) · pérdida máxima del día 500 $ · riesgo por operación 166,67 $ · hoy 0 operaciones, 0 $ abierto, 0 $ perdido

Límites (micros enteros; manda el menor):
  riesgo por operación   166,67 $ / 234,50 $ por micro                                       0 MNQ  <- manda
  tope de la cuenta      100 micros en Apex Trader Funding · 50K EOD fondeada (PA)         100 MNQ
  lo que queda del día   500 $ menos 0 $ abierto y 0 $ perdido = 500 $ / 234,50 $            2 MNQ

Sin orden: un MNQ arriesga 234,50 $ al stop (117,25 puntos × 2 $/pt), más que tu riesgo por operación de 166,67 $. Déjala pasar o planifica un stop más corto con kemet-salida
```

Rechazo honesto: en una 50K, un solo micro con ese stop arriesga más que el riesgo por operación. No se
escribe nada. La misma operación en una Apex 150K EOD financiada (`eod-pa-150`: 1.000 $ al día, 333,33 $
por operación):

```
$ python3 tamano.py orden --ahora "2026-11-11 10:45" --escribir
largo NQ a 28.429,75 (10:45) · stop 28.312,50 · objetivo 28.547 · riesgo 117,25 pts = 234,50 $ por MNQ · R 1,00

Límites (micros enteros; manda el menor):
  riesgo por operación   333,33 $ / 234,50 $ por micro                                       1 MNQ  <- manda
  tope de la cuenta      170 micros en Apex Trader Funding · 150K EOD fondeada (PA)        170 MNQ
  lo que queda del día   1.000 $ menos 0 $ abierto y 0 $ perdido = 1.000 $ / 234,50 $        4 MNQ

Tamaño: 1 MNQ. Pérdida al stop: 1 × 234,50 $ = 234,50 $.
Orden bracket propuesta (nada se ha enviado a ninguna plataforma):
  compra 1 MNQ, stop a 28.429,75, stop 28.312,50, objetivo 28.547
Escrita 1 orden propuesta en kemet/orden.json
```

Y en `kemet/orden.json`:

```json
{"generado": "2026-11-11T15:45:00Z",
 "ordenes": [{"simbolo": "MNQ", "lado": "compra", "contratos": 1, "tipo": "stop", "precio": 28429.75,
              "stop": 28312.5, "objetivo": 28547.0, "riesgo_pts": 117.25, "perdida_max_usd": 234.5,
              "por_que": "largo NQ: 1 MNQ, manda riesgo por operación (1 × 234,50 $ = 234,50 $ al stop)",
              "plan": {"fecha": "2026-11-11", "lado": "largo", "entrada": 28429.75, "stop": 28312.5, "objetivo": 28547.0,
                       "regla_stop": "ib-medio", "regla_objetivo": "R:1", "plano_a": "15:55", "…": "el resto del plan"}}],
 "cuenta": "Apex Trader Funding · 150K EOD fondeada (PA)", "papel": true}
```

Si a mediodía ya hay 320 $ abiertos y 500 $ perdidos en `kemet/estado/dia.json`, quedan 180 $ y ni un
micro de 234,50 $ cabe: 0 contratos y «el día está hecho». Con un stop de 40 puntos (80 $ por micro) en esa
misma situación saldrían 2 MNQ, y mandaría «lo que queda del día».

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026, cuenta propia

Cuenta propia de 5.000 $ con 50 $ de pérdida máxima por operación y 150 $ al día:

```
$ python3 tamano.py config --propia --presupuesto 5000 --max-perdida-operacion 50 --max-perdida-dia 150 --mercado TSLA
Config escrita en kemet/config.json
Cuenta: Cuenta propia · 5.000 $ · mercado TSLA (acción)
Pérdida máxima del día (verde): 150 $ · riesgo por operación: 50,00 $ · como mucho 3 operaciones al día
Topes: posición 75 % del presupuesto (3.750 $) · orden entre 5 $ y 4.000 $ · colchón de efectivo 10 % (500 $)
Sin hora límite de firma · plano a las 15:55 NY · sin entradas antes de 09:45 ni después de 15:00 NY
Cortos: no · margen: no · opciones: no · bloqueados: ninguno
```

La ruptura del rango de apertura de TSLA ese día (fixture real de Yahoo, velas de 5 minutos): rango de 15
minutos de 09:30 a 09:45, 386,35 a 392,67 $. La primera vela cerrada fuera fue la de las 10:10, que cerró a
las 10:15 en 393,08 $: largo a 393,08, stop en el punto medio del rango (389,51), objetivo 1R en 396,65,
riesgo 3,57 $ por acción. No llegó al objetivo (máximo del día 395,43) y el stop saltó a las 15:50. Con ese
plan en `kemet/plan.json`:

```
$ python3 tamano.py orden --ahora "2026-11-11 10:15" --escribir
ORDEN · TSLA · 2026-11-11 · 16:15 Madrid / 10:15 NY
largo TSLA a 393,08 $ (10:15) · stop 389,51 $ · objetivo 396,65 $ · riesgo 3,57 $ por acción (la entrada del plan) · R 1,00
Cuenta: Cuenta propia · 5.000 $ · pérdida máxima del día 150 $ · riesgo por operación 50,00 $ · hoy 0 operaciones, 0 $ abierto, 0 $ perdido

Límites (acciones enteras; manda el menor):
  riesgo por operación   50,00 $ / 3,57 $ por acción                                        14 TSLA
  posición máxima        75 % de 5.000 $ = 3.750 $ / 393,08 $                                9 TSLA  <- manda
  orden máxima           4.000 $ / 393,08 $                                                 10 TSLA
  efectivo               5.000 $ menos 500 $ de colchón = 4.500 $ / 393,08 $                11 TSLA
  lo que queda del día   150 $ menos 0 $ abierto y 0 $ perdido = 150 $ / 3,57 $             42 TSLA

Tamaño: 9 acciones de TSLA = 3.537,72 $. Pérdida al stop: 9 × 3,57 $ = 32,13 $.
Un stop es una orden, no una promesa: en un mercado rápido se llena peor que 389,51 $.

Orden bracket propuesta (campos de place_stock_order; nada se ha enviado a ningún bróker):
  buy 9 TSLA, a mercado, día, objetivo 396.65, stop 389.51
Plano a las 15:55 NY: lo que siga abierto se cierra (kemet-alertas avisa).

Siguiente: kemet-riesgo la comprueba; kemet-broker te lee el ticket y espera tu sí.
Escrita 1 orden propuesta en kemet/orden.json
```

Por el riesgo cabrían 14 acciones; manda la posición máxima, 3.750 $ a 393,08 $ son 9. Y en `kemet/orden.json`,
con las cantidades y los precios como texto, tal cual los quiere `place_stock_order`:

```json
{"generado": "2026-11-11T15:15:00Z",
 "ordenes": [{"symbol": "TSLA", "side": "buy", "qty": "9", "type": "market", "time_in_force": "day",
              "order_class": "bracket", "take_profit_limit_price": "396.65", "stop_loss_stop_price": "389.51",
              "why": "largo TSLA: 9 acciones, manda posición máxima (9 × 3,57 $ = 32,13 $ al stop)",
              "plan": {"fecha": "2026-11-11", "lado": "largo", "entrada": 393.08, "stop": 389.51, "objetivo": 396.65,
                       "hora_entrada": "10:15", "plano_a": "15:55", "riesgo_por_accion": 3.57, "perdida_max_usd": 32.13,
                       "coste": 3537.72, "…": "el resto del plan"},
              "instrumento": "accion"}],
 "cuenta": "Cuenta propia · 5.000 $", "papel": true}
```

`calc --stop 3.57 --entrada 393.08` da la misma tabla sin el plan. Si `kemet/precios.json` trae TSLA a
394,50 $ leído hace un minuto, la orden a mercado se mide desde 394,50: riesgo 4,99 $ por acción y 10
acciones por el riesgo (la posición sigue mandando con 9). Con el precio a 392 no cambia nada. Con
`--limite 393.00`, una orden limit a 393,00 con el stop a 3,49 $.

## Reglas

- Propuestas, nada más. Esta skill no habla con ningún bróker ni con ninguna firma.
- Toda cifra sale del archivo de reglas, del config, del plan o del estado del día. Nada se supone.
- Un plan de otra fecha se rechaza: se hace uno nuevo con kemet-salida.
- Puntos del contrato y dólares por micro; los minis solo como equivalencia cuando la cuenta los permite.
- Nunca imprime un beneficio esperado. Un objetivo es un plan, no una previsión.

## Lo que nunca hace

No pone ni aprueba órdenes, no sube un límite por su cuenta, no acorta un stop para que quepan más
contratos, no dimensiona por encima del tope de la cuenta, no fracciona acciones, no mide el riesgo desde un
precio mejor que el del plan y no convierte un rechazo en una orden más pequeña.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
