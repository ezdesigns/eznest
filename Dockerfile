# Local eznest page. Artwork stays in the container unless you mount a folder.
FROM python:3.12-slim-bookworm
WORKDIR /opt/eznest
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Installed-build flag. Removing the release marker does not make this a source checkout.
RUN printf '%s\n' '"""Generated when the image is built."""' 'INSTALLED = True' > /opt/eznest/eznest_build.py
RUN printf '%s\n' 'eznest-release' > /opt/eznest/.eznest-release
ENV EZ_NEST_HOST=127.0.0.1
ENV EZ_NEST_PORT=8765
EXPOSE 8765
CMD ["python", "launcher.py", "--no-browser", "--web"]
