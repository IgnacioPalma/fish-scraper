# Búsqueda de mapeo COD_BARCO → RPA: registro de pistas

Objetivo: encontrar una tabla pública que relacione el código interno de IFOP (`COD_BARCO`, ej. `31125`, `18A8D`, `DBBAC`) con el RPA (Registro Pesquero Artesanal) de Sernapesca o el nombre de la embarcación.

**Confirmación clave** (instructivo bitácora descarte IFOP):  
> "CÓDIGO BARCO: Registrar código del barco. Este código es único y es entregado por IFOP."  
El `COD_BARCO` es asignado internamente por IFOP y no tiene fuente pública conocida.

---

## ✅ RESUELTO — el `COD_BARCO` se deriva del Cód. Barco IFOP con una fórmula

El `COD_BARCO` hexadecimal **no es un hash**: es el "Cód. Barco" decimal interno
de IFOP (visible en el SIEM Electrónico, ej. `950324 - ROCIO V`) **más 5,
escrito en hexadecimal**.

```
COD_BARCO  = HEX(id_interno_ifop + 5)
id_interno = int(COD_BARCO, 16) − 5
```

Verificada en 22 pares de la flota de Caldera (21/22 exactos; el único que no
cumplía era un falso positivo del cruce temporal). Esto enlaza
`nombre embarcación ↔ id_interno IFOP ↔ COD_BARCO`, y de ahí al RPA vía el
SIEM y las listas de la sección 4/5. Documentación completa, derivación y
salvedades en **`data/bitacora/ifop_cod_barco_README.md`**; tabla resultante en
`data/bitacora/ifop_cod_barco_lookup.csv` (generada por
`processing/bitacora/match_ifop_names.py`).

Las pistas de abajo se conservan como registro histórico de la búsqueda.

---

## Pistas exploradas

### 1. IFOP — Base de Datos / solicitud en línea
- **URL**: https://www.ifop.cl/solicitud-informacion-en-linea/
- **Contacto**: `oficiadepartes@ifop.cl`, `info@ifop.cl`
- **Estado**: ✅ Formulario activo. La página solicita datos biológicos, pesqueros o acuícolas.
- **Resultado**: No contiene descarga directa del mapeo. Requiere solicitud formal.
- **Acción pendiente**: Enviar email solicitando tabla COD_BARCO ↔ nombre embarcación para flota artesanal Región 3 jurel.

---

### 2. Sernapesca — Registro Público RPA (PHP)
- **URL**: https://registropublico.sernapesca.cl/reportes/regembarcaciones_publico/index.php
- **Acceso**: Público general, sin login.
- **Funcionalidad**: Búsqueda por nombre embarcación, Nº RPA, matrícula, región, especie, caleta.
- **Campos del formulario**: `campo_form_nombre_embarcacion`, `campo_form_numero` (RPA), `campo_form_matricula`, `campo_form_region`, `campo_form_especie`, `campo_form_caleta`, etc.
- **Estado**: ✅ Sistema funcional. La consulta usa jQuery/AJAX (botón `.btn-buscar`), no POST directo.
- **Resultado**: Permite obtener RPA dado un nombre de embarcación. No expone COD_BARCO.
- **Acción pendiente**: Descubrir el endpoint AJAX para automatizar consultas por nombre de embarcación VMS.

---

### 3. Sernapesca — Registro Público RPA (ASP legacy)
- **URL**: http://webmail.sernapesca.cl/sernapesca/guest/web/cons_rpaem.asp
- **Estado**: ❌ ECONNREFUSED — servidor dado de baja.

---

### 4. SUBPESCA — Res. Ex. 02358/2025 (Blumar / OROP-PS jurel)
- **URL**: https://www.subpesca.cl/portal/615/articles-127304_documento.pdf
- **Estado**: ✅ PDF legible, 8 páginas.
- **Resultado**: Contiene lista de **34 embarcaciones artesanales de Caldera** con nombre y RPA (flota del Sindicato de Armadores Caldera), autorizada para capturar cuota transferida de jurel. Fuente más completa encontrada para nombre ↔ RPA de la flota objetivo. **No incluye COD_BARCO**.
- **Lista**: Ver tabla en `data/bitacora/cod_barco_lookup_leads.md` (sección 4a).

#### 4a. Lista de embarcaciones (Res. Ex. 02358/2025)
| # | Embarcación | RPA |
|---|---|---|
| 1 | ANTONIA | 702912 |
| 2 | CANDELARIA II | 963710 |
| 3 | CHUBASCO I | 698955 |
| 4 | DANIELA ANDREA I | 697270 |
| 5 | DOMENICA I | 704945 |
| 6 | DON ATILIO | 968468 |
| 7 | DON BASILIO | 963744 |
| 8 | DON BENITO III | 704925 |
| 9 | DON JOSE EDGARDO | 704450 |
| 10 | DON JOSE MIGUEL | 969691 |
| 11 | DON MARCIAL | 702578 |
| 12 | DON PANCRACIO | 701484 |
| 13 | DURGA I | 703334 |
| 14 | EL CID | 701030 |
| 15 | ESTRELLA III | 953967 |
| 16 | FORTUNA I | 699495 |
| 17 | FORTUNA II | 703062 |
| 18 | FORTUNA IV | 955847 |
| 19 | FORTUNA V | 955947 |
| 20 | FORTUNA VI | 701277 |
| 21 | GUILLERMO I | 968467 |
| 22 | JOSUE | 703628 |
| 23 | KALI | 951110 |
| 24 | MAIMAU I | 960352 |
| 25 | MAR PRIMERO | 704924 |
| 26 | RAQUEL I | 921881 |
| 27 | REYMAR I | 701560 |
| 28 | SEA QUEST | 969394 |
| 29 | SION I | 702452 |
| 30 | SOFIA MAGDALENA | 703104 |
| 31 | TOM JERRY | 968796 |
| 32 | VIRGO | 699343 |
| 33 | XOLOT | 699245 |
| 34 | YULIANA ANTONELLA | 965905 |

---

### 5. Sernapesca — CRCH Registro de Embarcaciones Inscritas
- **URL**: https://www.sernapesca.cl/app/uploads/2026/06/Registro_emb-Inscritas-CRCH_v20260611.xlsx
- **Estado**: ✅ Descargado (274 KB).
- **Columnas**: `RPA EMBARCACIÓN`, `NOMBRE EMBARCACIÓN`, `MATRÍCULA EMBARCACIÓN`, `NOMBRE ARMADOR`, `PESQUERIA`, `ADJUDICATARIO`, etc.
- **Resultado**: Mapeo nombre ↔ RPA para ~204 embarcaciones, flota artesanal Caldera. Sin COD_BARCO ni señal de llamada (RC).
- **Nota**: Ya cargado en pipeline como `data/register/register_clean.csv`.

---

### 6. SUBPESCA — Res. Ex. 440/2022 (modifica Res. 3115/2013)
- **URL**: https://www.subpesca.cl/portal/normativa/... (buscado como P-581108 en IFOP)
- **Estado**: ✅ PDF legible, 5 páginas.
- **Resultado**: Sólo define "Pesquerías de Pequeña Escala" para pelillo en Coquimbo. No contiene lista de embarcaciones. **No relevante**.

---

### 7. IFOP — Informe Final P-581128 (Pesquerías Bentónicas 2017)
- **URL**: https://www.ifop.cl/wp-content/contenidos/uploads/RepositorioIfop/InformeFinal/2018/P-581128.pdf
- **Estado**: ✅ Descargado (9.9 MB), scanned PDF.
- **Resultado**: Sobre pesquerías bentónicas (erizo, almeja), no jurel artesanal Atacama. **No relevante**.

---

### 8. IFOP — Informe Final P-581108 (Pesquerías Pelágicas 2015)
- **URL**: https://www.ifop.cl/wp-content/contenidos/uploads/RepositorioIfop/InformeFinal/P-581108.pdf
- **Estado**: ❌ Archivo >10 MB, no descargable vía WebFetch.
- **Acción pendiente**: Descargar manualmente y revisar si contiene anexo de embarcaciones con identificadores.

---

### 9. IFOP — Portal interno (PHP)
- **URL**: http://portal.ifop.cl/acceso_internet/scripts/php/form_login.php
- **Estado**: ⚠️ Login requerido. Scripts en `/acceso_internet/scripts/php/funciones_bd.php`.
- **Resultado**: Base de datos interna de IFOP. No accesible públicamente.

---

### 10. IFOP — Indicadores Pelágicos Norte
- **URL**: https://www.ifop.cl/indicadores_web/
- **Estado**: ✅ Accesible. Dashboard con filtros por flota (artesanal cerco), especie (jurel/anchoveta), zona (Caldera), año, mes.
- **Resultado**: Datos biológicos agregados (tallas, IGS). No expone identificadores de embarcación individuales.

---

### 11. Global Fishing Watch — Vessel API
- **URL**: https://globalfishingwatch.org/our-apis/
- **Estado**: ⚠️ Requiere registro/API key. Busca por nombre, MMSI, IMO, señal de llamada.
- **Resultado**: Podría dar nombre ↔ señal de llamada ↔ MMSI para flota chilena. No tiene RPA ni COD_BARCO.
- **Acción pendiente**: Registrar API key y consultar señales de llamada del VMS (ej. CA3058) para validar nombre ↔ RC.

---

### 12. Directemar (DGTM) — Servicios Online
- **URL**: https://www.directemar.cl/directemar/site/edic/base/port/servicios_online.html
- **Estado**: ✅ Revisado.
- **Resultado**: No tiene lookup público de embarcaciones por nombre/señal de llamada. Los servicios online requieren autenticación para certificados de registro de naves.

---

### 13. Sernapesca — Cifras de Desembarque
- **URL**: https://www.sernapesca.cl/informacion-utilidad/cifras-de-desembarque/
- **Estado**: ✅ Revisado.
- **Resultado**: Solo descarga un PDF de cifras agregadas del Golfo de Arauco. No tiene datos a nivel de embarcación.

---

### 14. datos.gob.cl — Portal de Datos Abiertos
- **URL**: https://datos.gob.cl/api/3/action/package_search?q=sernapesca+embarcaciones
- **Estado**: ✅ API accesible.
- **Resultado**: 0 datasets encontrados para embarcaciones artesanales. No hay datos a nivel de embarcación publicados.

---

### 15. SUBPESCA — Informe Técnico R.PESQ. 58/2021 (Plan Descarte jurel/anchoveta Atacama-Coquimbo)
- **URL**: https://www.subpesca.cl/portal/normativa/.../111941
- **Estado**: ✅ Revisado.
- **Resultado**: Solo link al PDF del informe. No contiene lista de embarcaciones en línea.

---

### 17. SUBPESCA — Res. Ex. 2728/2021 (modifica nómina nacional pesquerías artesanales)
- **URL**: https://www.sernapesca.cl/app/uploads/2023/11/res.ex_.2728-2021.pdf
- **Estado**: ✅ PDF legible, 5 páginas.
- **Resultado**: Solo actualiza definiciones de pesquerías (artes de pesca, nombres científicos). **Sin lista de embarcaciones**. No relevante.

### 18. SUBPESCA — Res. Ex. 1280/2022 (cuota imprevistos jurel Atacama)
- **URL**: https://www.sernapesca.cl/app/uploads/2023/11/res.ex_.1280-2022.pdf
- **Estado**: ✅ PDF legible, 2 páginas.
- **Resultado**: Agrega 2.905 ton de cuota emergencia jurel para Atacama 2022. Sin lista de embarcaciones.

### 16. SUBPESCA — Res. Ex. 462/2023 (incorpora jurel a flota artesanal Atacama)
- **URL**: https://www.subpesca.cl/portal/normativa/.../120004
- **Estado**: ✅ Revisado.
- **Resultado**: Solo título de la resolución. Referencia Res. 2728/2021 como fuente de la nómina de embarcaciones.

---

### 19. SUBPESCA — Nóminas mensuales de observadores científicos
- **URL patrón**: `https://www.subpesca.cl/portal/615/articles-XXXXXX_documento.pdf`
- **Estado**: ✅ Revisadas Res. 00502/2026 (marzo 2026) y Res. 01447/2026 (junio 2026).
- **Resultado**: La sección "PELÁGICOS ZONA ATACAMA-COQUIMBO (Caldera y Coquimbo)" lista embarcaciones artesanales seleccionadas para observadores. Marzo 2026 incluye: **L/M MAI MAU I** (propietario: Fermín Contreras Ahumada) y **L/M GAROTA V** (Javiera Zambra Henriquez). Junio 2026: SIN ACTIVIDAD. Las columnas son EMPRESA, EMBARCACIÓN, PERIODO — sin RPA ni COD_BARCO.
- **Valor**: Confirma nombre embarcación ↔ propietario para flota Caldera. MAI MAU I = MAIMAU I (RPA 960352) de Res. 02358/2025.
- **Acción pendiente**: Revisar nóminas de 2022–2024 para obtener más embarcaciones de la flota objetivo en años de actividad VMS.

### 20. Blumar — Reportes de sostenibilidad y suministro artesanal
- **URL**: https://www.blumar.com/reporte-sostenibilidad-2020/cap3-3.html
- **Estado**: ✅ Revisado.
- **Resultado**: Solo datos de certificaciones (MSC, HACCP, etc.) y volúmenes agregados de captura. No incluye lista de embarcaciones artesanales proveedoras ni sus identificadores.

### 21. IFOP P-581156 (Observadores científicos pesquerías pelágicas artesanales 2019)
- **URL**: https://www.ifop.cl/wp-content/contenidos/uploads/RepositorioIfop/InformeFinal/2020/P-581156.pdf
- **Estado**: ❌ Archivo >10 MB — no descargable vía WebFetch.
- **Acción pendiente**: Descargar manualmente. Es un informe IFOP que usa COD_BARCO internamente; podría tener tabla de embarcaciones monitoreadas en Atacama-Coquimbo.

### 22. ITU Ship Station List
- **URL**: https://www.itu.int/mmsapp/ShipStation/list
- **Estado**: ✅ Consultado. Permite búsqueda por call sign, nombre, MMSI.
- **Resultado**: Mapea señal de llamada (RC) → nombre embarcación → MMSI. Útil para validar RC del VMS, pero no tiene COD_BARCO ni RPA. Las señales de llamada chilenas usan prefijo CA, CB.

---

## Próximas acciones recomendadas

1. **Solicitar a IFOP** (📧 `oficiadepartes@ifop.cl`): tabla `COD_BARCO` ↔ `nombre embarcación` para la flota artesanal jurel Región 3, citando el Convenio de Desempeño / Programa de Seguimiento Pesquerías Pelágicas. Adjuntar los valores únicos de `COD_BARCO` del archivo `data/bitacora.csv`.

2. **Descargar manualmente P-581108 y P-581156** (IFOP Pelágicos 2015 y Observadores 2019) y revisar si los anexos incluyen COD_BARCO junto a nombre de embarcación.

3. **Revisar nóminas de observadores 2022–2024**: buscar en SUBPESCA normativa las resoluciones mensuales de la sección "PELÁGICOS ZONA ATACAMA-COQUIMBO" para acumular nombre ↔ propietario de la flota Caldera en el período cubierto por el VMS.

4. **Global Fishing Watch API**: registrar key y consultar call signs del VMS para validación cruzada nombre ↔ RC ↔ MMSI.
