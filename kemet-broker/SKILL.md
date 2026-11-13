---
name: kemet-broker
description: >-
  La única skill del pack que puede acabar en una orden puesta, y por eso la más estricta. Convierte cada orden de
  kemet/orden.json en un ticket en palabras llanas (una bracket enseña su stop-loss, su take-profit y la pérdida al
  stop) y la marca LISTA solo si kemet-riesgo le dio PASS hoy a esa orden exacta, por su huella. Claude lee el ticket
  al usuario, espera un sí explícito para ese ticket en el chat, lo apunta palabra por palabra y solo entonces llama al
  conector del bróker: Alpaca por su servidor MCP oficial, cuenta papel por defecto, con la herramienta en «Necesita
  aprobación» para que la tarjeta de Claude vuelva a preguntar. Apunta el fill en kemet/estado/broker.json y en
  kemet/portfolio.json, y construye la orden que cierra una posición antes de la hora de estar plano. Para futuros no
  hay conector gratuito: el ticket se enseña igual y la operación la pone el usuario en su plataforma. Cubre cómo
  instalar el servidor de Alpaca en Claude Desktop y Claude Code con las claves en el archivo de configuración, nunca
  en el chat. Úsala cuando el usuario diga «pon la orden», «cómprala», «envíala al bróker», «ejecuta», «cierra la
  posición», «sácame», «ponme plano», «conecta Alpaca», «quiero operar en papel», o siempre después de un PASS de
  kemet-riesgo.
argument-hint: "[mostrar | aprobar --huella H --respuesta «sí» | registrar --huella H --id-broker ID --precio P | plano --simbolo TSLA]"
---

# kemet-broker

Una orden llega al bróker solo después de tres puertas, cada vez, para cada orden: kemet-riesgo le dio PASS hoy a esa
orden exacta; el usuario escribió un sí explícito para ese ticket en el chat; el usuario pulsó «Permitir una vez» en la
tarjeta de Claude, que aparece porque la herramienta del bróker está en «Necesita aprobación». Dos síes del usuario y un
PASS de las reglas. Sin sí no hay orden. La mayoría de los que hacen day trading pierde dinero, y una herramienta no
cambia eso: estas puertas evitan la orden que no querías, no hacen ganar ninguna.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill (donde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/broker.py" mostrar                                     # cada orden como ticket, LISTA o no
python3 "${CLAUDE_SKILL_DIR}/broker.py" mostrar --huella 28e10297de27 --json
python3 "${CLAUDE_SKILL_DIR}/broker.py" aprobar --huella 28e10297de27 --respuesta - <<'SI'
sí
SI
# el sí del usuario, palabra por palabra, siempre por la entrada estándar: entre comillas en la línea de órdenes, un «$(…)» se ejecutaría
python3 "${CLAUDE_SKILL_DIR}/broker.py" rechazar --huella 28e10297de27 --respuesta "no"
python3 "${CLAUDE_SKILL_DIR}/broker.py" registrar --huella 28e10297de27 --id-broker ID --precio 393.10 [--cantidad 8]
python3 "${CLAUDE_SKILL_DIR}/broker.py" registrar --huella 28e10297de27 --estado denegada|fallida [--nota "..."]
python3 "${CLAUDE_SKILL_DIR}/broker.py" registrar --simbolo TSLA --lado venta --cantidad 8 --precio 389.51 --id-broker ID   # la pata que se llenó
python3 "${CLAUDE_SKILL_DIR}/broker.py" plano --simbolo TSLA                        # la venta que cierra la posición, a kemet/orden.json
python3 "${CLAUDE_SKILL_DIR}/broker.py" hoy                                         # lo apuntado hoy
```

**Lo que de verdad protege.** `broker.py` no envía nada y sus comprobaciones las puede saltar quien edite `kemet/`: la
última puerta es la tarjeta de Claude. Por eso `place_stock_order` va siempre en «Necesita aprobación» (nunca «Permitir
siempre» ni un modo que apruebe solo), y antes de la primera orden de la sesión se mira la cuenta con `get_account_info`:
una cuenta papel de Alpaca tiene un número que empieza por `PA`. Si no empieza por `PA`, es dinero real: no se envía nada
y se le dice al usuario. Un PASS vale 10 minutos y deja de valer si cambia `kemet/estado/dia.json`; uno hecho con
`--ahora` es una simulación y nunca deja una orden LISTA.

`broker.py` no habla con ningún bróker: enseña tickets, comprueba que una respuesta es un sí de verdad para esa orden,
apunta lo que pasó y construye la orden de cierre. `--ahora "2026-11-11 10:16"` fija el reloj (hora de Nueva York).
Código de salida de `mostrar`: 0 si alguna orden está LISTA, 1 si ninguna. `aprobar` devuelve 1 si la respuesta no
vale. Errores en una línea, código 2.

## Qué lee y escribe

| archivo | qué |
| --- | --- |
| `kemet/orden.json` | las órdenes propuestas (kemet-tamano `orden`; `plano` lo sustituye por la orden de cierre) |
| `kemet/estado/riesgo.json` | los veredictos de kemet-riesgo con la huella de cada orden; solo un PASS de hoy deja una orden LISTA |
| `kemet/estado/broker.json` | cada sí, no, colocada, denegada y fallida, con la pérdida al stop de cada entrada; kemet-riesgo cuenta aquí lo colocado hoy |
| `kemet/portfolio.json` | efectivo y posiciones (`simbolo`, `cantidad`, `precio_medio`); lo actualiza `registrar` |
| `kemet/config.json` | `papel`, `presupuesto` (arranca la cartera si no existe), `plano_a`, `cuenta_nombre` |
| `kemet/precios.json` | (futuros) el último precio para la orden de cierre, si kemet-alertas lo guardó |

## Dos formatos de orden

- **Acciones** (`"instrumento": "accion"`): la orden lleva los campos de `place_stock_order` de Alpaca tal cual, con los
  números como texto: `symbol`, `side`, `qty`, `type`, `time_in_force`, `order_class`, `take_profit_limit_price`,
  `stop_loss_stop_price` y, si es límite, `limit_price`. Se envían esos y nada más: `why`, `por_que` y `plan` se quedan
  en el archivo.
- **Futuros** (`"instrumento": "futuro"`): `simbolo` (MNQ, MES, MCL…), `lado` compra o venta, `contratos`, `tipo`,
  `precio`, `stop`, `objetivo`. No se envían a ningún sitio: el ticket se lee y la orden la pone el usuario.

La **huella** es un sha1 de 12 hex de los campos que importan para poner la orden (los de Alpaca en una acción;
símbolo, lado, contratos, tipo, precio, stop, objetivo y cierre en un futuro). Es la misma función que usa
kemet-riesgo, así que un veredicto solo vale para la orden idéntica: una acción más, un stop movido o un día después,
y el ticket vuelve a NO LISTA hasta otro `riesgo.py check`.

## Conectar Alpaca (servidor MCP oficial)

El servidor es github.com/alpacahq/alpaca-mcp-server (MIT), se ejecuta en el ordenador del usuario y opera en la
cuenta **papel** salvo que se le diga lo contrario. Comprobado en su repositorio en octubre de 2026 (versión 2.4.0).

1. El usuario abre una cuenta en Alpaca y crea claves de API de **paper trading** en su panel. Son claves distintas de
   las de la cuenta real.
2. Instala `uv` (trae `uvx`): docs.astral.sh/uv.
3. En Claude Desktop: Ajustes > Desarrollador > Editar configuración. Se abre `claude_desktop_config.json` (macOS en
   `~/Library/Application Support/Claude/`, Windows en `%APPDATA%\Claude\`). Añade este bloque (está en
   `claude_desktop_config.example.json`, junto a este archivo) y escribe sus claves en el archivo:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server==2.4.0"],
      "env": {
        "ALPACA_API_KEY": "TU_CLAVE_PAPEL_ESCRITA_AQUI_NUNCA_EN_EL_CHAT",
        "ALPACA_SECRET_KEY": "TU_SECRETO_PAPEL_ESCRITO_AQUI_NUNCA_EN_EL_CHAT",
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,stock-data"
      }
    }
  }
}
```

   El bloque `env` le pasa las claves al servidor como variables de entorno. **Las claves nunca van en el chat.** No las
   pidas, no leas ese archivo en la conversación, y si el usuario pega una clave, dile que borre el mensaje y cree
   claves nuevas en su panel. `ALPACA_PAPER_TRADE` ya es `true` por defecto; escribirlo lo hace visible.
   `ALPACA_TOOLSETS` es opcional y esconde las herramientas que no hacen falta.
4. Reinicia Claude Desktop.
5. **Permisos de las herramientas.** Personalizar > Conectores (Ajustes > Conectores en versiones anteriores), abre
   alpaca y elige por herramienta:
   - `place_stock_order`: **Necesita aprobación**. Nunca «Permitir siempre».
   - lo que pone, cambia, cancela o cierra algo (`cancel_order_by_id`, `replace_order_by_id`, `close_position`,
     `update_account_config`): Necesita aprobación.
   - `place_option_order`, `place_crypto_order`, `close_all_positions`, `cancel_all_orders`,
     `exercise_options_position`, `do_not_exercise_options_position`: **Bloqueada**, salvo que el usuario tenga un
     motivo y lo diga.
   - solo lectura (`get_account_info`, `get_all_positions`, `get_open_position`, `get_orders`, `get_clock`,
     `get_stock_snapshot`, `get_stock_latest_quote`): «Permitir siempre» vale.
6. Compruébalo: pide la información de la cuenta (solo lectura) y confirma en el panel de Alpaca que es la cuenta papel.

En Claude Code, en vez de Claude Desktop, el servidor se añade con `claude mcp add` con las mismas variables de entorno,
y la herramienta de órdenes se deja en «preguntar» en `.claude/settings.json`:
`"permissions": {"ask": ["mcp__alpaca"]}` (todas las herramientas de Alpaca preguntan) y, en `deny`, las que nunca hacen
falta: `mcp__alpaca__close_all_positions`, `mcp__alpaca__cancel_all_orders`, `mcp__alpaca__place_option_order`,
`mcp__alpaca__place_crypto_order`. Nunca una herramienta de órdenes en `allow`, ni el modo que aprueba solo. Añádelo con
`claude mcp add --scope user` o `--scope local`: con `--scope project` las claves acabarían en `.mcp.json`, que se sube a git.

**Brackets en Alpaca.** `place_stock_order` acepta `take_profit_limit_price` y `stop_loss_stop_price` (y un
`stop_loss_limit_price` opcional). Con cualquiera de los dos, el servidor pone `order_class` en `bracket` solo;
kemet-tamano lo escribe igualmente para que el ticket lo enseñe. Una bracket es de acciones enteras, `day` o `gtc`.
Cuando la entrada se llena, el stop-loss y el take-profit esperan en el bróker como dos órdenes que se anulan entre sí.
Son órdenes del día: mueren en el cierre, una razón más para estar plano antes.

## Pasos: la entrada

1. `broker.py mostrar`. Al usuario solo se le lee un ticket LISTO. Uno NO LISTA o BLOQUEADA vuelve a kemet-riesgo (o
   a kemet-tamano si la orden tiene que cambiar).
2. Enseña UN ticket y pregunta: «¿Pongo esta orden? Responde sí o no». Una orden por pregunta. Nunca ofrezcas «sí a
   todas».
3. `broker.py aprobar --huella H --respuesta -` con la respuesta del usuario, palabra por palabra, por la entrada estándar
   en un heredoc con el delimitador entre comillas simples (`<<'SI'` … `SI`), nunca entre comillas en la línea. Si imprime «No
   apuntado», la respuesta no era un sí explícito para esa orden (por ejemplo «vale», «sí a las dos», una pregunta, o
   un sí que nombra otro símbolo u otra cifra). Pregunta otra vez. Nunca conviertas tú una respuesta en un sí.
4. Solo después de «Apuntado tu sí», llama a `place_stock_order` exactamente con el JSON que imprimió el ticket.
   Aparece la tarjeta de Claude: Permitir una vez o Denegar.
5. Apunta lo que pasó: `broker.py registrar --huella H --id-broker <id> --precio <precio del fill>` (de la respuesta
   del conector o de `get_open_position`), o `--estado denegada`, o `--estado fallida --nota "..."`. Una orden fallida
   no se repite sin otro `check` y otro sí. `registrar` escribe el fill en la cartera y deja la pérdida al stop en el
   registro para que kemet-riesgo lleve la cuenta del día.

## Pasos: mientras está abierta, y plano antes del cierre

- kemet-alertas vigila el stop, el objetivo y la hora de estar plano (`alertas.py add --desde-plan`). Las patas de la
  bracket hacen el trabajo de parar.
- Cuando el stop-loss o el take-profit se llena en el bróker, apúntalo sin huella, porque esa venta no pasó por un
  ticket: `broker.py registrar --simbolo TSLA --lado venta --cantidad 8 --precio 389.51 --id-broker <id de la pata>`.
  La cartera vuelve a efectivo y el registro guarda la pata como `llenada`.
- A `plano_a` (15:55 NY en acciones e índices), lo que siga abierto se cierra:
  1. Pregunta al bróker cuántas acciones hay: `get_open_position` (solo lectura).
  2. `broker.py plano --simbolo TSLA` escribe una venta a mercado por la cantidad de `kemet/portfolio.json` (o la de
     `--cantidad`) en `kemet/orden.json`, con `"cierre": true`.
  3. `riesgo.py check`. Una venta que solo cierra lo que tienes nunca se bloquea por los límites del día ni por el
     horario de entradas.
  4. `broker.py mostrar`, y el sí del usuario para esa orden, como arriba.
  5. El stop-loss y el take-profit de la bracket retienen esas acciones, así que Alpaca rechaza otra venta hasta que se
     cancelan: `get_orders` (status open, nested true) los enseña; `cancel_order_by_id` cada uno (Necesita aprobación).
     Después `place_stock_order` con el ticket, y `registrar`.

## Pasos: futuros

El ticket de un futuro se enseña igual, con su pérdida al stop en dólares del micro, y el sí del usuario se apunta
igual. No hay conector gratuito de futuros que se pueda recomendar, así que la orden la pone el usuario en su
plataforma, con el stop puesto antes de confirmar; después `riesgo.py registrar --abrir` para el día y
`broker.py registrar --huella H --precio <fill>` para la cartera (sin `--id-broker`: queda «a mano»). Para cerrar,
`broker.py plano --simbolo MNQ --precio <precio actual>` escribe la orden de cierre, que pasa por kemet-riesgo como
cualquier otra. Los sistemas que Kemet Capital opera con agentes en cuentas de fondeo llevan filtros y parámetros
validados en su propio banco; no están en este pack. kemet-capital.com

## Ejemplo: TSLA, miércoles 11 de noviembre de 2026

Cuenta propia de 5.000 $ en papel, 50 $ de riesgo por operación. El rango de apertura de 15 minutos de TSLA fue
386,35 a 392,67 y la vela de las 10:10 cerró en 393,08, por encima. Stop en el punto medio 389,51 (3,57 $ por acción),
objetivo 1R 396,65, 8 acciones: 28,56 $ al stop. kemet-riesgo le dio PASS a las 10:16.

```
$ python3 broker.py mostrar --ahora "2026-11-11 10:16"
TICKET 2026-11-11 · 16:16 Madrid / 10:16 NY
ORDEN 1 de 1, cuenta PAPEL, Alpaca
  COMPRA 8 TSLA, a mercado, válida hoy
  stop-loss 389,51
  take-profit 396,65
  pérdida al stop unos 28,56 $ si se llena justo en 389,51 (en un mercado rápido se llena peor)
  por qué: ruptura del rango de apertura de TSLA: 8 acciones, 3,57 $ de riesgo por acción, 28,56 $ al stop dentro de tus 50 $ por operación
  huella 28e10297de27
  LISTA: PASS de kemet-riesgo hoy, falta tu sí
  Claude llamará a place_stock_order exactamente con:
    {
      "symbol": "TSLA",
      "side": "buy",
      "qty": "8",
      "type": "market",
      "time_in_force": "day",
      "order_class": "bracket",
      "take_profit_limit_price": "396.65",
      "stop_loss_stop_price": "389.51"
    }
  Alpaca pone la entrada y después el stop-loss y el take-profit como dos órdenes que se anulan entre sí:
  cuando una se llena, la otra se cancela.
  Responde «sí» para poner esta orden, o «no» para dejarla pasar.
  La tarjeta de Claude vuelve a preguntar: Permitir una vez la pone, Denegar la para.

Una orden cada vez: un sí cubre un ticket, nunca el lote. Contenido educativo, no asesoramiento financiero.
```

El usuario contesta «vale»: no cuenta. Contesta «sí, las 8 de TSLA»: cuenta.

```
$ python3 broker.py aprobar --huella 28e10297de27 --respuesta "vale" --ahora "2026-11-11 10:16"
No apuntado: solo cuenta una respuesta que empiece por «sí» (no vale ok, vale, adelante, hazlo). Vuelve a enseñar el ticket 28e10297de27 al usuario y pregunta otra vez.
$ python3 broker.py aprobar --huella 28e10297de27 --respuesta "sí, las 8 de TSLA" --ahora "2026-11-11 10:16"
Apuntado tu sí para 28e10297de27: COMPRA 8 TSLA, a mercado, válida hoy / stop-loss 389,51 / take-profit 396,65 / pérdida al stop unos 28,56 $ si se llena justo en 389,51 (en un mercado rápido se llena peor).
Ahora llama a place_stock_order exactamente con:
{
  "symbol": "TSLA",
  "side": "buy",
  "qty": "8",
  "type": "market",
  "time_in_force": "day",
  "order_class": "bracket",
  "take_profit_limit_price": "396.65",
  "stop_loss_stop_price": "389.51"
}
La tarjeta de Claude dice Permitir una vez o Denegar. Después: broker.py registrar --huella 28e10297de27 --id-broker ID --precio PRECIO
```

Claude llama a `place_stock_order`, la tarjeta dice «Claude quiere usar Place stock order» con ese JSON y dos botones,
Permitir una vez y Denegar. Permitir una vez la manda a la cuenta papel. El fill vuelve a 393,10:

```
$ python3 broker.py registrar --huella 28e10297de27 --id-broker 61e69015-8549-4bfd-b9c3-01e75843f47d --precio 393.10 --ahora "2026-11-11 10:17"
Apuntada a las 10:17 NY: compra 8 TSLA a 393,10, id 61e69015-8549-4bfd-b9c3-01e75843f47d (huella 28e10297de27).
Cartera: efectivo 1.855,20 $, TSLA: 8 acciones a 393,10 de media.
Apuntado en kemet/estado/broker.json y kemet/portfolio.json.
```

A las 15:50 sigue abierta (el máximo del día fue 395,43, el objetivo no se tocó):

```
$ python3 broker.py plano --simbolo TSLA --ahora "2026-11-11 15:50"
Plano TSLA: VENTA 8 acciones de TSLA, a mercado, válida hoy / cierre: solo saca de la posición (plano a las 15:55 NY).
Escrita en kemet/orden.json (sustituye 1 propuesta anterior).
La cantidad sale de kemet/portfolio.json: compárala con get_open_position TSLA antes de decir sí.
Siguiente:
  1. kemet-riesgo: riesgo.py check. Un cierre nunca se bloquea por los límites del día ni por el horario de entradas.
  2. broker.py mostrar, y el sí del usuario para esta orden.
  3. Si el stop-loss y el take-profit del bracket siguen abiertos, Alpaca retiene esas acciones y rechaza otra venta.
     Cancélalos antes: get_orders (status open, nested true) y cancel_order_by_id por cada pata (Necesita aprobación).
     Después place_stock_order con el ticket, y broker.py registrar.
```

Sin ese `check`, `mostrar` dice «NO LISTA: esta orden exacta no está en la última comprobación (se editó o es nueva)».
Al día siguiente, el PASS del 11 tampoco vale: «la comprobación de riesgo es del 2026-11-11, no de hoy».

## Ejemplo: NQ, miércoles 11 de noviembre de 2026

La orden de kemet-tamano para la ruptura del balance inicial (IB 28.199 a 28.426; la vela de las 10:40 cerró en
28.429,75) en una Apex 150K EOD financiada, con el PASS de kemet-riesgo de las 10:45:

```
$ python3 broker.py mostrar --ahora "2026-11-11 10:46"
TICKET 2026-11-11 · 16:46 Madrid / 10:46 NY
ORDEN 1 de 1, cuenta PAPEL, futuros, a mano en tu plataforma
  COMPRA 1 MNQ, Nasdaq 100, orden stop a 28.429,75
  stop 28.312,50, objetivo 28.547
  pérdida al stop 234,50 $ (117,25 pts × 2 $/pt × 1), si se llena justo en el stop
  por qué: ruptura del balance inicial de NQ: 1 MNQ, manda el riesgo por operación
  huella f2328b1ec6e1
  LISTA: PASS de kemet-riesgo hoy, falta tu sí
  No hay conector gratuito de futuros: esta orden la pones tú en tu plataforma, con su stop puesto antes de confirmar.
  Cuando esté puesta: riesgo.py registrar --abrir, y broker.py registrar --huella f2328b1ec6e1 --precio PRECIO_DE_FILL.

Una orden cada vez: un sí cubre un ticket, nunca el lote. Contenido educativo, no asesoramiento financiero.
```

La huella f2328b1ec6e1 es la misma que imprime kemet-riesgo para esa orden.

## Reglas

- Un sí vale para un ticket, con su huella. Dos órdenes son dos preguntas y dos síes.
- La respuesta cuenta si empieza por «sí», no es una pregunta, no habla de un lote, no lleva una condición y no
  contradice la orden (otro símbolo, otra cifra). Lo decide `aprobar`, no Claude.
- Un ticket LISTO que no se decide hoy caduca con el día: mañana hace falta otro `check`.
- Un precio de fill no se promete: una orden a mercado y un stop se llenan a lo que dé el mercado.
- Lo que hay en la cartera lo manda el bróker: `kemet/portfolio.json` es el apunte, `get_open_position` la verdad.

## Lo que nunca hace

No pone una orden sin las tres puertas ni dos órdenes con un sí; no pone órdenes desde una tarea programada o en segundo
plano (no hay nadie para decir sí); no pide, lee, guarda ni repite claves; no cambia `ALPACA_PAPER_TRADE` ni `"papel"`
a real (eso lo hace el usuario en su configuración); no llama por su cuenta a `close_all_positions`,
`cancel_all_orders` ni a herramientas de opciones o cripto; no promete un precio de fill.

## Seguridad
- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes salvo kemet-broker, y solo en cuenta papel por defecto, tras un PASS de kemet-riesgo para esa orden exacta y un sí explícito del usuario para ese ticket en el chat.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
