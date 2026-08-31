FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY index.html download.html style.css script.js app.py ./
COPY windows-client ./windows-client
COPY downloads ./downloads
ENV PORT=80
EXPOSE 80
CMD ["python", "app.py"]
