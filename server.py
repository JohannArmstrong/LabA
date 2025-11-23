# En cuanto a la comunicación con la DB, este script es funcina de forma
# muy parecida al que toma los datos desde el CSV desde google.
# La diferencia es que este los toma de un json cuando se lo envía google
# cuando el formulario es enviado.



from flask import Flask, request, jsonify, render_template
import psycopg as psy
from datetime import datetime
import logging
import os

app = Flask(__name__)

# cambia los NaN, etc. para mostrar "-" en las tablas
@app.template_filter("default_dash")
def default_dash(value):
    if value is None or str(value).lower() in ("nan", "none"):
        return "-"
    return value


# almacena logs en un archivo local. Para eso el módulo "os"
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/server.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# config para conección con la DB
DB_CONFIG = {
    "host": "localhost",
    "dbname": "labA",
    "user": "postgres",
    "password": "Passw0rd",
    "port": 5432
}

# funciones auxiliares

def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    # A veces Google Forms manda "2025-01-31T12:33:10.123Z"
    if "T" in value and "Z" in value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except:
            pass

    formatos = [
        "%Y-%m-%d",              # JSON Google Forms (solo fecha)
        "%Y-%m-%d %H:%M:%S",     # JSON Google Forms (fecha y hora)
        "%d/%m/%Y",              # CSV Google Sheets
        "%d/%m/%Y %H:%M:%S",     # CSV Google Sheets (si agrega hora)
        "%Y/%m/%d",              # Algunas configuraciones
        "%Y/%m/%d %H:%M:%S"
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(value, fmt).date()
        except:
            pass

    print("⚠ No se pudo parsear la fecha:", value)
    return None



def parse_int(value):
    try:
        return int(float(value))
    except Exception:
        return None


def clean_keys(data):
    clean = {}
    for key, value in data.items():
        new_key = key.strip().replace("\n", " ").replace("\r", "").replace("  ", " ")
        clean[new_key] = value
    return clean



# NUEVA FUNCIÓN ⇨ consulta/crea valores en tablas normalizadas

def get_or_create(cur, table, field, value):
    """
    Busca un valor en una tabla normalizada.
    Si no existe, lo crea.
    Retorna el id.
    """
    if value is None or str(value).strip() == "":
        return None

    cur.execute(f"SELECT id_{table} FROM {table} WHERE {field} = %s;", (value,))    
    row = cur.fetchone()

    if row:
        return row[0]

    cur.execute(
        f"INSERT INTO {table} ({field}) VALUES (%s) RETURNING id_{table};",
        (value,)
    )
    return cur.fetchone()[0]


# establece la ruta, es decir, el "túnel" que proporciona ngrok
@app.route("/api/nuevo_proyecto", methods=["POST"])
def nuevo_proyecto():
    data = clean_keys(request.get_json())
    logging.info(f"📩 Datos recibidos: {data}")

    fecha_registro = parse_date(str(data.get("Marca temporal"))) or datetime.now().date()
    
    # para evitar errores que había
    #fecha_necesidad_raw = data.get("Fecha de necesidad: (considerar fecha de necesidad teniendo en cuenta una semana de antelación)")
    #fecha_necesidad = parse_date(fecha_necesidad_raw)

    # fecha_registro = parse_date(str(data.get("Marca temporal"))) or datetime.now().date()
    # esa anda pero se ve que toma el date.now
    fecha_necesidad = parse_date(str(data.get("Fecha de necesidad: (considerar fecha de necesidad teniendo en cuenta una semana de antelación)")))
    # Manejo flexible de la clave de fecha de necesidad

    #key_fecha_necesidad = next(
    #    (k for k in data.keys() if "Fecha de necesidad" in k),
    #    None
    #)
    #print(">>> Fecha llegada del JSON:", data.get(key_fecha_necesidad))


    #fecha_necesidad = parse_date(str(data.get(key_fecha_necesidad))) if key_fecha_necesidad else None



    cantidad_prototipos = parse_int(data.get("Cantidad de prototipos a fabricar:"))

    copiado = data.get("Ya copiado") if "Ya copiado" in data else None
    estado_raw = data.get("Estado") if "Estado" in data else None

    try:
        conn_str = (
            f"host={DB_CONFIG['host']} dbname={DB_CONFIG['dbname']} "
            f"user={DB_CONFIG['user']} password={DB_CONFIG['password']} port={DB_CONFIG['port']}"
        )

        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:

                # verifica si el usuario ya existe
                email = data.get("Dirección de correo electrónico")
                nombre = data.get("Nombre completo:")

                cur.execute("SELECT id_usuario FROM usuario WHERE email = %s;", (email,))
                user_row = cur.fetchone()

                if user_row:
                    id_usuario = user_row[0]
                else:
                    cur.execute(
                        "INSERT INTO usuario (nombre, email) VALUES (%s, %s) RETURNING id_usuario;",
                        (nombre, email)
                    )
                    id_usuario = cur.fetchone()[0]

                
                # nuevo método para consultar/insertar en las nuevas tablas
                id_cargo = get_or_create(
                    cur, "cargo", "nombre",
                    data.get("Describa su cargo dentro de la Institución y/o Proyecto.")
                )

                id_sede = get_or_create(
                    cur, "sede", "nombre",
                    data.get("En qué sede queda el laboratorio al cual quiere acceder:")
                )

                id_tipo = get_or_create(
                    cur, "tipo", "nombre",
                    data.get("Seleccione el tipo de solicitud")
                )

                id_herramienta = get_or_create(
                    cur, "herramienta", "nombre",
                    data.get("Seleccione la herramienta, material o servicio que desea utilizar:")
                )

                id_origen_material = get_or_create(
                    cur, "origen_material", "nombre",
                    data.get("Origen del material")
                )

                id_estado = get_or_create(
                    cur, "estado", "nombre",
                    estado_raw
                )

                id_carrera = get_or_create(
                    cur, "carrera", "nombre",
                    data.get("Describa a qué carrera y/o institución corresponde el proyecto:")
                )


                # insertar proyecto en DB
                cur.execute("""
                    INSERT INTO proyecto (
                        fecha_registro,
                        id_usuario,
                        id_carrera,
                        id_cargo,
                        id_sede,
                        nombre_proyecto,
                        descripcion,
                        id_tipo,
                        id_herramienta,
                        material,
                        cantidad_prototipos,
                        justificacion,
                        fecha_necesidad,
                        tiempo_estimado,
                        otros_comentarios,
                        id_origen_material,
                        copiado,
                        id_estado
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT ON CONSTRAINT proyecto_unico DO NOTHING;
                """, (
                    fecha_registro,
                    id_usuario,
                    id_carrera,
                    id_cargo,
                    id_sede,
                    data.get("Nombre del proyecto/actividad:"),
                    data.get("Breve descripción del proyecto"),
                    id_tipo,
                    id_herramienta,
                    data.get("Material a utilizar"),
                    cantidad_prototipos,
                    data.get("Vinculación del proyecto con las acciones relacionadas a las herramientas de fabricación digital / materiales / servicios: (justificación de uso)"),
                    fecha_necesidad,
                    data.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"),
                    data.get("Otros comentarios"),
                    id_origen_material,
                    copiado,
                    id_estado
                ))

                conn.commit()

        msg = "✅ Proyecto insertado correctamente (o ignorado si ya existía)."
        logging.info(msg)
        print(msg)
        return jsonify({"status": "ok", "mensaje": msg})

    except Exception as e:
        msg = f"❌ Error al insertar en la base de datos: {e}"
        logging.error(msg)
        print(msg)
        return jsonify({"status": "error", "mensaje": str(e)}), 500


# ruta para la p'agina web localhost:5000
@app.route("/")
def proyectos():
    try:
        conn_str = (
            f"host={DB_CONFIG['host']} dbname={DB_CONFIG['dbname']} "
            f"user={DB_CONFIG['user']} password={DB_CONFIG['password']} port={DB_CONFIG['port']}"
        )
        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:
                # consulta censilla para comenzar
                #                                                         
                cur.execute("""
                    SELECT p.id_proyecto, p.fecha_registro, u.email, u.nombre, carrera.nombre, cargo.nombre, sede.nombre, p.nombre_proyecto, p.descripcion, tipo.nombre, herr.nombre, p.material, p.cantidad_prototipos, p.justificacion, p.fecha_necesidad, p.tiempo_estimado, p.otros_comentarios, origen.nombre, estado.nombre
                    FROM proyecto p
                    JOIN usuario u ON p.id_usuario = u.id_usuario
                    JOIN tipo ON p.id_tipo = tipo.id_tipo
                    JOIN sede ON p.id_sede = sede.id_sede
                    JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
                    JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                    JOIN estado ON p.id_estado = estado.id_estado
                    JOIN carrera ON p.id_carrera = carrera.id_carrera
                    JOIN cargo ON p.id_cargo = cargo.id_cargo
                    ORDER BY p.id_proyecto DESC;
                """)
                proyectos = cur.fetchall()

        return render_template("proyectos.html", proyectos=proyectos)

    except Exception as e:
        # loguear el error y mostrar un mensaje
        logging.error(f"Error en consulta: {e}")
        return f"❌ Error al cargar proyectos: {e}", 500


# inicia túnel público de ngrok
if __name__ == "__main__":
    from pyngrok import ngrok

    public_url = ngrok.connect(5000)
    print(f"🌐 URL pública: {public_url}")
    app.run(port=5000)
