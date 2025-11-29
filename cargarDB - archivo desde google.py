import pandas as panda
import psycopg as psy
from datetime import datetime
import math
from decimal import Decimal, InvalidOperation

# CSV público de google sheets
# Se pueden agregar más archivos separados con coma
links = [ 
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vTilwi5g-OdfObKJmRWFIV-8N0RBaGLX2QiF0bmSpl915RlkIed5Ye-O80Ey5crsg5D7o8bCNtz26sv/pub?gid=1350431005&single=true&output=csv"
]

# configuración de la DB
DB_CONFIG = {
    "host": "localhost",
    "dbname": "labA",
    "user": "postgres",
    "password": "Passw0rd",
    "port": 5432
}

# cambia valores numéricos de fecha a formato TIMESTAMP
def parse_timestamp(value):
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except Exception:
            pass
    return None

# transforma float a int
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
        # descartar NaN o infinitos
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError):
        return None
        

# funci'on para obtener o insertar ID en tablas normalizadas
def get_or_create_id(cur, table, name_value):
    """ Devuelve el id de la tabla normalizada. Inserta si no existe """
    if not name_value or str(name_value).strip() == "":
        return None

    name_value = str(name_value).strip()

    cur.execute(f"SELECT id_{table} FROM {table} WHERE nombre = %s;", (name_value,))
    row = cur.fetchone()

    if row:
        return row[0]

    cur.execute(
        f"INSERT INTO {table} (nombre) VALUES (%s) RETURNING id_{table};",
        (name_value,)
    )
    return cur.fetchone()[0]


# lee hoja 
hoja = panda.read_csv(link)
hoja.columns = [name.strip().replace("\n", " ").replace("\r", "").replace("  ", " ") for name in hoja.columns]

print("Columnas detectadas:")
print(hoja.columns.tolist())
print(f"Total de filas leídas (sin encabezado): {len(hoja)}")
print(hoja.head(3))


conn_str = (
    f"host={DB_CONFIG['host']} dbname={DB_CONFIG['dbname']} "
    f"user={DB_CONFIG['user']} password={DB_CONFIG['password']} port={DB_CONFIG['port']}"
)

with psy.connect(conn_str) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM proyecto;")
        total_antes = cur.fetchone()[0]

        tiene_copiado = "Ya copiado" in hoja.columns
        tiene_estado = "Estado" in hoja.columns

        for i, row in hoja.iterrows():
            email = row.get("Dirección de correo electrónico")
            nombre = row.get("Nombre completo:")

            print(f"Fila {i+1} → email={repr(email)}, nombre={repr(nombre)}")

            if not email or not nombre:
                print(f"⚠ Fila {i+1} sin email o nombre → omitida")
                continue

            # usuario
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
                print(f"🆕 Usuario creado: {nombre} ({email}) id={id_usuario}")

            fecha_registro = parse_timestamp(str(row.get("Marca temporal")))
            fecha_necesidad = parse_timestamp(str(row.get("Fecha de necesidad: (considerar fecha de necesidad teniendo en cuenta una semana de antelación)")))

            tiempo_estimado = parse_decimal(row.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"))


            # por si hay texto en vez de números, aunque de todas formas inserta null
            cantidad_prototipos = row.get("Cantidad de prototipos a fabricar:")
            try:
                cantidad_prototipos = parse_int(cantidad_prototipos)
            except Exception:
                pass

            # estas 2 columnas puede que no vayan en la DB final
            # por ahora están de forma opcional para poder probarlas al completar yo el formulario
            copiado = row.get("Ya copiado") if tiene_copiado else None
            estado_val = row.get("Estado") if tiene_estado else None

            # NUEVO SISTEMA → obtiene IDs de tablas normalizadas (alternativo a lo que se hace con usuario)
            id_cargo = get_or_create_id(cur, "cargo", row.get("Describa su cargo dentro de la Institución y/o Proyecto."))
            id_sede = get_or_create_id(cur, "sede", row.get("En qué sede queda el laboratorio al cual quiere acceder:"))
            id_tipo = get_or_create_id(cur, "tipo", row.get("Seleccione el tipo de solicitud"))
            id_herramienta = get_or_create_id(cur, "herramienta", row.get("Seleccione la herramienta, material o servicio que desea utilizar:"))
            id_origen_material = get_or_create_id(cur, "origen_material", row.get("Origen del material"))
            id_estado = get_or_create_id(cur, "estado", estado_val)
            # 'carrera' por si quieren hacerla con opciones precargadas en un futuro
            id_carrera = get_or_create_id(cur, "carrera", row.get("Describa a qué carrera y/o institución corresponde el proyecto:"))


            # valores ordenados según la nueva tabla
            valores = (
                fecha_registro,
                id_usuario,
                id_carrera,
                id_cargo,
                id_sede,
                row.get("Nombre del proyecto/actividad:"),
                row.get("Breve descripción del proyecto"),
                id_tipo,
                id_herramienta,
                row.get("Material a utilizar"),
                cantidad_prototipos,
                row.get("Vinculación del proyecto con las acciones relacionadas a las herramientas de fabricación digital / materiales / servicios: (justificación de uso)"),
                fecha_necesidad,
                tiempo_estimado,
                #row.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"),
                row.get("Otros comentarios"),
                id_origen_material,
                copiado,
                id_estado
            )

            print(f"\n➡ Insertando proyecto de: {nombre}")

            try:
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
                    ON CONFLICT (id_usuario, nombre_proyecto, fecha_registro, id_sede, descripcion)
                    DO NOTHING;
                """, valores)

                if cur.rowcount == 0:
                    print("⚠ No se insertó (conflicto o duplicado)")
                else:
                    print("✅ Proyecto insertado")

            except Exception as e:
                print(f"❌ Error en fila {i+1}: {e}")
                conn.rollback()
                continue

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM proyecto;")
        total_despues = cur.fetchone()[0]
        insertados = total_despues - total_antes
        print(f"\n✔ Registros insertados: {insertados}")

print("Script ejecutado sin problemas.")
