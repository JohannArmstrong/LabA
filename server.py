# En cuanto a la comunicación con la DB, este script es funcina de forma
# muy parecida al que toma los datos desde el CSV desde google.
# La diferencia es que este los toma de un json cuando se lo envía google
# cuando el formulario es enviado.



from flask import Flask, request, jsonify, render_template, make_response
import pdfkit
from weasyprint import HTML, CSS
from bs4 import BeautifulSoup
import psycopg as psy
from datetime import datetime
import logging
import os
import atexit # para cerrar ngrok al cerrar el server
from decimal import Decimal, InvalidOperation
import math

app = Flask(__name__)

# cambia los NaN, etc. para mostrar "-" en las tablas
# Los @app usan jinja2 a través de flask
# se usa directamente desde el HTML con <td>{{ cell|default_dash }}</td>
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

conn_str = (
    f"host={DB_CONFIG['host']} dbname={DB_CONFIG['dbname']} "
    f"user={DB_CONFIG['user']} password={DB_CONFIG['password']} port={DB_CONFIG['port']}"
)


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


def parse_decimal(value):
    if value is None:
        return None
    try:
        v = str(value).replace(",", ".").strip()
        if v == "":
            return None
        d = Decimal(v)
        # descarta NaN o infinitos
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError):
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
# para la entrada de datos hacia la DB
@app.route("/api/nuevo_proyecto", methods=["POST"])
def nuevo_proyecto():
    data = clean_keys(request.get_json())
    logging.info(f"📩 Datos recibidos: {data}")

    # si por alguna razón no se puede parsear la fecha, se coloca la actual
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

                tiempo_estimado = parse_decimal(data.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"))


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
                    tiempo_estimado,
                    #data.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"),
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

#####################################################################################

# para concatenar con la consulta
COLUMNAS_DISPONIBLES = {
    "id_proyecto": "p.id_proyecto",
    "fecha_registro": "p.fecha_registro",
    "email": "u.email",
    "usuario_nombre": "u.nombre",
    "carrera": "carrera.nombre",
    "cargo": "cargo.nombre",
    "sede": "sede.nombre",
    "nombre_proyecto": "p.nombre_proyecto",
    "descripcion": "p.descripcion",
    "tipo": "tipo.nombre",
    "herramienta": "herr.nombre",
    "material": "p.material",
    "cantidad_prototipos": "p.cantidad_prototipos",
    "justificacion": "p.justificacion",
    "fecha_necesidad": "p.fecha_necesidad",
    "tiempo_estimado": "p.tiempo_estimado",
    "otros_comentarios": "p.otros_comentarios",
    "origen": "origen.nombre",
    "estado": "estado.nombre"
}

# ruta para la p'agina web localhost:5000
@app.route("/", methods=["GET", "POST"])
def proyectos():
    try:
        if request.method == "POST":
            seleccionadas = request.form.getlist("columnas")
            # si hay una alg'un par'ametro de b'usqueda, vac'io
            filtros = {col: request.form.get(f"filtro_{col}", "") for col in seleccionadas}
        else:
            # GET inicial con todas las columnas seleccionadas por defecto
            seleccionadas = list(COLUMNAS_DISPONIBLES.keys())
            filtros = {col: "" for col in seleccionadas}

        # se juntan las columnas seleccionadas, separadas por coma
        cols_sql = ", ".join([COLUMNAS_DISPONIBLES[c] for c in seleccionadas])

        # se obtienen par'ametros de filtrado, si los hay (los campos de b'usqueda de coincidencias)
        where_clauses = []
        params = []
        for col, val in filtros.items():
            if val.strip():  # si el input no está vacío. Strip vita espacios innecesarios
                where_clauses.append(f"{COLUMNAS_DISPONIBLES[col]}::text ILIKE %s")
                params.append(f"%{val}%")
        
        # se juntan los filtros para la consulta
        where_sql = " AND ".join(where_clauses)

        if where_sql:
            query = f"""
                SELECT {cols_sql}
                FROM proyecto p
                JOIN usuario u ON p.id_usuario = u.id_usuario
                LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
                LEFT JOIN sede ON p.id_sede = sede.id_sede
                LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
                LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                LEFT JOIN estado ON p.id_estado = estado.id_estado
                LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
                LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
                WHERE {where_sql}
                ORDER BY p.id_proyecto DESC;
            """
        else:
            # consulta cuando no hay búsqueda
            # se unen ambas partes para formar la consulta
            query = f"""
                SELECT {cols_sql}
                FROM proyecto p
                JOIN usuario u ON p.id_usuario = u.id_usuario
                LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
                LEFT JOIN sede ON p.id_sede = sede.id_sede
                LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
                LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                LEFT JOIN estado ON p.id_estado = estado.id_estado
                LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
                LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
                ORDER BY p.id_proyecto DESC;
            """

        '''# consulta cuando no hay búsqueda
        # se unen ambas partes para formar la consulta
        query = f"""
            SELECT {cols_sql}
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
        """'''

        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                proyectos = cur.fetchall()
                print(len(proyectos))
                cur.execute("SELECT COUNT(*) FROM proyecto;")
                print("Total proyectos en DB:", cur.fetchone()[0])


        # sumatorias de columnas numéricas
        # con problemas por ser algunas texto en vez de n'umeros
        sum_row = []
        for i, col in enumerate(seleccionadas):
            valores = []
            for p in proyectos:
                v = p[i]
                # aceptar int, float, Decimal
                if isinstance(v, (int, float, Decimal)):
                    # descartar NaN
                    if isinstance(v, float) and math.isnan(v):
                        continue
                    valores.append(v)
            sum_row.append(sum(valores) if valores else "-")

        '''sum_row = []
        for i, col in enumerate(seleccionadas):
            valores = [p[i] for p in proyectos if isinstance(p[i], (int, float, Decimal))]
            if valores:
                sum_row.append(sum(valores))
            else:
                sum_row.append("-")'''

        return render_template("proyectos.html",
                               columnas_disponibles=COLUMNAS_DISPONIBLES.keys(),
                               columnas=seleccionadas,
                               rows=proyectos,
                               sum_row=sum_row,
                               filtros=filtros)

    except Exception as e:
        logging.error(f"Error en consulta: {e}")
        return f"❌ Error al cargar proyectos: {e}", 500


#######################################################################################
# función auxiliar para obtener datos y sumatorias
def obtener_proyectos(seleccionadas):
    cols_sql = ", ".join([COLUMNAS_DISPONIBLES[c] for c in seleccionadas])
    query = f"""
        SELECT {cols_sql}
        FROM proyecto p
        JOIN usuario u ON p.id_usuario = u.id_usuario
        LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
        LEFT JOIN sede ON p.id_sede = sede.id_sede
        LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
        LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
        LEFT JOIN estado ON p.id_estado = estado.id_estado
        LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
        LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
        ORDER BY p.id_proyecto DESC;
    """


    with psy.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            proyectos = cur.fetchall()

    # fila de sumatorias
    sum_row = []
    for i, col in enumerate(seleccionadas):
        valores = []
        for p in proyectos:
            v = p[i]
            # aceptar int, float, Decimal
            if isinstance(v, (int, float, Decimal)):
                # descartar NaN
                if isinstance(v, float) and math.isnan(v):
                    continue
                valores.append(v)
        sum_row.append(sum(valores) if valores else "-")

    return proyectos, sum_row

@app.route("/exportar_pdf", methods=["GET", "POST"])
def exportar_pdf():
    seleccionadas = request.form.getlist("columnas")
    if not seleccionadas:
        seleccionadas = list(COLUMNAS_DISPONIBLES.keys())

    proyectos, sum_row = obtener_proyectos(seleccionadas)

    # renderizar el mismo template que usás en pantalla
    html_string = render_template("proyectos.html",
                                  columnas_disponibles=COLUMNAS_DISPONIBLES.keys(),
                                  columnas=seleccionadas,
                                  rows=proyectos,
                                  sum_row=sum_row)

    # generar PDF con WeasyPrint
    pdf = HTML(string=html_string).write_pdf(
        stylesheets=[CSS("static/css/bootstrap.min.css"),
                     CSS("static/css/styles-pdf.css")]
    )

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "inline; filename=proyectos.pdf"
    return response



# corre en el puerto 5000 donde se conecta con ngrok

if __name__ == "__main__":
    from pyngrok import ngrok
    import atexit

    if not ngrok.get_tunnels():
        public_url = ngrok.connect(5000)
        print(f"🌐 URL pública: {public_url}")
        atexit.register(ngrok.disconnect, public_url)

    app.run(debug=True, port=5000, use_reloader=False)
