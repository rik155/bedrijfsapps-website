FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY index.html download.html install.html admin.html login.html expired.html style.css script.js pwa-install.js sw.js bouwflow-icon.svg app.py ./
ENV PORT=80
EXPOSE 80
CMD ["python", "app.py"]
