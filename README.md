# iadroc

Herramienta de procesamiento asíncrono de datos basada en IA utilizando Flask y SQLite.

## Guía técnica completa

Esta guía está orientada a analistas que desean usar la aplicación sin necesidad de tener amplios conocimientos de programación en Python. A continuación se explica paso a paso la instalación, el uso y las opciones de configuración.

### 1. Requisitos previos

- Python 3.9 o superior.
- Acceso a internet para instalar dependencias y para conectarse a la API de OpenAI.
- Opcionalmente Docker si se prefiere ejecutar la aplicación en un contenedor.

### 2. Instalación del entorno

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask --app app.py initdb  # restablece la base de datos y crea usuarios de demostración
flask --app app.py create-user alice secret analyst  # ejemplo para añadir usuarios
```

El comando `initdb` genera una base de datos vacía e incorpora un usuario "demo" (analista) y un usuario "super" (supervisor). El comando `create-user` permite agregar nuevos usuarios indicando nombre, token y rol ("analyst" o "supervisor").

### 3. Puesta en marcha

```bash
FLASK_APP=app.py flask run
```

Al iniciar el servidor visita `http://localhost:5000` en el navegador e inicia sesión con las credenciales de demostración (`demo`/`demo` para el analista o `super`/`maxiasuper` para el supervisor).

### 4. Uso de la interfaz

1. **Crear un trabajo**
   - Selecciona un archivo CSV, un archivo `config.json` y un `directive.txt`.
   - Presiona **Verificar** para calcular una estimación de tokens que serán necesarios.
   - Si los archivos son válidos se habilitará el botón **Enviar**. Introduce una descripción opcional y envía el trabajo.

2. **Roles de usuario**
   - **Analista**: puede crear trabajos y consultar su progreso.
   - **Supervisor**: además de lo anterior, puede aprobar, rechazar, pausar, reanudar o cancelar trabajos.

3. **Estados del trabajo**
   - `pending`: el analista ha enviado el trabajo y espera revisión.
   - `approved`: el supervisor aprobó el trabajo y comenzó el procesamiento.
   - `processing`: el trabajo se está ejecutando en segundo plano.
   - `paused`: el supervisor ha pausado temporalmente el procesamiento.
   - `done`: el trabajo finalizó correctamente y se puede descargar el resultado.
   - `failed`: ocurrió un error durante el procesamiento.
   - `rejected` o `cancelled`: el supervisor rechazó o canceló el trabajo.

En la tabla principal se muestran todos los trabajos con la información de tokens, filas procesadas, errores y enlaces para descargar tanto el resultado final como capturas intermedias.

### 5. Archivos necesarios para un trabajo

- **CSV de datos**: contiene las filas a procesar. El campo objetivo se define en el archivo de configuración.
- **config.json**: especifica parámetros como el modelo de OpenAI, cantidad máxima de filas, nuevas columnas y delimitador del CSV. También debe incluir la clave de API de OpenAI codificada en base64.
- **directive.txt**: prompt que se enviará al modelo. Debe mencionar la palabra "json" para que la aplicación utilice el modo JSON y reciba respuestas estructuradas.

Consulta los archivos `config.json` y `directive.txt` incluidos en el repositorio como ejemplo del formato esperado.

### 6. Personalización de `config.json`

A continuación se describen los campos más relevantes:

- `retry_times`: número de reintentos si ocurre un error al consultar la API.
- `max_rows`: límite de filas a procesar (0 para procesar todas).
- `openai_api_key`: clave de OpenAI codificada en base64.
- `model`: modelo a utilizar (por ejemplo `gpt-3.5-turbo`).
- `target`: nombre de la columna del CSV que contiene el texto a analizar.
- `delimiter`: delimitador utilizado en el CSV.
- `snapshot_rows`: frecuencia (en filas) con la que se guardan capturas parciales.
- `new_columns`: lista de columnas que se añadirán al resultado según la respuesta de la IA.
- `schema`: esquema JSON opcional para validar la respuesta del modelo.

### 7. Consejos de uso

- Siempre verifica que la clave de OpenAI esté correctamente codificada en base64.
- Mantén un registro de los tokens estimados y usados para controlar los costos.
- El directorio `uploads` almacena los archivos de cada trabajo. Puedes limpiar este directorio periódicamente si el tamaño crece demasiado.

### 8. Ejecución mediante Docker

Construye la imagen y publícala (reemplaza `youruser` por tu usuario de Docker Hub):

```bash
docker build -t youruser/iadroc:latest .
docker push youruser/iadroc:latest
```

Ejecuta el contenedor montando un directorio para mantener la base de datos y las subidas:

```bash
docker run -d -p 5000:5000 \
  -v $PWD/data:/data \
  -e DB_PATH=/data/iadroc.db \
  -e UPLOAD_FOLDER=/data/uploads \
  --name iadroc youruser/iadroc:latest
```

Tras iniciar el contenedor, inicializa la base de datos y crea las cuentas necesarias:

```bash
docker exec iadroc flask initdb
# docker exec iadroc flask create-user <nombre> <token> <rol>
```

### 9. Soporte y colaboración

Si encuentras problemas o deseas proponer mejoras, abre un *issue* o envía un *pull request* en el repositorio. Tus aportes son bienvenidos.

