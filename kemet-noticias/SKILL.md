---
name: kemet-noticias
description: >-
  El monitor de noticias. Para cada acción de la watchlist lee los titulares
  de Yahoo Finance y los 8-K que la empresa presenta en EDGAR (resultados,
  cambios de directivos, acuerdos, reformulaciones, quiebra), dice cuánto se
  ha movido hoy frente al cierre de ayer y añade en la misma pantalla la
  agenda macro del día de kemet/agenda.json (IPC, FOMC, inventarios, con sus
  ventanas), para que un trader de futuros vea titulares y datos juntos.
  Enseña solo lo nuevo desde la última comprobación, lo más reciente primero,
  en hora de Nueva York, con etiquetas (resultados, guía, fusión, regulador,
  dirección, demanda, dividendo, parada, macro) y sin repetir nada. Úsala
  cuando el usuario diga "qué noticias hay de TSLA", "por qué se mueve",
  "noticias de mi watchlist", "resumen de la mañana", "noticias de
  premercado", "vigila las noticias", "ha salido algo", "mira los 8-K", "qué
  datos hay hoy", o después de kemet-scanner y antes de kemet-entrada.
argument-hint: "[--tickers TSLA,AAPL] [--horas 12] [--escribir] [--offline CARPETA]"
---

# kemet-noticias

Un gráfico puede estar perfecto y aun así abrir con hueco por unos resultados, una parada de cotización o una
demanda. Antes de que una regla se convierta en una operación, este tool lee las dos fuentes que lo cuentan primero
(los titulares y lo que la empresa le dice a la SEC) para cada acción de la watchlist, dice cuánto se ha movido hoy
y pone al lado la agenda macro del día, la misma que usa kemet-plan para abrir ventanas sin operar. Solo lee e
informa. La mayoría de los que hacen day trading pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde vive este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/noticias.py"                                  # los tickers de kemet/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --tickers TSLA,AAPL --horas 12
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --tickers TSLA --horas 72 --todo # todo lo de 3 días, visto o no
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --tickers TSLA --escribir        # y guarda kemet/noticias.json
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --sin-edgar --json               # solo titulares, documento completo
python3 "${CLAUDE_SKILL_DIR}/noticias.py" --tickers TSLA --horas 6 --ahora "2026-10-19 10:52" --offline tests/fixtures/kemet-noticias
```

Otros flags: `--formularios 8-K,10-Q` (más formularios de la SEC), `--sin-movimiento` (sin la línea de precio),
`--movimiento-pct 3` (desde qué movimiento se marca SE MUEVE), `--user-agent "Nombre correo@ejemplo.com"` (el de la
SEC, si no está en la configuración), `--sin-estado` (no apunta lo visto), `--ahora "AAAA-MM-DD HH:MM"` (hora de
Nueva York, fija el reloj y permite repetir un día). Código de salida 0 si hay algo nuevo, 1 si no, 2 ante un error.

## Qué lee y escribe

| archivo o fuente | qué |
| --- | --- |
| `--tickers`, si no `kemet/watchlist.json` | los aciertos del escáner (`aciertos[].simbolo`, solo acciones) y las posiciones de `kemet/portfolio.json` si existe |
| `kemet/agenda.json` | los datos macro del día (la escribe el usuario o `plan.py agenda`); solo si su `fecha` es hoy, con la ventana sin operar de cada dato (20 minutos a cada lado si es fuerte, 10 si no) |
| `kemet/config.json` | `sec_user_agent` ("Nombre correo@ejemplo.com"); también vale la variable `SEC_USER_AGENT` |
| RSS de Yahoo Finance | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=TSLA&region=US&lang=en-US` |
| gráfico de Yahoo Finance | el último precio frente al cierre de ayer (no oficial, con retraso) |
| Atom de EDGAR por empresa | 8-K por defecto; sin `sec_user_agent` se omite y lo dice en una línea, los titulares siguen |
| `kemet/estado/noticias.json` | lo ya enseñado (30 días) y el CIK de cada ticker |
| `kemet/noticias.json` | con `--escribir`: `generado`, `fuente`, `tickers`, `movimientos`, `agenda`, `items`, `notas` |

## Las reglas

- **Los titulares son pistas, no hechos.** Antes de contarle al usuario que algo ha pasado, abre la noticia o el
  filing y léelo. Cita la fuente y enlázala. Nunca resumas una noticia de pago que no pudiste leer: dilo.
- **Un filing manda sobre un titular.** Si un 8-K y un titular no coinciden, el 8-K es lo que la empresa le dijo a
  la SEC.
- **Di a quién toca.** Cada item lista los tickers que toca y sus etiquetas: resultados, guía, analista, demanda,
  fusión, dividendo, dirección, riesgo, parada, regulador, macro. Un filing con `!` lleva un punto importante del
  8-K: resultados (2.02), cambio de consejero o directivo (5.02), deterioro de activos (2.06), aviso de exclusión
  (3.01), cuentas pasadas no fiables (4.02), quiebra (1.03) o incidente de ciberseguridad (1.05).
- **SE MUEVE** marca una acción a un 3 % o más del cierre de ayer (`--movimiento-pct`). Un movimiento sin titular
  también se dice en voz alta.
- **La agenda es del día o no es.** Si `kemet/agenda.json` tiene otra fecha, el tool lo dice y no la enseña. Si no
  existe, lo dice: no conoce los datos del día. Los datos se escriben con `plan.py agenda`.
- **Sin predicciones.** Se cuenta lo publicado y a qué distancia está el precio del cierre de ayer. Nunca qué hará
  la acción después.

## Pasos

1. Lanza la comprobación: `noticias.py` (o con `--tickers`). Código 1 significa que no hay nada nuevo. `--todo`
   enseña lo ya visto, `--json` lo da todo legible por máquina, `--sin-estado` deja el archivo de lo visto como está.
2. Lee primero lo que importa: cada filing con `!`, lo etiquetado como resultados, parada, demanda, regulador o
   riesgo, cada ticker con SE MUEVE y el próximo dato fuerte de la agenda con su ventana.
3. Escribe un resumen corto por ticker: qué pasó, la fuente con enlace, el movimiento y una línea sobre por qué le
   importa a la regla (por ejemplo "presenta resultados esta semana: un hueco nocturno salta cualquier stop").
4. Si una noticia o un dato cambia el cuadro, dilo antes de kemet-entrada y kemet-salida: unos resultados dentro de
   la operación, una parada, una ampliación, un FOMC a las 14:00. Nunca se actúa por un titular.
5. Durante la sesión: `/loop 15m` con `noticias.py`, o una tarea programada cada mañana antes de la apertura.
6. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en su
   propio banco; no están en este pack. kemet-capital.com

## Ejemplo: TSLA, lunes 19 de octubre de 2026

TSLA cerró por encima de su rango de apertura a las 10:15 NY (kemet-scanner). La comprobación a las 10:52 con el
fixture real del pack de referencia (`tests/fixtures/kemet-noticias`: el RSS de Yahoo Finance de TSLA de esa mañana,
18 titulares, y el gráfico bajado a las 10:52):

```
python3 noticias.py --tickers TSLA --horas 6 --ahora "2026-10-19 10:52" --offline tests/fixtures/kemet-noticias
Noticias de TSLA, lunes 19/10/2026, 16:52 Madrid / 10:52 NY · últimas 6 horas, titulares de Yahoo Finance, 8-K de EDGAR y movimiento de hoy
Movimiento de hoy frente al cierre de ayer:
  TSLA   366,48 $  +3,31 % (cierre de ayer 354,72 $, a las 10:52 NY)  SE MUEVE
Lo nuevo, lo más reciente primero:
  19/10/2026 10:32  TSLA        Yahoo Finance What to say to the skeptics during Elon Musk's five-day run
      https://finance.yahoo.com/video/what-to-say-to-the-skeptics-during-elon-musks-five-day-run-143217090.html?.tsrc=rss
  ...
  19/10/2026 08:04  TSLA        Yahoo Finance Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings
      etiquetas: resultados, fusión  https://finance.yahoo.com/m/24874872-02fc-312d-ab0a-030d5dafda4f/tesla-spacex-merger-mania.html?.tsrc=rss
  19/10/2026 08:02  TSLA        Yahoo Finance Tech Stock Rebound Nudges US Equity Futures Mostly Higher Pre-Bell
      etiquetas: macro  https://finance.yahoo.com/markets/stocks/articles/tech-stock-rebound-nudges-us-120243477.html?.tsrc=rss
  19/10/2026 08:00  TSLA        Yahoo Finance Meta and Musk earnings and September pending home sales: What to Watch
      etiquetas: resultados  https://finance.yahoo.com/video/meta-musk-earnings-september-pending-120000067.html?.tsrc=rss
Nota: sin kemet/agenda.json: no conozco los datos macro de hoy (escríbela con `plan.py agenda`)
Nota: sin CIK en la SEC para TSLA
Comprobado a las 10:52 NY. Los titulares son pistas, no hechos: abre la noticia antes de actuar. No es asesoramiento financiero.
```

El resumen: "Tesla presenta resultados esta semana, así que la acción puede abrir con hueco; la operación de hoy
entra y sale antes del cierre. Va un 3,31 % arriba. Sin 8-K nuevo (el fixture de la SEC no trae el CIK de TSLA; en
vivo sí)". Con `--ahora "2026-10-19 10:15"` salen 16 titulares: los dos de las 10:32 aún no existían, y el tool no
enseña nada publicado después del reloj fijado. La segunda pasada a la misma hora dice `Nada nuevo en las últimas 6
horas.` y termina con código 1.

Con una agenda del día en `kemet/agenda.json` (`plan.py agenda --fecha 2026-10-19 --dato "08:30 Peticiones de
desempleo" --dato "10:30 Inventarios EIA CL" --dato "14:00 FOMC fuerte"`), la misma comprobación a las 10:15 añade:

```
Agenda macro de hoy (kemet/agenda.json), hora de Nueva York:
  08:30  Peticiones de desempleo                    ventana sin operar 08:20 a 08:40  (pasado)
  10:30  Inventarios EIA              solo CL       ventana sin operar 10:20 a 10:40  (dentro de 15 min)
  14:00  FOMC                         fuerte        ventana sin operar 13:40 a 14:20  (dentro de 3 h 45 min)
```

Un 8-K importante se ve así (AAPL, `--horas 2400 --ahora "2026-10-14 00:00"`):

```
! 30/07/2026 16:30  AAPL        EDGAR         Apple Inc. presentó un 8-K: resultados
      etiquetas: resultados  https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/0000320193-26-000018-index.htm
```

Cuando un ticker no tiene noticias, dilo en vez de rellenar el resumen.

## Reglas

- Una petición por fuente y ticker, con una pausa entre llamadas; muy lejos del límite de 10 peticiones por segundo
  de la SEC.
- Las horas se imprimen en hora de Nueva York, con Madrid en la cabecera.
- Lo visto se recuerda 30 días en `kemet/estado/noticias.json`: una noticia sale una vez, salvo con `--todo`.
- Los futuros no tienen titulares por ticker: para NQ o CL mira la agenda macro aquí y los niveles en kemet-niveles.

## Lo que nunca hace

- Nunca inventa ni adorna una noticia, una cita o una cifra.
- Nunca opera por una noticia, y nunca le dice al usuario que compre o venda por un titular.
- Nunca machaca un servidor ni usa una clave: Yahoo y EDGAR son públicos; el User-Agent de la SEC es tu nombre y tu
  correo, nada más.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
