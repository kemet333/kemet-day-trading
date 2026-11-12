---
name: kemet-tamano
description: >-
  Tamaño por operación en cuentas de fondeo. Convierte tu firma y tu cuenta (Topstep, Apex, Tradeify,
  Alpha Futures, Lucid: 76 cuentas con fecha de comprobación) en kemet/config.json con la regla Kemet
  para quien empieza: pérdida máxima del día = la menor entre el límite diario de la firma y un cuarto
  del drawdown, riesgo por operación = un tercio de eso (tres fallos y paras). Con un stop en puntos dice
  cuántos micros caben; con el plan de kemet-salida escribe UNA orden bracket en micros a kemet/orden.json
  con el tope de la cuenta y lo que queda del día. Un plan que no cabe en 0 contratos es un rechazo con
  motivo, no una orden más pequeña. Nada se envía a ninguna plataforma. Úsala cuando el usuario diga
  «cuántos contratos», «cuántos micros caben», «qué tamaño pongo», «tengo una Apex 50K», «mi stop son 18
  puntos», «configura mi cuenta», «qué reglas tiene mi firma», o después de que kemet-salida escriba un
  plan. Va antes de kemet-riesgo; kemet-plan usa la misma regla para el tamaño del plan de sesión.
argument-hint: "[--firma apex --cuenta eod-pa-50 --mercado NQ] [--stop 18]"
---

# kemet-tamano

Convierte «tengo una Apex 50K y mi stop son 18 puntos» en «4 MNQ», con la regla de tu firma y la regla
Kemet para quien empieza. El stop decide el tamaño: cuanto más lejos, menos contratos. Con el plan de
kemet-salida escribe una orden propuesta; kemet-riesgo la comprueba y la pones tú en tu plataforma. La
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

`--semaforo verde|ambar|rojo` reduce la pérdida del día a la mitad en ámbar y en rojo. `--zona` solo se
guarda para que las demás skills sepan desde dónde operas. `--max-micro` pone el tope de tu panel cuando la
cuenta no lo publica (Topstep Express Funded) o el tuyo es menor. `--json` imprime el documento completo.
Código de salida: 0 si hay orden o caben contratos, 1 si es un rechazo, 2 si hay un error.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `reglas-de-firmas.json` (en esta carpeta) | las 76 cuentas: drawdown y tipo, límite diario, contratos, hora límite, noticias, consistencia, fecha de comprobación |
| `kemet/config.json` | lo escribe `config`; lo leen todas las skills (ejemplo en `config.example.json`) |
| `kemet/plan.json` | la operación planificada: lado, entrada, stop, objetivo, fecha, hora de estar plano (kemet-salida) |
| `kemet/estado/dia.json` | lo ya arriesgado hoy: riesgo de las abiertas y pérdidas realizadas (kemet-riesgo `registrar`) |
| `kemet/orden.json` | la orden bracket propuesta que escribe `orden --escribir` |

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

## Reglas

- Propuestas, nada más. Esta skill no habla con ningún bróker ni con ninguna firma.
- Toda cifra sale del archivo de reglas, del config, del plan o del estado del día. Nada se supone.
- Un plan de otra fecha se rechaza: se hace uno nuevo con kemet-salida.
- Puntos del contrato y dólares por micro; los minis solo como equivalencia cuando la cuenta los permite.
- Nunca imprime un beneficio esperado. Un objetivo es un plan, no una previsión.

## Lo que nunca hace

No pone ni aprueba órdenes, no sube un límite por su cuenta, no acorta un stop para que quepan más
contratos, no dimensiona por encima del tope de la cuenta y no convierte un rechazo en una orden más pequeña.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes a ningún bróker ni a ninguna firma de fondeo. Las operaciones las pone el usuario en su plataforma, con su stop.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
