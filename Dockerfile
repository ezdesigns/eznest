# Local eznest page. Artwork stays in the container unless you mount a folder.
FROM python:3.12-slim-bookworm
WORKDIR /opt/eznest
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV EZ_NEST_HOST=127.0.0.1
ENV EZ_NEST_PORT=8765
EXPOSE 8765
CMD ["python", "launcher.py", "--no-browser", "--web"]
