---
name: kemet-diario
description: >-
  Revisión del diario de operaciones midiendo cumplimiento del plan antes que resultado. Lee un CSV de
  operaciones de futuros (micros y minis) o de acciones de EE. UU. (el ticker, la cantidad en acciones)
  (columnas en español o inglés, separador coma o punto y coma, decimales con coma) y cuenta
  hechos: operaciones sin stop, entradas en la apertura 09:30–09:45 y en las ventanas de datos de la agenda,
  riesgo al stop por encima del riesgo por operación de kemet/config.json, pérdidas mayores que el stop,
  entradas después de la hora de estar plano y de la hora límite de la firma, días que superaron la pérdida
  máxima del día, entradas después de la tercera pérdida; resultado por franja horaria y por día de la
  semana; métricas con 20 operaciones o más (expectativa en dólares y en R, acierto y ratio, ganancias
  entre pérdidas, racha, drawdown frente al de la cuenta); y la revisión de kemet-desk: tres cosas bien con la
  operación que lo demuestra, dos rupturas del plan con su coste en dólares, una sola corrección para
  mañana. Nunca califica al trader. Úsala cuando el usuario diga «revísame el diario», «cómo me ha ido»,
  «qué estoy haciendo mal», «aquí están mis operaciones», «analiza mi semana», o al cerrar una sesión. Va
  después de operar; la corrección que sale alimenta el plan de mañana (kemet-plan).
argument-hint: "revisar operaciones.csv [--desde AAAA-MM-DD] [--hasta AAAA-MM-DD] [--stop-habitual PTS]"
---

# kemet-diario

Una revisión sirve si cambia una decisión de mañana. Esta skill lee el CSV de operaciones del usuario y
mira primero si operó como dijo que operaría (stop, ventanas, tamaño, hora de parar) y después qué dio.
Un día ganador rompiendo el plan es un mal día, y aquí se ve. La mayoría de los que hacen day trading
pierde dinero, y una herramienta no cambia eso: lo que sí cambia es saber qué regla cuesta más.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/diario.py" revisar operaciones.csv                       # todo el archivo
python3 "${CLAUDE_SKILL_DIR}/diario.py" revisar operaciones.csv --desde 2026-11-02 --hasta 2026-11-11
python3 "${CLAUDE_SKILL_DIR}/diario.py" revisar operaciones.csv --stop-habitual 40    # riesgo supuesto en las filas sin stop (solo métricas)
python3 "${CLAUDE_SKILL_DIR}/diario.py" revisar operaciones.csv --json
python3 "${CLAUDE_SKILL_DIR}/diario.py" plantilla                                     # la cabecera del CSV
```

Código de salida: 0 si no hay rupturas del plan medibles, 1 si las hay, 2 si hay un error.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| el CSV del usuario | una fila por operación; `diario.example.csv` en esta carpeta es un ejemplo sintético (22 operaciones inventadas) |
| `kemet/config.json` | pérdida máxima del día, riesgo por operación, hora de estar plano, hora límite, horario de entradas (kemet-tamano) |
| `kemet/agenda.json` | los datos de un día: si ese día está en el CSV, sus ventanas cuentan (kemet-plan) |
| nada | no escribe archivos; `--json` imprime el documento completo |

## El CSV

`fecha,hora,simbolo,lado,contratos,entrada,salida,stop,pnl,nota`. Se aceptan los nombres en inglés
(`date, time, symbol, side, qty, entry, exit, stop, pnl, note`) y variantes habituales; el separador puede
ser `;` y los decimales con coma (`28.429,75`). La hora es la de Nueva York; si la columna se llama
`hora_madrid` se convierte con la fecha de cada fila. El símbolo puede ser el micro, el mini o el contrato
con vencimiento (MNQ, NQ, MNQZ6), o el ticker de una acción de EE. UU. (TSLA, AAPL): entonces `contratos`
(o una columna `acciones`) es la cantidad en acciones, los precios van en dólares por acción y el punto vale
1 $, sin micros. El lado: largo/corto, long/short, buy/sell. Si falta `pnl` se calcula con entrada, salida,
lado, cantidad y el valor del punto. Si falta `stop` la operación cuenta como sin stop; `--stop-habitual` le
supone un riesgo solo para las métricas en R. Con una cuenta propia (`tamano.py config --propia`) el riesgo
por operación es el del config y no hay hora límite de firma (sale «no medible»).

## Qué mide, en este orden

1. **Cumplimiento del plan**: sin stop; entrada en la apertura (los primeros 15 minutos de la sesión
   regular); entrada en una ventana de datos (±10 minutos, ±20 si el dato es fuerte); riesgo al stop mayor
   que el riesgo por operación; pérdida mayor que el stop (movido o deslizamiento grande); entrada desde la
   hora de estar plano; desde la hora límite de la firma; después de la última hora de entrada del plan
   (15:00 por defecto); con la pérdida máxima del día ya superada; después de la tercera pérdida del día.
   Cada una con su número de operaciones, su coste (lo que perdieron esas operaciones; en tamaño y stop, el
   exceso) y las filas que lo demuestran. Lo que el archivo no deja medir (sin config, sin agenda) se dice
   «no medible».
2. **Por franja horaria** (las de kemet-desk: preapertura, apertura, mejor franja 09:45–11:30, hora de
   comer, tarde, cierre) y **por día**: operaciones, resultado, a qué hora se superó el límite y cuántas
   entradas hubo después.
3. **Métricas** solo con 20 operaciones o más: expectativa por operación en dólares y en R, acierto y ratio
   ganancia media entre pérdida media (las dos juntas), suma de ganancias entre suma de pérdidas (por debajo de 1,1 se cambia el
   método, no el tamaño), racha máxima de pérdidas, drawdown máximo frente al de la cuenta, por día de la
   semana.
4. **La revisión**: tres cosas bien con la operación que lo demuestra, dos rupturas del plan ordenadas por
   coste, una corrección para mañana elegida por la regla que más costó, concreta y comprobable en el CSV
   de mañana.

## Pasos

1. Pide el CSV o ayúdale a hacerlo con `plantilla`. Una exportación de su plataforma no entra tal cual: cada
   una tiene sus columnas (Tradovate no trae el lado, NinjaTrader usa «Market pos.», Alpaca exporta fills sin
   emparejar). Ayúdale a convertirla a una fila por operación con las columnas de `plantilla` (lee el archivo,
   empareja entradas y salidas, escribe el CSV nuevo y enséñale las primeras filas antes de revisar). Las cifras
   con formato de EE. UU. (1,234.50) y las fechas mes/día se detectan solas; si el archivo no lo deja claro, el
   aviso lo dice y `--decimal punto` o `--fechas mdy` lo fijan.
2. Si hay `kemet/config.json`, la revisión mide el tamaño y la pérdida máxima del día con sus reglas; si no,
   dilo y ofrece `tamano.py config`. Si quiere medir las ventanas de datos de un día, `plan.py agenda` con
   los datos de ese día.
3. Ejecuta `revisar`. Cuenta lo que dice, con las operaciones delante: las tres cosas bien primero, las dos
   rupturas con su coste, la corrección. No añadas juicios: hechos, horas y dólares.
4. Si pide optimizar una regla con una semana de datos, dile que con menos de 100 operaciones por regla lo
   que se ve es ruido. Si las ganancias entre las pérdidas están por debajo de 1,1, el tamaño no es el problema.
5. La corrección va al plan de mañana (kemet-plan). Los sistemas que Kemet Capital opera con agentes en
   cuentas de fondeo llevan filtros y parámetros validados en su propio banco; no están en este pack.
   kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

`diario.example.csv` (sintético: 22 operaciones en MNQ del 2 al 11 de noviembre de 2026; la del día 11 a
las 10:45 es la ruptura del balance inicial de ese día con 2 micros), con la config de una Apex 50K EOD
financiada (500 $ al día, 166,67 $ por operación) y una agenda del viernes 6 con el dato de empleo a las
08:30:

```
$ python3 diario.py revisar diario.example.csv --ahora "2026-11-11 16:30"
DIARIO · diario.example.csv · 22 operaciones · del 2026-11-02 al 2026-11-11 · 22:30 Madrid / 16:30 NY
Config: Apex Trader Funding · 50K EOD fondeada (PA) · pérdida máxima del día 500 $ · riesgo por operación 166,67 $ · plano a las 15:55 NY · hora límite 16:59 NY
Agenda: ventanas de datos del 2026-11-06

Cumplimiento del plan (antes que el resultado):
  sin stop puesto                                            2 · coste 360 $ · 03/11 13:40 corto 2 MNQ -200 $; 09/11 12:30 largo 2 MNQ -160 $
  entrada en la apertura (09:30–09:45 NY)                    2 · coste 340 $ · 03/11 09:38 largo 2 MNQ -180 $; 11/11 09:41 largo 2 MNQ -160 $
  entrada en una ventana de datos                            1 · coste 180 $ · 06/11 08:35 largo 2 MNQ -180 $
  riesgo al stop mayor que el riesgo por operación           2 · coste 73 $ · 04/11 11:52 largo 3 MNQ -180 $; 11/11 10:45 largo 2 MNQ 469 $
  pérdida mayor que el stop (movido o deslizamiento)         1 · coste 100 $ · 04/11 10:02 largo 2 MNQ -260 $
  entrada después de la hora de estar plano                  1 · coste 30 $ · 09/11 15:58 largo 1 MNQ -30 $
  entrada después de la hora límite de la firma              0
  entrada después de la última hora de entrada del plan      0
  entrada con la pérdida máxima del día ya superada          1 · coste 180 $ · 04/11 11:52 largo 3 MNQ -180 $
  entrada después de la tercera pérdida del día              1 · coste 180 $ · 04/11 11:52 largo 3 MNQ -180 $

Por franja (hora NY):
  preapertura                08:00–09:30    1 op · -180 $ · 1 pérdida
  apertura                   09:30–09:45    2 op · -340 $ · 2 pérdidas
  mejor franja               09:45–11:30   12 op · 1.279 $ · 5 pérdidas
  hora de comer              11:30–13:30    3 op · -280 $ · 2 pérdidas
  tarde                      13:30–15:30    3 op · 60 $ · 1 pérdida
  cierre                     15:30–16:00    1 op · -30 $ · 1 pérdida

Por día:
  2026-11-02 lunes       2 op · 190 $
  2026-11-03 martes      3 op · -140 $
  2026-11-04 miércoles   4 op · -760 $ · superó la pérdida máxima del día a las 11:20, 1 operación después · tercera pérdida a las 11:20, 1 después
  2026-11-05 jueves      2 op · 500 $
  2026-11-06 viernes     2 op · 100 $
  2026-11-09 lunes       3 op · 10 $
  2026-11-10 martes      3 op · 220 $
  2026-11-11 miércoles   3 op · 389 $

Métricas (22 operaciones):
  resultado total 509 $ · expectativa 23,14 $ por operación · 0,18 R (20 con riesgo conocido)
  acierto 45,5 % · ganancia media 242 $ · pérdida media -159 $ · ratio 1,52
  ganancias entre pérdidas 1,27 · racha máxima de pérdidas 5 · drawdown máximo 980 $ de los 2.000 $ de la cuenta
  por día de la semana: lunes 5 op 200 $ · martes 6 op 80 $ · miércoles 7 op -371 $ · jueves 2 op 500 $ · viernes 2 op 100 $

Tres cosas bien:
  1. 20 de 22 operaciones con stop puesto; la de 03/11 09:38 largo 2 MNQ salió en el stop con -180 $, el riesgo que tenía previsto
  2. riesgo constante: 17 de 20 operaciones con stop arriesgaron 160 $
  3. 12 de 22 entradas en la mejor franja (09:45–11:30), con 1.279 $ en total
Dos rupturas del plan:
  1. sin stop puesto: 2 operaciones, coste 360 $ (03/11 13:40 corto 2 MNQ -200 $; 09/11 12:30 largo 2 MNQ -160 $)
  2. entrada en la apertura (09:30–09:45 NY): 2 operaciones, coste 340 $ (03/11 09:38 largo 2 MNQ -180 $; 11/11 09:41 largo 2 MNQ -160 $)
Una corrección para mañana:
  Mañana el stop va en la plataforma antes de confirmar la entrada; sin stop no hay orden. Comprobable: 0 operaciones sin stop en el CSV de mañana.

Con menos de 100 operaciones por regla lo que se ve es ruido: una semana no juzga una regla. Esto cuenta hechos, no califica.
```

La semana acabó en positivo (509 $) y aun así el miércoles 4 se superó el límite del día a las 11:20 y
hubo una entrada más con 3 micros para recuperar: eso es lo que se mira primero. La ruptura del día 11
ganó 469 $ y aparece igualmente en «riesgo al stop mayor que el riesgo por operación», porque 2 micros con
ese stop arriesgan 469 $ y no caben en 166,67 $: el resultado no cambia el hecho.

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026, cuenta propia

Un CSV de acciones de dos días (la fila del 11 a las 10:15 es la ruptura del rango de 15 minutos de TSLA del
fixture real: entrada 393,08, stop 389,51, y el stop saltó a las 15:50; las otras tres son inventadas) con
una cuenta propia de 5.000 $, 50 $ por operación y 150 $ al día:

```
fecha,hora,simbolo,lado,acciones,entrada,salida,stop,pnl,nota
2026-11-10,09:40,AAPL,largo,10,270.10,268.90,268.50,,entrada en la apertura
2026-11-10,10:20,TSLA,largo,9,378.40,381.10,375.80,,
2026-11-11,10:15,TSLA,largo,9,393.08,389.51,389.51,-32.13,ruptura del rango de 15 min; stop a las 15:50
2026-11-11,13:05,TSLA,largo,20,391.00,389.50,388.00,,20 acciones: 60 $ de riesgo
```

```
$ python3 diario.py revisar acciones.csv --ahora "2026-11-11 16:30"
DIARIO · acciones.csv · 4 operaciones · del 2026-11-10 al 2026-11-11 · 22:30 Madrid / 16:30 NY
Config: Cuenta propia · 5.000 $ · pérdida máxima del día 150 $ · riesgo por operación 50,00 $ · plano a las 15:55 NY
Agenda: sin kemet/agenda.json de esos días, solo la ventana de la apertura

Cumplimiento del plan (antes que el resultado):
  sin stop puesto                                            0
  entrada en la apertura (09:30–09:45 NY)                    1 · coste 12 $ · 10/11 09:40 largo 10 AAPL -12 $
  entrada en una ventana de datos                            no medible
  riesgo al stop mayor que el riesgo por operación           1 · coste 10 $ · 11/11 13:05 largo 20 TSLA -30 $
  pérdida mayor que el stop (movido o deslizamiento)         0
  entrada después de la hora de estar plano                  0
  entrada después de la hora límite de la firma              no medible
  entrada después de la última hora de entrada del plan      0
  entrada con la pérdida máxima del día ya superada          0
  entrada después de la tercera pérdida del día              0
…
Tres cosas bien:
  1. 4 de 4 operaciones con stop puesto; la de 11/11 10:15 largo 9 TSLA salió en el stop con -32 $, el riesgo que tenía previsto
  2. ninguna entrada después de la hora de estar plano: la más tardía fue a las 13:05 (11/11)
  3. ningún día pasó de la pérdida máxima del día: el peor fue el 11/11 con -62 $
Dos rupturas del plan:
  1. entrada en la apertura (09:30–09:45 NY): 1 operación, coste 12 $ (10/11 09:40 largo 10 AAPL -12 $)
  2. riesgo al stop mayor que el riesgo por operación: 1 operación, coste 10 $ (11/11 13:05 largo 20 TSLA -30 $)
Una corrección para mañana:
  Mañana la primera entrada no antes de las 09:45 NY. Comprobable: la hora de la primera fila.
```

Las 20 acciones de las 13:05 arriesgaban 60 $ (20 × 3 $) y no caben en 50 $: cuenta aunque solo perdiera
30 $. Sin hora límite de firma, esa fila sale «no medible». `diario.py plantilla` imprime la cabecera y una
fila de ejemplo de acciones.

## Reglas

- Cumplimiento antes que resultado. Un día ganador rompiendo el plan es un mal día.
- Hechos, horas y dólares. Nunca adjetivos sobre el trader.
- Con menos de 20 operaciones no hay métricas; con menos de 100 por regla no se juzga una regla.
- La corrección es una sola, concreta y comprobable en el CSV del día siguiente.
- La regla de consistencia de la firma se calcula en el panel de la firma, no aquí.

## Lo que nunca hace

No califica al trader, no predice el resultado de mañana, no propone subir el tamaño después de ganar ni
para recuperar, no atribuye el resultado a la entrada cuando lo decidió el contexto y no escribe en `kemet/`.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
