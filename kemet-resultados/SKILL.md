---
name: kemet-resultados
description: >-
  Los resultados que una empresa de EE. UU. presentó de verdad en la SEC, trimestre a trimestre y en español:
  ingresos, márgenes bruto, operativo y neto, beneficio neto, BPA diluido y flujo de caja operativo si la empresa lo
  etiqueta, cada trimestre frente al mismo trimestre del año anterior, los últimos cuatro sumados, el cuarto
  trimestre derivado del 10-K y marcado como tal. Lee los hechos XBRL de EDGAR (companyfacts), el último 10-Q o 10-K,
  el último 8-K de resultados con su nota de prensa y estima cuándo toca el próximo informe. Cifras en formato
  español, millones con M. Escribe kemet/resultados.json y una fila por empresa en un JSON de métricas. Nunca dice
  si la acción es compra o venta. Úsala cuando el usuario diga «qué tal los resultados de Tesla», «cuánto creció
  Apple», «está ganando dinero esta empresa», «mira el 10-Q», «compárame los márgenes», «cuándo presenta
  resultados», «hay resultados esta semana», o antes de operar una acción cerca de su informe. Va después de
  kemet-scanner o de que el usuario nombre un ticker, y antes de kemet-entrada y kemet-salida, que necesitan saber si
  el próximo informe cae dentro de la operación.
argument-hint: "TSLA [AAPL ...] [--trimestres 8] [--metricas kemet/metricas.json] [--escribir]"
---

# kemet-resultados

Los resultados mueven una acción más que cualquier otra cosa del calendario, y la nota de prensa está escrita
para poner delante el número que mejor queda. Esta skill lee lo que la empresa presentó en la SEC, lo pone en
fila trimestre a trimestre y dice en llano qué cambió. Para quien hace day trading responde dos preguntas antes
de entrar: qué dijo el último informe y si el próximo cae dentro de la operación. La mayoría de los que hacen day
trading pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/resultados.py" TSLA                                    # los últimos 6 trimestres
python3 "${CLAUDE_SKILL_DIR}/resultados.py" AAPL KO --trimestres 8                  # dos años, varias empresas
python3 "${CLAUDE_SKILL_DIR}/resultados.py" TSLA --escribir                         # y guarda kemet/resultados.json
python3 "${CLAUDE_SKILL_DIR}/resultados.py" TSLA NVDA AMD --metricas kemet/metricas.json   # una fila por empresa
python3 "${CLAUDE_SKILL_DIR}/resultados.py" --cik 1318605                           # una empresa por su CIK
python3 "${CLAUDE_SKILL_DIR}/resultados.py" AAPL --json
```

Flags: `--trimestres N` (6 por defecto), `--sin-informes` (solo la tabla, sin 10-Q, 8-K ni próximo informe),
`--metricas ARCHIVO`, `--escribir`, `--json`, `--ahora "AAAA-MM-DD HH:MM"` en hora de Nueva York (fija el reloj
para repetir un día), `--offline CARPETA` (los JSON de EDGAR guardados; los tests usan
`tests/fixtures/kemet-resultados`), `--user-agent`. `KEMET_DIR` cambia la carpeta `kemet/`. Código de salida 0
si salió todo, 1 si alguna empresa falló y otra no, 2 si hay un error (una línea, sin traza).

EDGAR exige un User-Agent con tu nombre y correo. Se toma de `sec_user_agent` en `kemet/config.json` (lo deja
`tamano.py config`), de la variable `SEC_USER_AGENT` o de `--user-agent`; sin él, la herramienta lo pide en una
línea y para. No se llama a la SEC sin él y nunca se pasa de 10 peticiones por segundo.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `https://www.sec.gov/files/company_tickers.json` | el CIK de cada ticker (los ETF y muchas empresas extranjeras no están) |
| `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | todos los números que la empresa etiquetó en sus 10-Q y 10-K |
| `https://data.sec.gov/submissions/CIK##########.json` | la lista de presentaciones: el último 10-Q o 10-K, el último 8-K con el punto 2.02 (resultados) y la carpeta de ese 8-K para la nota de prensa (anexo EX-99.1) |
| `kemet/config.json` | solo `sec_user_agent` (kemet-tamano) |
| `kemet/resultados.json` | con `--escribir`: `generado`, `fuente`, `empresas[]` con `ticker`, `resultado` (entidad, cik, trimestres, ultimos_4, conceptos), `informes`, `proximo`, `cambios`, `aviso` |
| el JSON de `--metricas` | una fila por empresa: `ticker`, `nombre`, `cik`, `fin_periodo`, `ingresos_12m`, `beneficio_neto_12m`, `bpa_12m`, `flujo_caja_operativo_12m`, `ingresos_interanual`, `bpa_interanual`, `beneficio_neto_interanual`, `margen_bruto`, `margen_operativo`, `margen_neto`, `fuente`. Se añade o se actualiza la fila; `metricas.example.json` en esta carpeta es una pasada real (AAPL, AXP, BAC, GOOGL y KO el 2026-10-13) |

## Las reglas

- **Primero lo presentado.** La tabla sale de los hechos XBRL que la empresa firmó. La nota de prensa sirve
  para el contexto (guía, segmentos) y se dice qué número viene de dónde.
- **Se compara con lo comparable.** El crecimiento es frente al mismo trimestre del año anterior. El cambio
  frente al trimestre anterior se enseña, pero muchos negocios son estacionales (el trimestre de diciembre de
  Apple es siempre el mayor).
- **Se dice lo que es derivado.** No hay 10-Q del cuarto trimestre: es el año del 10-K menos los tres
  trimestres de dentro, y va marcado «derivado». Su BPA es aproximado porque el número de acciones cambia.
- **Manda la reexpresión, la etiqueta es la primera.** Si un periodo se presentó dos veces, el valor es el de la
  presentación más reciente; el nombre fiscal (T1 2026) es el de la primera que lo presentó.
- **Se avisa cuando los datos van tarde.** La API de hechos de la SEC puede ir por detrás de una presentación.
  Si el último 10-Q es posterior al último trimestre de la tabla, sale un AVISO con el enlace: se lee el 10-Q
  antes de resumir.
- **Se señalan las partidas raras.** Si el beneficio neto supera el resultado operativo, dentro hay ganancias
  ajenas al negocio (inversiones, impuestos); si el flujo de caja operativo va por debajo del beneficio, el
  beneficio no se está convirtiendo en caja. Bancos y aseguradoras no tienen margen bruto: en blanco, no cero.
- **El próximo informe es una estimación.** La SEC no publica el calendario. Si en la lista está el mismo
  informe del año pasado, su fecha más 52 semanas; si no, unos 91 días después del último. Siempre se dice que es
  una estimación y que se confirma en la web de relación con inversores (o en los titulares de kemet-noticias).

## Pasos

1. Comprueba que hay `sec_user_agent` en `kemet/config.json` (o `SEC_USER_AGENT`). Si no, pide al usuario su
   nombre y un correo suyo y apúntalo con `tamano.py config` o en la variable; no inventes uno.
2. Ejecuta la herramienta para la empresa (o para los tickers de `kemet/watchlist.json` si viene de
   kemet-scanner). Con `--trimestres 8` se ven dos años; con `--metricas` queda una fila por empresa para sus
   notas.
3. Si hay AVISO de datos atrasados o la pregunta necesita contexto, abre la nota de prensa (el enlace EX-99) o el
   10-Q y léelos.
4. Escribe el resumen: una línea del trimestre (ingresos, BPA, crecimiento interanual), una de márgenes, una de
   lo raro (una partida ajena, un trimestre derivado, datos que van tarde) y los enlaces. Palabras llanas, cifras
   reales, ningún adjetivo que los números no sostengan.
5. Si el próximo informe cae dentro de la operación que el usuario planea (una posición que se queda abierta de
   un día para otro, o un informe antes de la apertura), dilo antes de que kemet-salida ponga el stop: un stop no
   protege de un hueco, la acción puede abrir más allá. Un day trade que cierra antes de la campana no está
   expuesto; lo que se queda abierto, sí.
6. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros validados en
   su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: Apple, ocho trimestres, miércoles 11 de noviembre de 2026

Sobre los datos de EDGAR guardados en `tests/fixtures/kemet-resultados` (reales, leídos en octubre de 2026):

```
$ python3 resultados.py AAPL --trimestres 8 --offline tests/fixtures/kemet-resultados --ahora "2026-11-11 16:30"
RESULTADOS AAPL, Apple Inc., CIK 0000320193 · 22:30 Madrid / 16:30 NY
Fuente: SEC EDGAR, XBRL companyfacts y submissions. Millones de dólares salvo el BPA. Interanual: frente al mismo trimestre del año anterior.

trimestre   fiscal       ingresos interanual  m.bruto  m.oper.   m.neto  beneficio BPA dil. interanual
2026-06-27  T3 2026       109.417    +16,4 %   50,1 %   32,6 %   27,2 %     29.789     2,02    +28,7 %
2026-03-28  T2 2026       111.184    +16,6 %   49,3 %   32,3 %   26,6 %     29.578     2,01    +21,8 %
2025-12-27  T1 2026       143.756    +15,7 %   48,2 %   35,4 %   29,3 %     42.097     2,84    +18,3 %
2025-09-27  T4 2025       102.466     +7,9 %   47,2 %   31,6 %   26,8 %     27.466     1,84    +89,7 %  derivado
2025-06-28  T3 2025        94.036     +9,6 %   46,5 %   30,0 %   24,9 %     23.434     1,57    +12,1 %
2025-03-29  T2 2025        95.359     +5,1 %   47,1 %   31,0 %   26,0 %     24.780     1,65     +7,8 %
2024-12-28  T1 2025       124.300     +4,0 %   46,9 %   34,5 %   29,2 %     36.330     2,40    +10,1 %
2024-09-28  T4 2024        94.930          -   46,2 %   31,2 %   15,5 %     14.736     0,97          -  derivado

Últimos cuatro trimestres: ingresos 466.823 M$, beneficio neto 128.930 M$, BPA diluido 8,71 $.

Qué cambió:
  - Trimestre cerrado el 2026-06-27 (T3 2026): ingresos 109.417 M$ (+16,4 % interanual), beneficio neto 29.789 M$ (+27,1 %), BPA diluido 2,02 $ (+28,7 %).
  - Margen bruto 50,1 % (+0,8 puntos frente al trimestre anterior).
  - Margen operativo 32,6 % (+0,3 puntos frente al trimestre anterior).
  - Margen neto 27,2 % (+0,6 puntos frente al trimestre anterior).
  - Ingresos -1,6 % frente al trimestre anterior (muchos negocios son estacionales: compara primero con el mismo trimestre del año pasado).

Último 10-Q: periodo 2026-06-27, presentado el 2026-07-31  https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/aapl-20260627.htm
Último 8-K de resultados (punto 2.02): presentado el 2026-07-30  https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/a8-kex991q3202606272026.htm
Próximo informe: por el calendario tocaba un 10-K hacia el 2026-10-30 (unos 91 días después del último 10-Q, presentado el 2026-07-31); han pasado 12 días y no aparece en la lista leída. Confírmalo en la web de relación con inversores de la empresa.

Los trimestres derivados son el año del 10-K menos los tres 10-Q; su BPA es aproximado.
```

El T4 2025 derivado: ejercicio 416.161 menos 124.300, 95.359 y 94.036 = 102.466 M$. El 11 de noviembre la
estimación del 10-K ya había pasado y la lista guardada no lo trae: en vivo, con la lista completa de EDGAR, ese
10-K aparecería como último informe y el próximo sería el 10-Q de enero. Con Coca-Cola (`resultados.py KO`) sale
el AVISO: los hechos XBRL llegan hasta el 2026-04-03 y el 10-Q del 2026-07-03 ya estaba presentado, así que se lee
ese 10-Q directamente.

## Reglas

- Números presentados, no estimaciones de analistas ni titulares.
- Interanual antes que intertrimestral.
- Derivado, reexpresado, atrasado: siempre dicho.
- El próximo informe es una estimación hasta que lo confirme la empresa.
- Si el informe cae dentro de la operación, se dice antes del stop.

## Lo que nunca hace

No dice que una acción esté barata o cara, ni que sea compra o venta. No inventa un número que las
presentaciones no tengan ni estima un trimestre que no pueda derivar. No llama a la SEC sin User-Agent. No baja
transcripciones de conferencias: si el usuario pega una, se lee y se resume qué dijo la dirección que cambió
(guía, márgenes, demanda, lo que no quisieron contestar).

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
