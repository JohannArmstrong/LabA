# Imagen base con Python
FROM python:3.11-slim

# Evitar que Python genere archivos .pyc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Crear directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para WeasyPrint
RUN apt-get update && apt-get install -y \
    build-essential \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libffi-dev \
    libjpeg-dev \
    libpng-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt /app/

COPY csv_links.txt /app/csv_links.txt


# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . /app/

# Exponer el puerto Flask
EXPOSE 5000

# Comando de inicio
CMD ["python", "server.py"]
