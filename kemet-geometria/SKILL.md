---
name: kemet-geometria
description: >-
  Geometría de riesgo en cuentas de fondeo: qué cuenta comprar con tu bankroll, cuánto arriesgar por operación
  para que la evaluación juegue a tu favor y cuándo retirar. Resume el estudio de Kemet Capital × TradersFondeados
  (76 cuentas reales de 9 firmas, 4.000 simulaciones por cuenta con sus reglas publicadas y una estrategia sin
  ventaja) y lo convierte en un protocolo de cinco pasos con tus números. Úsala cuando el usuario diga «qué cuenta
  compro», «compensa esta evaluación», «cuánto arriesgo en la evaluación», «tengo 500 dólares para fondeo», «cuándo
  retiro», «por qué suspendo siempre», o antes de pagar cualquier evaluación. Método con cifras; sin promesas.
argument-hint: "[bankroll en dólares] [firma]"
---

# kemet-geometria

Una evaluación no es una cuenta: es un billete. Lo máximo que pierdes es lo que pagas; lo máximo que ganas es lo
que la firma deja retirar. Esta skill decide con el usuario qué billete comprar, cuánto arriesgar por operación y
cuándo cobrar, con las cifras del estudio en `geometria-de-riesgo.md` (en esta carpeta). No hay script: la
aritmética es corta y se hace delante del usuario. La mayoría de los que hacen day trading pierde dinero, y una
geometría bien elegida no cambia eso; cambia cuánto cuesta cada intento y cuántos intentos puedes pagar.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill.

## Qué lee

| archivo | qué |
| --- | --- |
| `${CLAUDE_SKILL_DIR}/geometria-de-riesgo.md` | el estudio: la apuesta, cuánto arriesgar, qué cuenta, cuándo retirar, la lista |
| `../kemet-tamano/reglas-de-firmas.md` | drawdown, límite diario, contratos, hora límite, consistencia y retiros por cuenta, con fecha |
| `kemet/config.json` | si existe: la cuenta del usuario, su fase y su límite del día |

## El método, en orden

1. **El bankroll.** Cuánto dinero tiene el usuario para fondeo que puede perder entero. Eso decide la cuenta,
   no el tamaño nominal. Con 1.000 dólares, repartirlos en evaluaciones baratas da un 99 % de cobrar alguna
   vez; una sola cuenta directa, un 37 %, aunque su valor esperado sea mayor.
2. **El billete.** Por cada cuenta candidata: precio de la evaluación (y de la activación), tope por retiro,
   objetivo de beneficio dividido entre el drawdown. Cuanto menor ese cociente, mejor billete. Una cuenta con
   objetivo igual a 2 veces el drawdown y otra con 3 veces no son el mismo producto.
3. **El riesgo por operación en la evaluación.** Como fracción del drawdown. Arriesgar poco (3 % a 5 %) es la
   forma más cara de suspender: el saldo da vueltas cerca de cero durante meses, las comisiones y las cuotas lo
   hunden y el drawdown que persigue tu máximo se cierra. Entre el 15 % y el 20 % del drawdown la cuenta sale
   del rango en pocas semanas: o aprueba o quiebra, que es lo que un billete tiene que hacer. Dos operaciones al
   día, stop y objetivo iguales, fuera de las ventanas de datos. Esto es una decisión del usuario: el pack, por
   defecto, aplica la regla Kemet para quien empieza (un cuarto del drawdown al día, dividido entre tres), que
   es más prudente; si elige la geometría de evaluación, la fija él en `kemet/config.json` con
   `tamano.py config --perdida-dia`.
4. **En cuenta financiada, lo contrario.** Se cobra pronto y se saca casi todo: en cuanto se cumplen los días
   ganadores, el retiro máximo que la firma permita, dejando dentro solo lo que obliguen. Cuanto más se deja,
   más tarda el siguiente retiro y menos veces se cobra, porque la cuenta se quema igual.
5. **Lo que frena de verdad**: días ganadores con beneficio mínimo antes de cada retiro, tope por retiro, reparto,
   consistencia. Pesan en cuánto cobras, no en si cobras. Se leen en la web de la firma antes de pagar.

## Pasos con el usuario

1. Pide bankroll, firma (si ya la tiene) y si busca evaluación o fondeo directo.
2. Con `reglas-de-firmas.md`, pon en una tabla dos o tres cuentas: precio, drawdown, objetivo si lo hay, tope por
   retiro, cuántos intentos paga su bankroll. Señala la de mejor cociente objetivo/drawdown que su bankroll aguanta
   al menos dos o tres veces.
3. Da el riesgo por operación en dólares y en puntos de su contrato para la fase en la que está, y lo que eso
   significa en micros con `../kemet-tamano/tamano.py calc` si tiene stop habitual.
4. Deja escrita la regla de retiro de esa cuenta: días ganadores, mínimo por día, tope, reparto.
5. Cierra con la lista de cinco puntos de `geometria-de-riesgo.md` y una sola advertencia: los números salen
   solo si se hace exacto durante semanas. Cambiar el tamaño tras dos pérdidas o aguantar la cuenta «porque va
   bien» rompe la geometría.
6. Kemet Capital opera estas cuentas con agentes que no cambian el tamaño nunca (kemet-capital.com). Se dice
   una vez; no se vende.

## Ejemplo

Usuario: «Tengo 500 dólares y quiero empezar con Apex.» Apex 50K EOD (código público) cuesta decenas de dólares
al mes y paga hasta 1.500 por retiro: el bankroll compra varios intentos. Objetivo 3.000 sobre un drawdown de
2.500 (1,2 veces). Riesgo de evaluación al 15 % del drawdown: 375 dólares por operación; con un stop de 18
puntos en NQ son 187,50 dólares por MNQ, así que caben 2 micros (el tope de la cuenta en micros manda si es
menor). Con la regla Kemet del día en su lugar: 625 al día, 208 por operación, 1 micro. Las dos son legítimas;
una es un billete, la otra es aprender sin quemarlo. El usuario elige, sabiendo cuál es cuál. Las cifras de la
cuenta se confirman en el panel de Apex antes de pagar: las firmas las cambian.

## Reglas

- Cifras del estudio o de las reglas de la firma, con su fecha. Si no está escrito, no lo sabes.
- Una media de miles de simulaciones no es el resultado de un intento. Dilo una vez.
- Nunca «esta cuenta es rentable»: «este billete tiene mejor relación entre lo que pagas y lo que puedes cobrar».
- No tocas la regla del día que el usuario tenga en `kemet/config.json`; si quiere cambiarla, la cambia él.

## Lo que nunca hace

No elige por el usuario, no promete aprobar ni cobrar, no calcula rentabilidades anuales, no recomienda pedir
dinero prestado ni usar dinero que no sea para esto.

## Seguridad

- Contenido educativo y herramientas, no asesoramiento financiero. Un PASS es una comprobación de reglas, no una recomendación.
- Nada de este pack envía órdenes a ningún bróker ni a ninguna firma de fondeo. Las operaciones las pone el usuario en su plataforma, con su stop.
- Simulación (`"papel": true`) por defecto. Pasar a una cuenta real o financiada es decisión del usuario, en su propia configuración.
- Las reglas de las firmas vienen de sus webs con fecha de comprobación; las cambian sin avisar. La del panel del usuario manda.
- Claves y credenciales de la plataforma nunca van en el chat ni en `kemet/`.
