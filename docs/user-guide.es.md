# Ask Ubuntu — Guía del usuario

Ask Ubuntu es un asistente de IA para Ubuntu Linux. Responde preguntas sobre tu sistema, paquetes instalados, servicios en ejecución, hardware, configuración y uso general de Ubuntu.

Por defecto, funciona completamente de forma local con un modelo de Lemonade Server — sin nube requerida. También puede conectarse a proveedores de IA remotos (Anthropic, OpenAI, Google Gemini, o cualquier endpoint compatible con OpenAI como Ollama) cuando prefieras modelos en la nube o cuando la inferencia local no esté disponible. La búsqueda documental (RAG) está desactivada para los proveedores remotos.

---

## Qué puede responder Ask Ubuntu

- "¿Cómo instalo VLC?" — te indica el comando snap o apt con información de versión
- "¿Qué versión de Firefox tengo?" — comprueba tu versión snap instalada real
- "¿Por qué el ventilador de mi portátil funciona a plena potencia?" — lee tus sensores térmicos y el CPU governor
- "¿Cuánto espacio libre en disco hay?" — lee estadísticas de montaje en vivo
- "¿Está nginx en ejecución?" — comprueba el estado del servicio systemd en tiempo real
- "¿Qué snap interfaces necesita la aplicación de cámara?" — lo busca en el snap store
- "¿Cómo activo un firewall?" — obtiene la página man de UFW y te da los comandos exactos
- "¿Qué procesos están usando mi RAM?" — obtiene una instantánea de procesos en vivo y la explica

Ask Ubuntu tiene pleno conocimiento de tu máquina específica. Cuando preguntas "¿cuánta RAM tengo?", responde con tu memoria real, no con una explicación genérica.

---

## Iniciar Ask Ubuntu

### Terminal CLI

```bash
./ask-ubuntu
```

O si está instalado como snap:
```bash
ask-ubuntu
```

Ask Ubuntu se iniciará, mostrará una cabecera con información del sistema y te dejará en el prompt del chat.

### Desktop GUI

Lanza desde el lanzador de aplicaciones o desde el terminal:
```bash
cd electron && npm start
```

La aplicación abre una ventana dividida: panel de información del sistema a la izquierda, chat a la derecha.

### Configuración inicial

**Con Lemonade (local):** En el primer inicio, Ask Ubuntu:
1. Descargará el modelo de IA desde Lemonade Server (~2–5 GB según el modelo)
2. Descargará el modelo de incrustación para búsqueda de documentos (~500 MB)
3. Construirá el índice de documentación — lee páginas man y archivos de ayuda de Ubuntu (~2–3 minutos)

Todo queda en caché en `~/.cache/ask-ubuntu/`. Los inicios posteriores cargan al instante.

**Con un proveedor remoto:** No se necesita descargar ningún modelo. Ask Ubuntu se conecta directamente a la API del proveedor. La búsqueda documental (RAG) está desactivada cuando se usan modelos remotos.

---

## Usar la CLI

### Hacer preguntas

Escribe cualquier pregunta en el prompt `●` y pulsa Enter:

```
● How do I check if a service is enabled?
```

Para **preguntas multilínea** (p. ej. pegar un mensaje de error), pulsa `Esc` y luego `Enter` para insertar una nueva línea. Pulsa `Enter` solo para enviar.

Usa `↑` y `↓` para navegar por el historial de preguntas.

### Comandos especiales

| Comando | Qué hace |
|---------|----------|
| `/model` | Abre el selector de modelos interactivo — modelos locales y remotos |
| `/providers` | Añadir, editar o eliminar la configuración de proveedores remotos |
| `/help` | Muestra la tabla de ayuda |
| `/clear` | Limpia la pantalla |
| `/exit` o `/quit` | Salir de Ask Ubuntu |
| `Ctrl+D` | Salir |

### Cambiar el modelo en la CLI

Escribe `/model` para abrir un selector interactivo a pantalla completa con dos secciones:

**Modelos locales** (Lemonade):
- **Escribe para buscar** — filtra la lista de modelos instantáneamente mientras escribes
- `↑` / `↓` — desplazarse por la lista
- `PgUp` / `PgDn` — desplazarse más rápido
- `Enter` — seleccionar el modelo resaltado
- `Esc` — cancelar y mantener el modelo actual

Los badges indican:
- **★ Recommended** — mejor opción para tu hardware
- **NPU** — diseñado para ejecutarse en el AMD NPU (el más rápido en hardware compatible)
- **✓ Downloaded** — ya está en disco, carga inmediatamente
- *(sin badge)* — se descargará automáticamente al seleccionarlo (~2–5 GB)

**Modelos remotos** (☁ nube):
- Los proveedores configurados aparecen debajo de la lista local, con un prefijo ☁
- Los modelos se descubren automáticamente desde la API del proveedor; si el descubrimiento falla, puedes escribir el nombre del modelo manualmente
- Seleccionar un modelo remoto cambia inmediatamente (sin descarga)

### Gestionar proveedores remotos en la CLI

Escribe `/providers` para abrir el gestor interactivo de proveedores:

```
  ☁ Remote Providers

  1. Anthropic [preset]
  2. My Ollama  http://192.168.1.10:11434/v1

  [a Añadir] [e Editar] [r Eliminar] [q Listo]
  Haz clic en acciones o filas. ↑↓ navegar   PgUp/PgDn desplazar   Enter editar   Esc salir
```

- Atajos de teclado: `a` añadir, `e` o `Enter` editar el elemento seleccionado, `r` eliminar el elemento seleccionado, `q` o `Esc` cerrar.
- También puedes hacer clic en una fila de proveedor para seleccionarla y volver a hacer clic para editar.
- Las etiquetas de acción (`[a Añadir]`, `[e Editar]`, `[r Eliminar]`, `[q Listo]`) son clicables.

Los proveedores definidos mediante variable de entorno (p. ej. `ANTHROPIC_API_KEY`) se muestran pero no se pueden eliminar aquí.

**Usar un proveedor desde la línea de comandos:**

```bash
./ask-ubuntu --provider anthropic               # clave desde la variable ANTHROPIC_API_KEY
./ask-ubuntu --provider openai --api-key sk-... # clave pasada directamente
./ask-ubuntu --provider my-ollama               # proveedor personalizado por ID
```

### Leer las respuestas

Las respuestas aparecen como texto en streaming. Los bloques de código están resaltados. Si el asistente consultó datos del sistema en vivo antes de responder (p. ej. uso de memoria, versiones de paquetes), esas llamadas a herramientas se muestran en líneas de detalles contraídas antes de la respuesta:

```
  ↳ check_snap(firefox)
  ↳ get_system_stats()
```

---

## Usar la Desktop GUI

### Disposición de la ventana

La ventana tiene dos paneles:

**Barra lateral izquierda** — instantánea de información del sistema:
- SO, kernel, nombre de host, factor de forma (portátil/escritorio)
- CPU, GPU, memoria, disco por montaje, batería
- Alertas térmicas activas
- Recuento de paquetes instalados (snap y deb)
- En la parte superior: **botón de selección de modelo** y **botón de nuevo chat**

**Panel derecho** — el área de chat:
- Tus mensajes aparecen a la derecha en naranja
- Las respuestas del asistente aparecen a la izquierda
- Un punto pulsante muestra cuando el modelo está procesando
- Las llamadas a herramientas (búsquedas de paquetes, estadísticas en vivo) aparecen como detalles desplegables

### Cambiar el modelo en la GUI

Haz clic en el icono **⊙** (modelo/sunburst) en la parte superior de la barra lateral izquierda. Esto abre el overlay de selección de modelo con dos pestañas:

**Pestaña Local:**
- **Cuadro de búsqueda** — escribe para filtrar la lista de modelos al instante
- Cada fila muestra el nombre del modelo, tamaño y badges de estado
- Haz clic en una fila para seleccionarla
- Si el modelo aún no está descargado, aparece una barra de progreso — espera a que se complete la descarga antes de chatear

Badges:
- **Recommended** (naranja) — el mejor para tu hardware
- **NPU** (azul) — se ejecuta en el AMD NPU
- **Downloaded** (verde) — ya disponible

**Pestaña Remote:**
- Muestra los proveedores configurados y sus modelos disponibles
- Los modelos se descubren automáticamente desde la API del proveedor; para proveedores sin lista de modelos preestablecida (p. ej. Ollama), el descubrimiento se ejecuta automáticamente, con una opción de entrada manual como alternativa
- Haz clic en **Select** junto a cualquier modelo para cambiar a él inmediatamente
- Haz clic en **+ Add Provider** para añadir un nuevo proveedor:
  1. Elige un preajuste (Anthropic, OpenAI, Gemini) o Custom
  2. Introduce la clave API (y la URL base + el nombre para proveedores personalizados)
  3. Haz clic en **Save** — los modelos aparecen inmediatamente
- Haz clic en **Edit** en un proveedor existente para actualizar sus datos
- Haz clic en **Remove** para eliminar un proveedor guardado

### Gestionar proveedores remotos en la GUI

Las claves API de los proveedores también se pueden proporcionar mediante variables de entorno — tienen prioridad sobre la configuración guardada:

| Proveedor | Variable de entorno |
|-----------|---------------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |

Los proveedores configurados mediante variable de entorno aparecen en la pestaña Remote como de solo lectura (sin botón Editar/Eliminar). Los proveedores del archivo de configuración son totalmente editables en la interfaz.

### Iniciar una nueva conversación

Haz clic en el botón **+** (nuevo chat) en la barra lateral para borrar la conversación y empezar de nuevo. Los mensajes anteriores no se guardan.

### Bloques de código

Cada bloque de código en una respuesta tiene un botón **Copy**. Haz clic en él para copiar el comando al portapapeles. El botón parpadea para confirmar la copia.

---

## Cómo Ask Ubuntu elige el modelo de IA

Al iniciarse, Ask Ubuntu selecciona automáticamente el mejor modelo disponible para tu hardware:

### 1. NPU + FLM (máxima prioridad)

Si tienes un AMD NPU (XDNA o XDNA2 — presente en procesadores Ryzen AI y Strix Point) y el backend FastFlowLM (FLM) está instalado, Ask Ubuntu utiliza un modelo FLM dedicado que se ejecuta de forma nativa en el NPU. Esta es la opción más rápida y eficiente energéticamente.

Orden de preferencia de modelos FLM:
1. Qwen3-8b-FLM (8 mil millones de parámetros, mejor calidad)
2. Phi-4-Mini-Instruct-FLM (4B, más rápido)
3. Llama-3.2-3B-FLM (3B, el más pequeño)

Solo se seleccionan automáticamente los modelos FLM ya descargados. Si no hay ninguno, recurre al nivel de hardware.

### 2. Nivel de hardware (alternativa)

| Nivel | Hardware | Modelo |
|-------|----------|--------|
| High-End | AMD Strix / Ryzen AI (GPU) | Qwen3-4B-Instruct-2507-GGUF |
| Mid-Intel | Intel Core / Ultra | Phi-4-mini-instruct-GGUF |
| Balanced AMD | AMD CPU, ≥ 16 GB RAM | Llama-3.2-3B-Instruct-GGUF |
| Legacy | Otros / poca RAM | Llama-3.2-1B-Instruct-GGUF |

### Fijar un modelo específico

```bash
# CLI — pasar en la línea de comandos
./ask-ubuntu --model Llama-3.2-3B-Instruct-GGUF

# GUI — establecer una variable de entorno antes de iniciar
ASK_UBUNTU_MODEL=Llama-3.2-1B-Instruct-GGUF npm start
```

---

## Cómo funciona el contexto del sistema

Antes de tu primer mensaje, Ask Ubuntu recopila una instantánea de tu máquina:

- Identificación completa del SO (versión de Ubuntu, nombre clave, kernel)
- Modelo de CPU, número de núcleos, hyperthreading, caché L3, CPU frequency governor activo
- Nombre de GPU, uso de memoria VRAM y GTT, temperatura, velocidad de reloj (AMD)
- RAM: usada, disponible, en caché; uso de swap; presión de memoria (PSI)
- Disco: tipo de unidad (NVMe SSD / HDD), detección de LVM/LUKS/RAID, uso por montaje
- Interfaces de red: tipo, estado, velocidad
- Carga y estado de la batería (portátiles)
- Zonas térmicas — te avisa si alguna zona está caliente
- Todos los snaps y paquetes deb instalados
- Servicios systemd en ejecución

Este contexto se incluye con cada pregunta, por lo que las respuestas son siempre específicas para tu máquina.

El LLM también puede llamar a **herramientas en vivo** durante la conversación para obtener datos actualizados:

| Herramienta | Qué obtiene |
|-------------|------------|
| `check_snap(name)` | Versión instalada + versión en la tienda para un snap |
| `check_apt(name)` | Si un paquete deb está instalado o disponible |
| `list_installed_snaps()` | Todos los snaps instalados con versiones |
| `check_service(name)` | Si un servicio systemd está activo y habilitado |
| `list_running_services()` | Todos los daemons en ejecución |
| `list_failed_services()` | Todas las unidades systemd fallidas |
| `get_system_stats()` | Uso en vivo de memoria, GPU, CPU, procesos principales, disco |

---

## Cómo funciona la recuperación de documentos (RAG)

Ask Ubuntu tiene un índice vectorial local de documentación de Ubuntu. Antes de responder tu pregunta, busca en este índice los 3 documentos más relevantes y los incluye como contexto para el modelo de IA.

El índice contiene:
- ~500 páginas man de Ubuntu (apt, snap, systemctl, ufw, etc.)
- ~200 artículos de ayuda de Ubuntu de help.ubuntu.com
- La guía del usuario y FAQ de Ask Ubuntu (este documento)

Las páginas man se cargan desde:
1. `/var/lib/snapd/hostfs/usr/share/man/` mediante `usr-share-man` (`system-files`) al ejecutarse como snap
2. `/usr/share/man/` si/cuando `system-packages-doc` lo expone en snapd (respaldo futuro mantenido en el código)
3. El caché local en `~/.cache/ask-ubuntu/manpages/`
4. Descargadas de manpages.ubuntu.com en el primer uso (luego en caché)

El índice se almacena en `~/.cache/ask-ubuntu/`. Elimínalo para forzar una reconstrucción:
```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

---

## Consejos para hacer buenas preguntas

- **Sé específico** — "¿por qué apt va lento?" obtiene una mejor respuesta que "arregla mis paquetes"
- **Incluye el error** — pega el mensaje de error exacto, Ask Ubuntu lo explicará
- **Haz preguntas de seguimiento** — Ask Ubuntu recuerda el contexto de la conversación
- **Pide comandos** — "dame el comando para comprobar la temperatura de mi GPU" devuelve un comando listo para ejecutar
- **Pregunta sobre tu sistema** — "¿está Wayland o X11 en ejecución?", "¿cuál es mi CPU governor?"

---

## Proveedores remotos y privacidad

Cuando usas un proveedor remoto, tus preguntas y el contexto del sistema se envían a la API de ese proveedor a través de internet. Si la privacidad es una preocupación, usa un modelo local de Lemonade en su lugar.

Los proveedores definidos mediante variable de entorno nunca son escritos en disco por Ask Ubuntu. Los proveedores guardados a través de la interfaz o el comando `/providers` se almacenan en `~/.config/ask-ubuntu/remote_providers.json`.

## Versiones de Ubuntu compatibles

Ask Ubuntu funciona en Ubuntu 22.04 LTS (Jammy) y 24.04 LTS (Noble). Requiere Python 3.10+ y Lemonade Server ejecutándose localmente en el puerto 8000, o un proveedor remoto configurado.
