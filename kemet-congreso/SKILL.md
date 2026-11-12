---
name: kemet-congreso
description: >-
  Las operaciones en bolsa que los miembros de la Cámara de Representantes de EE. UU. están obligados a declarar
  por la STOCK Act, leídas del House Clerk y en español: el índice anual de declaraciones, los PTR (Periodic
  Transaction Reports) de un miembro, los presentados en los últimos días marcando los que no habías visto, y cada
  PTR convertido en filas (quién, titular, activo, ticker, compra o venta, opciones con strike y vencimiento, fecha
  de la operación, rango de importe y cuántos días tardó en declararse). Señala los tickers de tu watchlist o de
  tu cartera. Escribe kemet/congreso.json. Son declaraciones públicas con hasta 45 días de retraso, no información
  privilegiada: es un gancho para mirar un gráfico, no una estrategia. Úsala cuando el usuario diga «qué está
  comprando Pelosi», «operaciones del Congreso», «qué declaran los políticos», «ha comprado algún congresista
  X», «avísame cuando Pelosi presente algo», «lee este PTR». Va antes de kemet-scanner y kemet-entrada, que
  deciden si hay operación hoy; nunca sustituye a ninguna de las dos.
argument-hint: "index --miembro pelosi [--anio 2026] | recientes --dias 45 [--miembro pelosi] [--leer] | ptr DOC_ID | texto ptr.txt"
---

# kemet-congreso

Los miembros del Congreso tienen que declarar sus operaciones en bolsa, las de su cónyuge y las de sus hijos a
cargo. El House Clerk publica cada declaración en PDF y las lista todas en un índice por año. Esta skill lee ese
índice, ve cuándo aparece un PTR nuevo y lo convierte en filas que se entienden. Es rápida, no es temprana: un
PTR se presenta hasta 45 días después de la operación, así que cuando se puede leer ya tiene días o semanas. No
hay información privilegiada aquí; solo papeles públicos leídos deprisa. La mayoría de los que hacen day trading
pierde dinero, y una herramienta no cambia eso.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md). Herramienta en Python estándar;
`pdftotext` (poppler) es opcional, para sacar las filas de los PDF en local.

```bash
python3 "${CLAUDE_SKILL_DIR}/congreso.py" index --miembro pelosi                     # los PTR de este año de un miembro
python3 "${CLAUDE_SKILL_DIR}/congreso.py" index --anio 2026 --desde 2026-10-01       # todos los PTR desde una fecha
python3 "${CLAUDE_SKILL_DIR}/congreso.py" index --miembro "Josh Gottheimer" --tipo ""  # todas las declaraciones, no solo PTR
python3 "${CLAUDE_SKILL_DIR}/congreso.py" recientes --dias 45 --miembro pelosi --escribir   # los últimos 45 días, marca los nuevos
python3 "${CLAUDE_SKILL_DIR}/congreso.py" recientes --dias 7 --leer                  # y lee cada PTR (necesita pdftotext)
python3 "${CLAUDE_SKILL_DIR}/congreso.py" ptr 20035143                               # baja un PTR y lo lee
python3 "${CLAUDE_SKILL_DIR}/congreso.py" texto ptr.txt --presentado 2026-08-21      # filas desde el texto de pdftotext -layout
```

`--miembro` admite el apellido, «Nombre Apellido» o «Apellido, Nombre» y se puede repetir. `--tickers` señala
operaciones en esos tickers (además de los de `kemet/watchlist.json` y `kemet/portfolio.json`). `--ahora
"AAAA-MM-DD HH:MM"` en hora de Nueva York fija el reloj y el año por defecto. `--offline RUTA` lee un
`<AÑO>FD.zip` guardado o una carpeta con él y con textos `ptr-<DocID>.txt` (los tests usan
`tests/fixtures/kemet-congreso`). `--escribir` guarda `kemet/congreso.json`. `--json` imprime el documento.
`KEMET_DIR` cambia la carpeta `kemet/`. Código de salida 0 si hay algo que enseñar, 1 si no hay nada, 2 si hay
un error (una línea, sin traza).

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<AÑO>FD.zip` | el índice del año: un `<Member>` por declaración (nombre, distrito, tipo, fecha, DocID). El Clerk lo rehace una vez al día |
| `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<AÑO>/<DocID>.pdf` | cada PTR; se guarda en `kemet/estado/ptr/<DocID>.pdf` |
| `kemet/config.json` | `sec_user_agent` si lo hay, como identificación en las peticiones (kemet-tamano) |
| `kemet/watchlist.json`, `kemet/portfolio.json` | los tickers que se señalan: `aciertos[].simbolo` (kemet-scanner) y `posiciones[].simbolo` (kemet-broker) |
| `kemet/estado/congreso.json` | con `recientes --escribir`: los DocID ya enseñados (`vistos`) y `ultima_comprobacion`, para que cada PTR salga como nuevo una sola vez |
| `kemet/congreso.json` | con `--escribir`: `generado`, `fuente`, `comando`, `anio`, `miembros`, `declaraciones[]` (las filas del índice), `nuevas[]`, `informes[]` (cada PTR leído con sus `operaciones[]`) |

Cada operación de un PTR: `titular` (SP cónyuge, JT cuenta conjunta, DC hijo a cargo, vacío el propio miembro),
`activo`, `ticker`, `tipo_activo` (ST acciones, OP opciones, AB otros), `tipo` (P compra, S venta, S (partial)
venta parcial, E canje), `fecha`, `notificado`, `importe` (el rango en formato español), `importe_min`,
`importe_max`, `importe_original`, `descripcion`, `cuenta`, `opcion` (`contratos`, `clase`, `strike`, `vence`,
`ejercida`), `acciones`, `dias_retraso`, `fuera_de_plazo`.

## Las reglas

- **Se cita la declaración, no un rastreador.** Cada fila sale del PDF del Clerk, con su DocID y su enlace.
  Las webs que agregan estas operaciones sirven para curiosear, pero se equivocan (una mostraba las fechas de
  Pelosi un día antes que sus PTR). El PTR manda.
- **Los importes son rangos.** «De 1.000.001 a 5.000.000 $», nunca «3 millones».
- **El titular importa.** Las operaciones de Pelosi de 2026 son todas SP: su cónyuge.
- **Se dice el retraso.** Cada fila lleva los días entre la operación y la presentación; más de 45 se marca fuera
  de plazo.
- **Una opción es una opción.** Una call con strike y vencimiento no es una compra de acciones. La herramienta
  lee contratos, strike y vencimiento de la descripción y marca los ejercicios.
- **Es un gancho, no una estrategia.** Una declaración de hace semanas es un motivo para mirar un gráfico, no una
  entrada. Si el usuario quiere operar algo que vio aquí, va por el camino largo: kemet-scanner y kemet-entrada
  deciden si hay operación hoy; acciones, no opciones (la cuenta propia lleva `permitir_opciones: false`);
  tamaño con kemet-tamano, comprobación con kemet-riesgo, ticket con kemet-broker solo tras su sí.

## Pasos

1. Pregunta qué quiere: un miembro concreto (`index --miembro`), lo nuevo de los últimos días (`recientes`) o
   un PTR que ya tiene localizado (`ptr DOC_ID`).
2. Para vigilar, `recientes --miembro pelosi --escribir` enseña solo lo que no había visto y lo apunta. El Clerk
   rehace el índice una vez al día, así que una comprobación cada hora en días laborables sobra (`/loop 1h` o
   una tarea programada). Código 1 significa que no hay nada nuevo. En enero mira también el índice del año
   anterior.
3. Para leer un PTR, `ptr DOC_ID` guarda el PDF y, si hay `pdftotext`, imprime las filas; si no, abre el PDF y
   léelo tú directamente. Cuando un informe ocupa varias páginas, comprueba el número de filas contra el PDF.
4. Cuéntaselo al usuario con la fila delante: quién (y qué titular), qué, cuánto (el rango), cuándo operó y
   cuántos días tardó en declararlo, y el enlace. Después, siempre: «Es una declaración pública presentada N días
   después de la operación. Dice lo que compró su cónyuge en julio, no lo que nadie va a comprar mañana».
5. Si quiere actuar, no es aquí: kemet-scanner y kemet-entrada miran si hay operación hoy en ese ticker, y el
   resto del pack hace lo suyo. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan
   filtros y parámetros validados en su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: los PTR de Nancy Pelosi de 2026

Sobre el índice y los textos guardados en `tests/fixtures/kemet-congreso` (reales, leídos el 13 de octubre de 2026):

```
$ python3 congreso.py index --miembro pelosi --anio 2026 --offline tests/fixtures/kemet-congreso --ahora "2026-11-11 16:30"
CONGRESO, índice 2026 del House Clerk, 4 declaraciones de pelosi · 22:30 Madrid / 16:30 NY
2026-10-02  Hon. Nancy Pelosi            CA11  P    doc 20035553  https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035553.pdf
2026-08-21  Hon. Nancy Pelosi            CA11  P    doc 20035143  https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035143.pdf
2026-06-23  Hon. Nancy Pelosi            CA11  P    doc 20034836  https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20034836.pdf
2026-01-23  Hon. Nancy Pelosi            CA11  P    doc 20033725  https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20033725.pdf
Declaraciones públicas (STOCK Act), presentadas hasta 45 días después de operar. No es información privilegiada.
```

```
$ python3 congreso.py ptr 20035143 --anio 2026 --offline tests/fixtures/kemet-congreso
Hon. Nancy Pelosi (CA11), Member. PTR 20035143, presentado el 2026-08-21.
  - cónyuge, compra, Bloom Energy Corporation Class A Common Stock (BE): 10.000 acciones, de 1.000.001 a 5.000.000 $, operada el 2026-07-24, declarada 28 días después
  - cónyuge, compra, Bloom Energy Corporation Class A Common Stock (BE): 100 opciones call con strike de 100 $ que vencen el 2027-06-17, de 1.000.001 a 5.000.000 $, operada el 2026-07-24, declarada 28 días después
  - cónyuge, compra, Bloom Energy Corporation Class A Common Stock (BE): 5.000 acciones, de 500.001 a 1.000.000 $, operada el 2026-07-28, declarada 24 días después
  - cónyuge, compra, Bloom Energy Corporation Class A Common Stock (BE): 100 opciones call con strike de 100 $ que vencen el 2027-06-17, de 500.001 a 1.000.000 $, operada el 2026-07-28, declarada 24 días después
  - cónyuge, compra, Intel Corporation - Common Stock (INTC): 50 opciones call con strike de 50 $ que vencen el 2027-06-17, de 250.001 a 500.000 $, operada el 2026-07-24, declarada 28 días después
  - cónyuge, compra, Intel Corporation - Common Stock (INTC): 10.000 acciones, de 500.001 a 1.000.000 $, operada el 2026-07-24, declarada 28 días después
  - cónyuge, compra, REOF XXV, LLC, de 500.001 a 1.000.000 $, operada el 2026-07-27, declarada 25 días después
      Additional investment in LLC which is acquiring and restoring a luxury hotel property in San Francisco, CA.
Declaración pública por la STOCK Act, presentada hasta 45 días después de la operación. Los importes son rangos. No es información privilegiada.
```

El PTR 20033725 (23 de enero) trae tres ejercicios de calls de su cónyuge (NVDA, TEM y VST, strikes de 80, 20 y
50 $, compradas en enero de 2025), una venta de 5.000 PYPL y el canje de VSNT por la escisión de Comcast, con 7
días de retraso en los ejercicios y 24 en la venta. Lo que se dice al usuario después de la lista: «Es una
declaración pública presentada 28 días después de la operación. Dice lo que compró Paul Pelosi en julio, no lo
que nadie va a comprar mañana».

Con `recientes --dias 45 --miembro pelosi --ahora "2026-10-13 09:00" --escribir` sale solo el 20035553 marcado
NUEVO; la segunda vez, el mismo sin la marca y «0 sin ver».

## El Senado: la vía manual

Los informes del Senado están en `https://efdsearch.senate.gov`. Antes de buscar, la web pide marcar una casilla
aceptando los límites legales de uso de los informes. Ese acuerdo lo acepta la persona, así que esta skill no lo
marca ni lo automatiza. El camino:

1. El usuario abre `https://efdsearch.senate.gov/search/` en su navegador y acepta el acuerdo él mismo.
2. Elige el tipo «Periodic Transactions», escribe el apellido del senador, pone el rango de fechas y busca.
3. Abre el informe: los electrónicos enseñan una tabla de operaciones; los de papel son imágenes escaneadas.
4. Pega la tabla (o una captura, o la página guardada) en el chat, y tú la escribes con la misma forma que las
   filas de la Cámara, con el enlace del informe y el mismo aviso de los 45 días.

## Reglas

- La declaración manda; un rastreador no es fuente.
- Rangos, no cifras; titular, no «Pelosi compró».
- El retraso se dice en cada fila.
- Un PTR es un motivo para mirar, no una entrada.

## Lo que nunca hace

No dice ni insinúa que un miembro tenga información privilegiada, ni que copiar a un político gane al mercado.
No presenta un rango como una cifra exacta ni la fecha de un rastreador como la fecha de la operación. No envía
órdenes y no copia operaciones con opciones. No automatiza el acuerdo del Senado ni ningún inicio de sesión.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
