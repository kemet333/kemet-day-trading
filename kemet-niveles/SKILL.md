---
name: kemet-niveles
description: >-
  Niveles de sesión de futuros (ES, NQ, CL, GC) y de acciones de EE. UU. (TSLA, cualquier ticker) con velas de
  5 minutos gratis de Yahoo, sin clave. Calcula lo que un trader intradía marca antes de abrir: máximo, mínimo
  y cierre de la sesión regular anterior (PDH, PDL, PDC), rango nocturno desde las 18:00 de Nueva York (ONH,
  ONL), apertura de 15 minutos (ORH, ORL), balance inicial de la primera hora (IBH, IBL, solo cuando ya
  cerró), máximo y mínimo de hoy, el rango medio de las últimas 20 sesiones y dónde está el último precio
  respecto a cada nivel. En una acción no hay noche y el balance inicial es de 15 minutos, al céntimo.
  Niveles, no señales: sin dirección ni objetivos. Úsala cuando el usuario diga «qué niveles marco», «dame el
  máximo y el mínimo de ayer», «dónde cerró el NQ», «rango nocturno», «cuál es el balance inicial», «dónde
  está el precio respecto a ayer», «niveles de TSLA», o al empezar el día antes de kemet-plan.
argument-hint: "[--mercado ES|NQ|CL|GC|TSLA] [--ib-minutos 60|15] [--todos] [--escribir] [--ahora \"AAAA-MM-DD HH:MM\"]"
---

# kemet-niveles

Los niveles son la parte del plan que no admite opinión: dónde cerró ayer, hasta dónde fue la noche, qué hizo la
primera hora. Este tool los saca de velas de 5 minutos de Yahoo (gratis, unos 10 minutos de retraso en futuros), los
imprime en una pantalla y dice si el último precio está por encima o por debajo de cada uno. No dice hacia dónde va
el precio ni qué hacer con los niveles.
La mayoría de los que hacen day trading pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/niveles.py"                              # el mercado de kemet/config.json (NQ si no hay)
python3 "${CLAUDE_SKILL_DIR}/niveles.py" --mercado ES --escribir      # ES y guarda kemet/niveles.json
python3 "${CLAUDE_SKILL_DIR}/niveles.py" --todos                      # ES, NQ, CL y GC seguidos
python3 "${CLAUDE_SKILL_DIR}/niveles.py" --json                       # el documento completo
python3 "${CLAUDE_SKILL_DIR}/niveles.py" --ahora "2026-11-11 16:30" --offline tests/fixtures/yahoo   # repetir un día
python3 "${CLAUDE_SKILL_DIR}/niveles.py" --mercado TSLA                # una acción: sin noche, apertura y balance inicial de 15 minutos
```

Flags: `--mercado` o `--simbolo` (un futuro: ES, NQ, CL, GC, o un ticker de acciones de EE. UU.: TSLA), `--ib-minutos
15|30|60` (60 en futuros, 15 en acciones), `--todos`, `--escribir`, `--json`, `--ahora "AAAA-MM-DD HH:MM"` en hora de
Nueva York para fijar el reloj, `--offline RUTA` para leer un JSON de Yahoo guardado (`.json` o `.json.gz`, o la
carpeta `tests/fixtures/yahoo`). `KEMET_DIR` cambia la carpeta `kemet/`. Código de salida 0 si hay niveles, 1 si no
hay sesión anterior en los datos, 2 si hay un error (una línea, sin traza).

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/config.json` | opcional: `mercado` por defecto. Sin él, NQ |
| Yahoo, gráfico v8 | `range=60d&interval=5m` del contrato continuo (`NQ=F`), una petición por contrato: gratis, sin clave, unos 10 minutos de retraso; 60 días porque el rango medio usa 20 sesiones |
| `kemet/niveles.json` | con `--escribir`: `generado`, `mercado`, `instrumento` (futuro o accion), `fecha`, `sesion` (rth, nocturna, cerrado), `ultimo`, `pdh`, `pdl`, `pdc`, `onh`, `onl`, `orh`, `orl`, `ibh`, `ibl`, `ib_minutos`, `tdh`, `tdl`, `rango_medio_20`, `posicion`. Las claves que aún no existen no aparecen; en una acción `onh` y `onl` no existen nunca |
| `kemet/niveles-ES.json` (y CL, GC) | con `--todos --escribir`: los demás contratos, uno por archivo; `niveles.json` es el del mercado principal |

kemet-plan lee `niveles.json` si es de hoy y de su mercado; kemet-entrada usa el mismo balance inicial.

## Las reglas

- **El día de negociación** de CME empieza a las 18:00 de Nueva York de la víspera. La vela de las 19:00 del martes
  es ya del miércoles. Todas las horas son de Nueva York; la cabecera lleva también la de Madrid.
- **Sesión regular** por contrato: ES y NQ 09:30 a 16:00, CL 09:00 a 14:30, GC 08:20 a 13:30. En los días recortados
  de CME (víspera de Thanksgiving, Nochebuena) los índices cierran a las 13:00.
- **Ayer (PDH, PDL, PDC)**: máximo, mínimo y cierre de la última sesión regular completa anterior a hoy. El cierre es
  el de la última vela de 5 minutos de la sesión, que hace de liquidación. Si en los datos esa sesión está incompleta,
  lo dice.
- **Noche (ONH, ONL)**: máximo y mínimo de las velas desde las 18:00 hasta la apertura de la sesión regular. Antes de
  la apertura sigue creciendo; después queda fijo.
- **Apertura (ORH, ORL)**: los primeros 15 minutos de la sesión regular (tres velas). Solo cuando los 15 minutos han
  cerrado; antes dice que se está formando.
- **Balance inicial (IBH, IBL)**: la primera hora de la sesión regular (doce velas). Solo cuando la hora ha cerrado,
  es decir, a partir de las 10:30 en índices. Imprime también el ancho en puntos.
- **Hoy (TDH, TDL)**: máximo y mínimo de la sesión regular en curso.
- **Rango medio de sesión** (`rango_medio_20`): media de máximo menos mínimo de las últimas 20 sesiones regulares
  completas anteriores a hoy (una sesión con huecos en los datos no cuenta; con menos de 20 dice cuántas usa). Es
  contexto para dimensionar un stop: un stop de 10 puntos en un contrato que se mueve 500 al día es ruido. No es un
  filtro ni decide si se opera.
- **Último**: el cierre de la última vela cerrada, no la cinta. Con el retraso de Yahoo, el último precio que ves tiene
  unos 10 minutos.
- **Acciones de EE. UU.** (`--mercado TSLA`): el día es la fecha de Nueva York y no hay sesión nocturna, así que no
  hay ONH ni ONL y no se inventan con el premercado. Sesión regular de 09:30 a 16:00 (13:00 en los días recortados de
  la NYSE). Apertura y balance inicial son los dos de 15 minutos por defecto, así que coinciden; `--ib-minutos 30`
  o `60` separa el IB. Niveles al céntimo, rango medio en dólares por acción. Fin de semana y festivos de la NYSE:
  mercado cerrado.
- **Posición**: por encima, por debajo o justo en cada nivel, comparando el último con el nivel.
- Solo velas cerradas (inicio más 5 minutos antes del reloj). Una vela fuera de la rejilla de 5 minutos (el tick en
  vivo de Yahoo) se descarta.
- Fin de semana y festivos: dice que el mercado está cerrado y da los niveles de la última sesión igualmente.

## Pasos

1. Pregunta el mercado si el usuario no lo dice y no hay `kemet/config.json`. Si opera varios, `--todos`.
2. Ejecuta `niveles.py --escribir`. Cuenta al usuario la hora de los datos y el retraso.
3. Dile en una o dos frases dónde está el precio respecto a ayer y a la noche, con las cifras. Nada más: ni «va a
   romper», ni «rebotará», ni «soporte fuerte».
4. Pásalo a `/kemet-plan` para escribir el plan de la sesión con esos niveles. Si el usuario quiere seguir la ruptura
   del balance inicial vela a vela, `/kemet-entrada`.
5. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en su
   propio banco; no están en este pack. kemet-capital.com

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

Con el fixture real de Yahoo del pack (`tests/fixtures/yahoo`, 49 sesiones de NQ), a las 16:30 de Nueva York:

```
python3 niveles.py --ahora "2026-11-11 16:30" --offline tests/fixtures/yahoo
NQ · mié 2026-11-11 · 22:30 Madrid / 16:30 NY · velas de 5 min de Yahoo (gratis, ~10 min de retraso) · sesión regular cerrada
Último 28.457,25 (cierre de la vela de las 16:30 NY)
  Ayer (sesión regular 2026-11-10)   máximo 28.090   mínimo 27.516   cierre 27.835,25
  Noche (desde 18:00 NY)             máximo 28.406,25   mínimo 27.847,75
  Apertura 15 min                    máximo 28.426   mínimo 28.254,25
  Balance inicial 1 h                máximo 28.426   mínimo 28.199   ancho 227 (12 velas)
  Hoy (sesión regular)               máximo 28.697   mínimo 28.199
  Rango medio de sesión              514,15 puntos (media de máximo menos mínimo de las últimas 20 sesiones, para dimensionar el stop)
El precio está por encima del máximo de ayer, del mínimo de ayer, del cierre de ayer, del máximo nocturno, del mínimo nocturno, del máximo de la apertura, del mínimo de la apertura, del máximo del IB, del mínimo del IB, del mínimo de hoy; por debajo del máximo de hoy.
```

Lo que se lee ahí: el martes 10 cerró en 27.835,25 con un rango de 574 puntos (algo más que los 514 de media de las
últimas 20 sesiones); la noche subió hasta 28.406,25, por encima del máximo de ayer; la primera hora del miércoles fue
de 28.199 a 28.426 (227 puntos) y el máximo de la apertura coincidió con el del balance inicial; la sesión llegó a
28.697 y el último precio está dentro del rango de hoy, por encima de todo lo demás.

La misma mañana a las 03:00 de Nueva York (09:00 en Madrid) solo hay noche, y lo dice:

```
python3 niveles.py --ahora "2026-11-11 03:00" --offline tests/fixtures/yahoo
NQ · mié 2026-11-11 · 09:00 Madrid / 03:00 NY · velas de 5 min de Yahoo (gratis, ~10 min de retraso) · sesión nocturna
Último 28.240,25 (cierre de la vela de las 03:00 NY)
  Ayer (sesión regular 2026-11-10)   máximo 28.090   mínimo 27.516   cierre 27.835,25
  Noche (desde 18:00 NY)             máximo 28.280   mínimo 27.847,75
  Apertura 15 min                    a las 09:45 NY
  Balance inicial 1 h                a las 10:30 NY
  Hoy (sesión regular)               sin sesión regular todavía
  Rango medio de sesión              514,15 puntos (media de máximo menos mínimo de las últimas 20 sesiones, para dimensionar el stop)
El precio está por encima del máximo de ayer, del mínimo de ayer, del cierre de ayer, del mínimo nocturno; por debajo del máximo nocturno.
```

A las 10:00 la apertura ya está y el balance inicial «formándose, cierra a las 10:30». Con `--todos` a las 16:30
salen también ES (balance inicial 7.593,25 a 7.624,75, rango medio 78,76), CL (86,93 a 87,72, pit de 09:00 a 14:30)
y GC (4.035,30 a 4.052,90, pit de 08:20 a 13:30); en CL y GC el rango medio sale sobre las 2 sesiones que tiene el
fixture, y lo dice.

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026

Una acción, con el fixture real `TSLA-60d-5m.json.gz` (60 sesiones), a las 16:30 de Nueva York:

```
python3 niveles.py --mercado TSLA --ahora "2026-11-11 16:30" --offline tests/fixtures/yahoo
TSLA · mié 2026-11-11 · 22:30 Madrid / 16:30 NY · velas de 5 min de Yahoo (gratis, pueden ir con retraso) · sesión regular cerrada
Último 390,80 (cierre de la vela de las 16:00 NY)
  Ayer (sesión regular 2026-11-10)   máximo 380   mínimo 370,43   cierre 379,80
  Apertura 15 min                    máximo 392,67   mínimo 386,35
  Balance inicial 15 min             máximo 392,67   mínimo 386,35   ancho 6,32 (3 velas)
  Hoy (sesión regular)               máximo 395,43   mínimo 386,35
  Rango medio de sesión              13,11 $ por acción (media de máximo menos mínimo de las últimas 20 sesiones, para dimensionar el stop)
El precio está por encima del máximo de ayer, del mínimo de ayer, del cierre de ayer, del mínimo de la apertura, del mínimo del IB, del mínimo de hoy; por debajo del máximo de la apertura, del máximo del IB, del máximo de hoy.
```

Lo que se lee ahí: el martes 10 cerró en 379,80 y el miércoles abrió con hueco, 6,55 $ por encima del máximo de ayer
(386,35 fue el mínimo del día, en la primera vela); los primeros 15 minutos fueron de 386,35 a 392,67 (6,32 $, la
mitad del rango medio de 13,11 $ de una sesión entera); la sesión llegó a 395,43 y cerró en 390,80, dentro del rango
de la apertura. No hay línea de noche: una acción no la tiene.

A las 08:00 de Nueva York (14:00 en Madrid) solo está ayer, y lo dice: «antes de la apertura (09:30 NY)», apertura y
balance inicial «a las 09:45 NY». A las 09:40 los dos están «formándose, cierra a las 09:45» y ya hay máximo y mínimo
de hoy.

## Reglas

- Di siempre la hora de la última vela y que los datos llevan unos 10 minutos de retraso.
- Un nivel es un precio que ya pasó. No lo llames soporte, resistencia, objetivo ni zona de compra.
- El balance inicial no existe hasta las 10:30 (índices; 09:45 en una acción). Antes no lo inventes con menos velas.
- Una acción no tiene niveles nocturnos. No los saques del premercado ni de otra fuente.
- Si el tool dice que la sesión anterior está incompleta en los datos, avisa de que PDH, PDL y PDC pueden cambiar.
- Repite el tool antes de usar los niveles de hoy: el máximo y el mínimo de hoy se mueven.

## Lo que nunca hace

No predice, no da dirección, no calcula objetivos ni stops, no filtra días buenos y malos, no manda órdenes y no
llama «en tiempo real» a unas velas que van con retraso.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
