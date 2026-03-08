# Ask Ubuntu — Preguntas frecuentes

## Primeros pasos

### ¿Cómo inicio Ask Ubuntu?

**CLI:** Ejecuta `./ask-ubuntu` (o `ask-ubuntu` si está instalado como snap) en una terminal.

**GUI:** Ábrelo desde el lanzador de aplicaciones o ejecuta `cd electron && npm start` en una terminal.

Para modelos locales, inicia Lemonade Server primero:
```bash
lemonade-server start
```

Si tienes un proveedor remoto configurado (Anthropic, OpenAI, Gemini o personalizado), Ask Ubuntu lo usará automáticamente cuando Lemonade no esté disponible.

### ¿Qué es Lemonade Server?

Lemonade Server es el motor de inferencia de IA local que usa Ask Ubuntu para ejecutar el modelo de lenguaje en tu propio equipo. Funciona en el puerto 8000. Instálalo desde el proyecto Lemonade en GitHub.

Lemonade es opcional si configuras un proveedor remoto — Ask Ubuntu puede conectarse a APIs en la nube en su lugar.

### ¿Ask Ubuntu envía datos a internet?

**Con modelos locales (Lemonade):** No. La inferencia de IA se ejecuta en tu equipo. Las man pages pueden obtenerse de manpages.ubuntu.com en el primer uso para construir la caché local, pero esto es de solo lectura y sin autenticación.

**Con proveedores remotos:** Sí. Tus preguntas y el contexto del sistema se envían a la API del proveedor (Anthropic, OpenAI, Gemini o tu endpoint personalizado). Si la privacidad es una preocupación, usa un modelo local de Lemonade.

### ¿Cuánto tarda el primer inicio?

**Con Lemonade:** El primer inicio descarga el modelo de IA (~2–5 GB) y construye un índice de documentación (~2–3 minutos). Los inicios posteriores cargan todo desde la caché y tardan solo unos segundos.

**Con un proveedor remoto:** Inicia en segundos — no se requiere descarga de modelo ni construcción del índice.

---

## Usar Ask Ubuntu

### ¿Cómo hago una pregunta?

Simplemente escribe en el indicador `●` y pulsa Enter. No se necesita ninguna sintaxis especial.

### ¿Puedo pegar texto de varias líneas como un mensaje de error?

Sí. Pulsa `Esc` y luego `Enter` para insertar una nueva línea en el indicador de la CLI. Pulsa `Enter` solo para enviar. En la GUI, usa `Shift+Enter` para nuevas líneas.

### ¿Cómo inicio una nueva conversación?

**CLI:** La conversación se reinicia cuando reinicias `./ask-ubuntu`.

**GUI:** Haz clic en el botón **+** (nuevo chat) en la parte superior de la barra lateral izquierda.

### ¿Cómo limpio la pantalla de la CLI?

Escribe `/clear` en el indicador.

### ¿Cómo salgo de Ask Ubuntu?

**CLI:** Escribe `/exit`, `/quit` o pulsa `Ctrl+D`.

**GUI:** Cierra la ventana.

### ¿Puede Ask Ubuntu ejecutar comandos en mi equipo?

No. Ask Ubuntu lee el estado del sistema (listas de paquetes, estado de servicios, estadísticas en vivo) pero nunca ejecuta comandos ni realiza cambios en tu sistema. Te dirá qué comando ejecutar; tú lo ejecutas tú mismo.

---

## Modelos

### ¿Cómo elige Ask Ubuntu qué modelo de IA usar?

Detecta tu hardware automáticamente:
1. Si tienes una AMD NPU (Ryzen AI, Strix Point) y el backend FLM está instalado, usa el mejor modelo FLM descargado (Qwen3-8b-FLM, Phi-4-Mini-FLM o Llama-3.2-3B-FLM).
2. De lo contrario, selecciona un modelo GGUF según el nivel de tu hardware (AMD de gama alta, Intel, AMD equilibrado o hardware heredado).
3. Si Lemonade no está en ejecución y hay un proveedor remoto configurado, cambia automáticamente al proveedor remoto.

### ¿Cómo cambio el modelo de IA?

**CLI:** Escribe `/model` para abrir el selector de modelos interactivo. Muestra tanto modelos locales (Lemonade) como remotos (nube). Usa las teclas de flecha para navegar, escribe para buscar, pulsa Enter para seleccionar.

**GUI:** Haz clic en el botón de icono de modelo **⊙** en la parte superior de la barra lateral izquierda. Cambia entre las pestañas **Local** y **Remote**.

### ¿Qué significan las insignias de los modelos?

- **Recommended** — el modelo que Ask Ubuntu considera mejor para tu hardware
- **NPU** — diseñado para ejecutarse en la AMD NPU usando el backend FLM
- **Downloaded** — ya está en disco; se carga inmediatamente
- **☁** (icono de nube en la CLI) — un modelo remoto en la nube
- Sin insignia — se descargará cuando se seleccione (puede tardar unos minutos)

### ¿Cómo descargo un nuevo modelo?

En la pestaña Local del selector de modelos (CLI `/model` o botón ⊙ de la GUI), selecciona cualquier modelo que aún no esté descargado. Ask Ubuntu lo descargará automáticamente y cambiará a él. Los modelos remotos no requieren descarga.

### ¿Puedo fijar un modelo específico?

Sí. Inicia Ask Ubuntu con `--model <model-id>` en la CLI, o establece la variable de entorno `ASK_UBUNTU_MODEL` para la GUI. Para un modelo remoto, usa `--provider` y opcionalmente `--model`:

```bash
./ask-ubuntu --provider anthropic --model claude-sonnet-4-6
```

### ¿Qué es el backend FLM?

FastFlowLM (FLM) es un backend para ejecutar modelos de lenguaje cuantizados de forma nativa en la AMD NPU (Neural Processing Unit). Es significativamente más rápido y eficiente energéticamente que ejecutarlo en la CPU. El backend FLM se instala por separado como parte del stack Lemonade NPU.

### ¿Qué modelos están disponibles?

Hay ~70 modelos de chat en el catálogo de Lemonade, incluidos Llama, Qwen, Phi, Mistral y otros en varios tamaños y formatos (FLM para NPU, GGUF para CPU/GPU). Usa el selector de modelos para explorarlos todos.

---

## Proveedores remotos

### ¿Qué proveedores remotos son compatibles?

Ask Ubuntu es compatible con cualquier API compatible con OpenAI. Preajustes integrados:

| Proveedor | Modelos |
|-----------|---------|
| Anthropic | Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku 4.5 |
| OpenAI | GPT-4o, GPT-4o Mini, o3-mini |
| Google Gemini | Gemini 2.0 Flash, Gemini 2.5 Pro, Gemini 1.5 Pro |
| Personalizado | Cualquier endpoint compatible con OpenAI (Ollama, LiteLLM, vLLM, etc.) |

### ¿Cómo configuro un proveedor remoto?

**Más rápido — variable de entorno:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
./ask-ubuntu
```

**CLI — interactivo:**
Escribe `/providers` y sigue las instrucciones para añadir un proveedor.

**CLI — puntual:**
```bash
./ask-ubuntu --provider openai --api-key sk-...
```

**GUI:**
Abre el selector de modelos (botón ⊙) → pestaña Remote → rellena el formulario → Save.

### ¿Dónde se guarda la configuración del proveedor remoto?

En `~/.config/ask-ubuntu/remote_providers.json` (o `$SNAP_USER_DATA/config/remote_providers.json` dentro de un snap). Las claves API definidas mediante variable de entorno nunca se escriben en disco.

### ¿Puedo añadir Ollama como proveedor personalizado?

Sí. Usa la opción de proveedor personalizado y configura:
- **URL base:** `http://<nombre-de-host>:11434/v1` (el endpoint compatible con OpenAI de Ollama)
- **Clave API:** `ollama` (o cualquier cadena no vacía — Ollama no la verifica)
- **Nombre:** el que quieras (p. ej. «Mi Ollama»)

Ask Ubuntu descubrirá automáticamente los modelos que Ollama ha descargado. Si el descubrimiento falla (p. ej. el servidor no es accesible), puedes escribir el nombre del modelo manualmente.

### ¿Funciona la búsqueda documental (RAG) con proveedores remotos?

No. El RAG requiere un modelo de incrustación local cargado a través de Lemonade. Cuando se usa un proveedor remoto, Ask Ubuntu responde únicamente desde su conocimiento de entrenamiento y el contexto de tu sistema.

### ¿Qué ocurre si Lemonade se cae durante una sesión?

Solo las nuevas sesiones cambian automáticamente. Si Lemonade se detiene mientras ya estás chateando, usa `/model` para cambiar a un modelo remoto para la sesión actual, o reinicia Ask Ubuntu.

---

## Información del sistema

### ¿Qué información del sistema recopila Ask Ubuntu?

Al inicio: detalles del sistema operativo, modelo/núcleos/governor de la CPU, nombre y memoria de la GPU, uso de RAM, puntos de montaje de disco, batería, zonas térmicas, snaps y paquetes deb instalados, servicios en ejecución. Consulta la barra lateral izquierda en la GUI para un resumen rápido.

### ¿Ask Ubuntu puede ver mis archivos?

No. Ask Ubuntu lee metadatos del sistema (listas de paquetes, estado de servicios, información de hardware) pero nunca lee tus archivos personales, el contenido de tu directorio personal ni ningún archivo que no hayas pegado explícitamente en el chat.

### ¿Por qué la información del sistema en la barra lateral muestra una advertencia térmica?

Aparece una alerta térmica si alguna zona térmica de la CPU o GPU reporta 60 °C o más al inicio. Esto es informativo — Ask Ubuntu te está indicando que tu equipo está caliente. Pregúntale «is my laptop overheating?» para un análisis detallado.

### ¿Cómo actualizo la información del sistema?

La información del sistema se recopila al inicio. Reinicia Ask Ubuntu (o abre una nueva sesión) para obtener una instantánea actualizada. Las estadísticas en vivo (RAM, CPU, GPU durante la conversación) se obtienen bajo demanda usando la herramienta `get_system_stats` cuando haces preguntas sobre el uso actual de recursos.

---

## Documentación y RAG

### ¿Qué documentación busca Ask Ubuntu?

Busca en un índice vectorial local de ~500 man pages de Ubuntu y ~200 artículos de ayuda de Ubuntu de help.ubuntu.com, además de la guía de usuario de Ask Ubuntu. Este índice se construye en la primera ejecución y se almacena en caché en `~/.cache/ask-ubuntu/`.

### ¿Por qué Ask Ubuntu no conoce una man page específica?

El índice cubre los comandos más frecuentemente referenciados. Si falta una man page, Ask Ubuntu intentará igualmente responder desde su conocimiento de entrenamiento. También puedes pedirle que consulte un comando específico: «show me the man page for rsync».

### ¿Cómo fuerzo una reconstrucción del índice de documentación?

```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

Luego reinicia Ask Ubuntu. El índice se reconstruirá desde cero (2–3 minutos).

### ¿Cómo obtengo man pages/archivos de ayuda locales en lugar de los obtenidos remotamente?

Conecta estas interfaces `system-files` de solo lectura:
```bash
sudo snap connect ask-ubuntu:usr-share-man
sudo snap connect ask-ubuntu:usr-share-help
```

Esto da al snap acceso de lectura a:
- `/var/lib/snapd/hostfs/usr/share/man/`
- `/var/lib/snapd/hostfs/usr/share/help/`

`system-packages-doc` se mantiene soportado en el código como respaldo futuro.

---

## Solución de problemas

### Ask Ubuntu dice «Lemonade Server is not running»

Inicia Lemonade Server:
```bash
lemonade-server start
```

Luego vuelve a iniciar Ask Ubuntu.

### La GUI se queda atascada en «Starting backend…»

1. Asegúrate de que Lemonade Server esté en ejecución: `curl http://localhost:8000/api/v1/health`
2. Revisa la terminal en busca de líneas de error `[server]` — un error de importación de Python o un conflicto de puerto aparecerá allí.

### La descarga de un modelo falló o se quedó atascada

Abre el selector de modelos nuevamente e intenta seleccionar el mismo modelo otra vez. Si falla repetidamente, verifica que Lemonade Server tenga acceso a internet y suficiente espacio en disco (~5 GB libres).

### Las flechas del selector de modelos de la CLI no funcionan en mi terminal

Algunas terminales (especialmente variantes muy antiguas de xterm) no transmiten correctamente las secuencias de escape. Prueba con una terminal diferente (GNOME Terminal, Alacritty, Kitty o la terminal integrada de Ubuntu). El selector requiere una terminal moderna con soporte de códigos de escape ANSI.

### Mi snap no puede leer /var/lib/apt/lists o /var/lib/dpkg

Las interfaces snap deben estar conectadas:
```bash
sudo snap connect ask-ubuntu:var-lib-apt-lists
sudo snap connect ask-ubuntu:var-lib-dpkg
```

Tras conectarlas, reinicia Ask Ubuntu.

### Ask Ubuntu da respuestas incorrectas sobre mi sistema

Intenta pedirle que vuelva a verificar con una herramienta en vivo: «run get_system_stats and tell me what it shows». También prueba iniciar una nueva conversación — la información del sistema se recopila al inicio de cada sesión.

### ¿Cómo reporto un error?

Abre un issue en el repositorio de GitHub de Ask Ubuntu con:
- Tu versión de Ubuntu (`lsb_release -d`)
- La versión de Ask Ubuntu o el commit de git
- La pregunta exacta que hiciste y la respuesta que obtuviste
- Cualquier salida de error de la terminal

---

## Privacidad y seguridad

### ¿Son privados mis datos?

**Con modelos locales (Lemonade):** Sí. Toda la inferencia se ejecuta localmente en tu equipo. Nada se envía a ningún servidor remoto excepto:
- Man pages obtenidas de manpages.ubuntu.com en el primer uso (sin autenticación, solo lectura)
- Páginas de ayuda obtenidas de help.ubuntu.com en el primer uso (sin autenticación, solo lectura)

**Con proveedores remotos:** Tus preguntas y el contexto del sistema se envían a la API del proveedor. Consulta la política de privacidad del proveedor que elijas (Anthropic, OpenAI, Google o tu endpoint personalizado). Las claves API guardadas a través de la interfaz se almacenan localmente en `~/.config/ask-ubuntu/remote_providers.json`.

### ¿Puede Ask Ubuntu modificar mi sistema?

No. Lee el estado del sistema pero nunca ejecuta comandos ni escribe en tus archivos. Te dice qué ejecutar; tú decides si hacerlo.
