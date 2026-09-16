FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY index.html download.html install.html admin.html login.html expired.html style.css responsive.css script.js pwa-install.js sw.js app.webmanifest bouwflow-icon.svg janbos-logo.jpg janbos-logo.png icon-192.png icon-512.png app.py ./
ENV PORT=80
EXPOSE 80
CMD ["python", "app.py"]
