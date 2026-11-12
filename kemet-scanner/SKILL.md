---
name: kemet-scanner
description: >-
  El escáner de gráficos. Recorre miles de acciones de EE. UU. y los doce
  futuros de CME y lista los gráficos que cumplen una regla: construye el
  universo de acciones ordinarias y ADR desde los directorios de Nasdaq
  Trader, escanea antes de la apertura los cierres diarios (ruptura del máximo
  de cierre de 20 días, bandera alcista, recupera la media de 20 días,
  sobreventa por RSI 14, rebote), busca durante la sesión las rupturas del
  rango de apertura de 15 minutos sobre velas de 5 minutos, y en futuros dice
  quién cerró fuera del balance inicial de la primera hora, quién está por
  encima del máximo de ayer o por debajo del mínimo, y el rango de hoy frente
  al medio de 20 sesiones. Datos gratis de Yahoo, vela a vela. Escribe
  kemet/universo.txt y kemet/watchlist.json para kemet-noticias y
  kemet-entrada. Úsala cuando el usuario diga "escanea el mercado", "qué está
  rompiendo", "busca rupturas del rango de apertura", "banderas", "valores en
  sobreventa", "escaneo de premercado", "hazme la watchlist", "qué miro hoy",
  "qué futuros se mueven", "quién ha roto el balance inicial", o al empezar
  el día, antes de kemet-noticias y kemet-niveles.
argument-hint: "[universo | diario | orb [--a HH:MM] | futuros] [--offline RUTA] [--ahora \"AAAA-MM-DD HH:MM\"]"
---

# kemet-scanner

El primer paso del día es mirar muchos gráficos y quedarse con pocos. Este tool lee miles de gráficos gratuitos y
devuelve los que cumplen una regla escrita: ni más, ni menos. Un escaneo es una lista de gráficos que cumplen una
regla, no una lista de valores que comprar, y una regla que se cumple no es una predicción. La mayoría de los que
hacen day trading pierde dinero, y una herramienta no cambia eso. Lo único que ahorra es pasar cinco mil gráficos a
mano.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde vive este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/scanner.py" universo                          # -> kemet/universo.txt
python3 "${CLAUDE_SKILL_DIR}/scanner.py" diario                            # antes de la apertura -> kemet/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scanner.py" diario --simbolos TSLA,NVDA,AMD   # o --watchlist ARCHIVO, --limite 200
python3 "${CLAUDE_SKILL_DIR}/scanner.py" orb                               # desde las 09:50 NY -> kemet/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scanner.py" orb --a 10:15                     # corta el reloj a las 10:15 NY
python3 "${CLAUDE_SKILL_DIR}/scanner.py" futuros                           # los doce contratos de CME -> kemet/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scanner.py" futuros --simbolos NQ,ES --json
python3 "${CLAUDE_SKILL_DIR}/scanner.py" futuros --offline tests/fixtures/yahoo --ahora "2026-11-11 10:45"
```

Flags: `--min-precio 5` y `--min-volumen` (diario 1.000.000, orb 0), `--rango-minutos 15` y `--max-confirmar 200`
(orb), `--ib-minutos 60` y `--sesiones 20` (futuros), `--ahora "2026-10-19 10:15"` (hora de Nueva York: fija el
reloj y permite repetir un día), `--offline RUTA` (archivos de Yahoo guardados), `--sin-escribir`, `--salida RUTA`,
`--mostrar N`, `--json`. Código de salida 0 si encontró algo, 1 si no encontró nada o no había sesión que escanear
(lo dice en una línea), 2 ante un error.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/universo.txt` | lo escribe `universo`: un `SIMBOLO\|Nombre` por línea; lo leen `diario` y `orb` |
| `kemet/watchlist.json` | lo escriben `diario`, `orb` y `futuros`: `modo`, `generado`, `universo`, `escaneados`, `fallidos`, `aciertos[]` con `simbolo`, `regla`, `precio`, `hora`, `detalle`. kemet-noticias y `entrada.py watchlist` leen `aciertos[].simbolo` |
| `kemet/config.json` | lo lee `orb`: `sin_entradas_despues` (15:00 si falta) |
| Yahoo Finance | spark (cierres de 20 símbolos por petición) y gráfico v8 (máximos y mínimos reales): gratis, sin clave, no oficial, con retraso |
| Nasdaq Trader | `nasdaqlisted.txt` y `otherlisted.txt`, los directorios públicos de símbolos |

## El universo

`universo` baja los dos directorios de nasdaqtrader.com/dynamic/SymDir y se queda con una fila cuando, en este orden:

1. No es un valor de prueba, ni un ETF, ni NextShares.
2. Es un ticker llano: de 1 a 5 letras, o de 1 a 4 letras más una letra de clase tras un punto (BRK.B). Fuera una
   preferente con `$` (ABR$D) y los sufijos `.U`, `.W` o `.R` (unidades, warrants, derechos).
3. Fuera, diga lo que diga el resto del nombre: warrants; unidades y derechos de SPAC ("Units, each consisting of",
   "Rights to receive"); notas, ETN, obligaciones; un cupón con %; "Depositary Shares" que no sean American ni
   Global (llevan una preferente).
4. Dentro: el nombre dice common stock, common shares o units, ordinary shares, shares of beneficial interest, ADS,
   ADR, American o Global depositary shares, o partnership o trust units.
5. Fuera: el nombre aún dice unit, right, bond, preferred o preference.
6. Dentro: todo lo demás (nombres llanos como "AMETEK, Inc.").

Con los archivos del 19 de octubre de 2026 quedan 5.943 valores. Con los recortados de los tests (36 filas, un caso
por regla) quedan 17. Una vez a la semana basta.

## El escaneo diario (antes de la apertura)

El spark de Yahoo devuelve cierres de 20 símbolos por petición: 5.943 símbolos son 298 peticiones, unos dos minutos y
medio con la pausa educada de 0,3 segundos. La liquidez sale del meta del spark: último precio de al menos
`--min-precio` y volumen de la última sesión de al menos `--min-volumen`. Lánzalo antes de la apertura o después del
cierre: durante la sesión el volumen es el del día hasta ese momento, y la vela diaria de hoy no cuenta hasta las
16:00.

Las reglas van solo sobre cierres (el spark no trae máximos ni mínimos):

| regla | sobre cierres |
| --- | --- |
| `ruptura-20d` | el último cierre está por encima de los 20 cierres anteriores |
| `bandera` | sube más del 10 % en las 10 sesiones anteriores a las últimas 5, y los últimos 5 cierres caben en un 5 % |
| `recupera-media-20` | el cierre anterior estaba bajo la media de 20 días y el último está encima |
| `sobreventa` | RSI 14 (Wilder) por debajo de 30 |
| `rebote` | el RSI 14 estaba bajo 30 ayer y hoy cerró arriba |

Una ruptura del máximo de cierre dispara más veces que la del máximo intradía (KO el 16 de octubre rompió su máximo
de cierre de 20 días, no el intradía). Los aciertos salen ordenados por lo negociado (precio por volumen), los más
negociados primero. Un símbolo que cumple dos reglas sale una vez, con las dos en `regla` ("sobreventa + rebote").

## La ruptura del rango de apertura (durante la sesión)

El rango de apertura son los primeros `--rango-minutos` (15) de la sesión: las velas de 09:30, 09:35 y 09:40. Un
acierto es la primera vela de 5 minutos cerrada que CIERRA por encima del máximo del rango, a la hora de su cierre.
Es la misma lógica que la ruptura del balance inicial de kemet-entrada, con 15 minutos en vez de 60 y solo por arriba.

1. Fase 1, todos los símbolos: cierres de las velas de 5 minutos de hoy por el spark, 20 por petición. Un gráfico
   sigue solo si una vela cerrada después del rango cerró en o por encima del cierre más alto del rango. Es una
   condición necesaria (el máximo del rango es al menos cualquier cierre del rango), así que no se pierde ninguna
   ruptura.
2. Fase 2, cada candidato: su gráfico v8 con máximos y mínimos reales, una petición por gráfico. Máximo del rango =
   el máximo más alto de sus velas; mínimo = el más bajo. En una mañana fuerte casi todo es candidato, así que la fase
   2 comprueba como mucho `--max-confirmar` (200), los más negociados primero, e imprime PARCIAL con cuántos dejó sin
   mirar. `--max-confirmar 0` los comprueba todos.

Un gráfico vale solo cuando están todas las velas de 5 minutos desde las 09:30 hasta el corte; una vela que falta es
una parada o un valor sin operaciones. Fuera los cierres nulos, fuera la vela fuera de la rejilla (el tick en vivo,
como 10:58:07), y una vela cuenta solo cuando ha cerrado (inicio más 5 minutos). Antes de las 09:50, en fin de semana
o festivo, después del cierre o después de `sin_entradas_despues` (una ruptura caducada) imprime una línea y no
escribe nada. Las sesiones recortadas a las 13:00 están en el calendario.

## Futuros: los doce contratos de una vez

`futuros` lee las velas de 5 minutos de ES, NQ, YM, RTY, CL, GC, SI, HG, NG, 6E, ZN y ZB (una petición por
contrato) y, para cada uno con su propia sesión regular, dice:

- **El balance inicial** de los primeros `--ib-minutos` (60) de la sesión regular y si una vela ya cerró fuera: la
  primera que cierra por encima del IB alto (`ib-arriba`) o por debajo del IB bajo (`ib-abajo`), con su hora y su
  cierre. Una mecha no cuenta. Es la misma regla de kemet-entrada, aquí para todos a la vez; si el IB aún no ha
  cerrado, lo dice.
- **El máximo y el mínimo de ayer** (la última sesión regular con velas) y dónde está el último cierre: por encima
  del máximo (`sobre-pdh`), por debajo del mínimo (`bajo-pdl`) o dentro.
- **El rango de hoy** de la sesión regular hasta ahora (o de la nocturna, si la regular no ha abierto) frente al
  medio de las últimas `--sesiones` (20) sesiones regulares completas. Es contexto, no una regla: un 40 % del medio
  a media mañana dice que el día va lento; un 120 % dice que el movimiento ya se hizo.

Un contrato entra en `aciertos` si cumple al menos una de las cuatro reglas; `precio` y `hora` son los de la
ruptura del IB si la hubo, y si no los del último cierre. Con `--offline` solo cuentan los contratos que tengan
archivo; los que falten se dicen y el escaneo se marca PARCIAL.

## Datos y límites

- Los endpoints de Yahoo son gratuitos, no oficiales y van con retraso: unos 10 minutos en futuros. Velas de 5
  minutos, vela a vela, nunca tick a tick. query2 primero, query1 ante un 429 o un 5xx, un reintento tras cinco
  segundos ante un 429.
- Lo parcial se dice como parcial: "Recibidos 4.980 de 5.943 gráficos (963 fallaron o sin datos)". Nunca se redondea
  un escaneo parcial a "todo el mercado".
- Festivos y sesiones recortadas de la NYSE y de CME para 2026 y 2027 (los de `comun`).

## Pasos

1. Una vez a la semana: `scanner.py universo`.
2. Antes de la apertura: `scanner.py diario`. Dile al usuario los recuentos (recibidos, líquidos, escaneados,
   aciertos) y los primeros por regla.
3. Desde las 09:50 NY (10:15 es el clásico): `scanner.py orb`. Dile cuántos gráficos utilizables rompieron su rango
   y cuándo, y que un acierto tardío está más cerca del precio de ahora.
4. Si opera futuros: `scanner.py futuros` a partir del cierre del IB (10:30 en índices, 10:00 en CL, 09:20 en GC).
   Dile quién cerró fuera y a qué hora, quién está fuera del rango de ayer, y cómo va el rango del día frente a su
   medio.
5. El usuario elige un gráfico. Pásalo: kemet-noticias (qué lo mueve, y la agenda macro del día), después
   kemet-niveles y kemet-plan, y la entrada vela a vela con kemet-entrada. Nunca elijas por él.
6. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en su
   propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Con `--offline tests/fixtures/yahoo` (NQ y ES de 60 días, CL y GC de 5 días) a las 10:45 NY. El IB de NQ de 09:30 a
10:30 fue de 28.199 a 28.426 (227 puntos); la vela de 10:40 cerró en 28.429,75, por encima:

```
python3 scanner.py futuros --offline tests/fixtures/yahoo --ahora "2026-11-11 10:45"
Futuros, miércoles 11/11/2026, 16:45 Madrid / 10:45 NY · balance inicial de 60 minutos, máximo y mínimo de ayer, rango frente al medio de 20 sesiones (velas de 5 minutos de Yahoo, unos 10 minutos de retraso)
4 de 12 contratos con datos (8 sin datos: YM, RTY, SI, HG, NG, 6E, ZN, ZB). PARCIAL.
  ES   último 7.619,75 (10:45)   IB 7.593,25 a 7.624,75, 31,50 pts: sin cierre fuera
      ayer 7.493 a 7.566,25: por encima del máximo de ayer. Rango de hoy 31,50 pts, el 40 % del medio de 20 sesiones (78,76)
  NQ   último 28.429,75 (10:45)   IB 28.199 a 28.426, 227 pts: CIERRE POR ENCIMA a las 10:45 en 28.429,75
      ayer 27.516 a 28.090: por encima del máximo de ayer. Rango de hoy 245,25 pts, el 48 % del medio de 20 sesiones (514,15)
  CL   último 88,24 (10:45)   IB 86,93 a 87,72, 0,79 pts: CIERRE POR ENCIMA a las 10:20 en 88,10
      ayer 84,31 a 86,83: por encima del máximo de ayer. Rango de hoy 1,81 pts, el 75 % del medio de 2 sesiones (2,42)
  GC   último 4.013,10 (10:45)   IB 4.035,30 a 4.052,90, 17,60 pts: CIERRE POR DEBAJO a las 09:35 en 4.029
      ayer 4.020,80 a 4.090,50: por debajo del mínimo de ayer. Rango de hoy 44,50 pts, el 66 % del medio de 2 sesiones (67,55)
4 contratos cumplen una regla: ES por encima del máximo de ayer; NQ cierre por encima del balance inicial, por encima del máximo de ayer; CL cierre por encima del balance inicial, por encima del máximo de ayer; GC cierre por debajo del balance inicial, por debajo del mínimo de ayer.
Escrito kemet/watchlist.json (modo futuros, 4 aciertos).
```

Los cuatro índices abren a la vez, pero el crudo cerró fuera de su IB a las 10:20 (su IB va de 09:00 a 10:00) y el
oro a las 09:35 (el suyo, de 08:20 a 09:20). El rango de hoy de NQ, 245 puntos a las 10:45, es menos de la mitad de
su medio de 20 sesiones. En CL y GC el medio sale de 2 sesiones porque el fixture solo tiene 5 días; el tool lo dice
en la línea. Ocho contratos no tienen archivo en la carpeta: PARCIAL. Lo que pasó después con NQ lo cuentan
kemet-entrada y kemet-maquina; un día no dice nada de la regla.

## Ejemplo: acciones, lunes 19 de octubre de 2026

Escaneo a las 10:15 NY sobre una pared de 234 tickers (`tests/fixtures/kemet-scanner/wall5m-2026-10-19.json.gz`,
gráficos reales de Yahoo del pack de referencia):

```
python3 scanner.py orb --offline wall5m-2026-10-19.json.gz --ahora "2026-10-19 10:15" --min-precio 0
Ruptura del rango de apertura, lunes 19/10/2026, 10:15 NY · rango de 15 minutos (09:30 a 09:45), velas de 5 minutos de Yahoo
Recibidos 233 de 234 gráficos (1 fallaron o sin datos); 231 utilizables; 95 candidatos, 95 confirmados con máximos y mínimos reales.
42 de 231 gráficos cerraron por encima del máximo de su rango de apertura a las 10:15:
  09:50  AMC          2,97 $  rango 2,90 a 2,96  +0,50 % por encima
  09:50  CDNS       326,74 $  rango 321,58 a 324,80  +0,60 % por encima
  ...
  10:15  TSLA       364,18 $  rango 354,47 a 362,18  +0,55 % por encima
  ...
```

La pared no tenía suelo de precio (AMC a 2,97 $ es uno de los 42), de ahí `--min-precio 0`; con el suelo de 5 $ son
41. El rango de TSLA son las velas de 09:30 a 09:40, máximo 362,18 y mínimo 354,47; la vela de 10:10 cerró en
364,18, un 0,55 % por encima, a las 10:15. El usuario elige TSLA y Claude lo pasa a kemet-noticias y después a
kemet-entrada (`--mercado TSLA`, IB de 15 minutos).

El escaneo diario de esa mañana (cierres hasta el viernes 16, `daily-spark-2026-10-19.json`, 19 gráficos) marca BLK,
CI, XOM, HD y KO como ruptura de 20 días, CCL y RCL como bandera, F, JPM y GE recuperando la media de 20, BAC, MS,
RIVN y PLUG en sobreventa y PNC como rebote: 15 de 19 con `--min-precio 0 --min-volumen 0`; con los suelos por
defecto a las 10:50 (volumen del día a medias) quedan 7.

## Reglas

- Di qué se escaneó: cuántos símbolos, cuántos gráficos llegaron, cuántos valían y la hora de los datos.
- Di "cumple una regla", nunca "una compra", "un ganador" ni "una buena operación".
- Nunca se imprime un P&L, una rentabilidad ni una cifra de beneficio.
- Un acierto caduca en cuanto el precio se mueve. Vuelve a lanzar antes de actuar sobre él.
- Igual en acciones y en futuros: cada instrumento con su sesión regular y su calendario.

## Lo que nunca hace

Nunca pone, dimensiona ni comprueba una orden, nunca dice qué comprar, nunca llama a los datos "tiempo real" y nunca
promete que una regla funcione.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
