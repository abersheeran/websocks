FROM python:3.7 as build

WORKDIR /app

COPY . /app

RUN pip3 install poetry2setup
RUN poetry2setup > setup.py

FROM python:3.7-alpine

ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
# Python, don't write bytecode!
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /app

COPY . /app
RUN rm -f pyproject.toml poetry.lock

COPY --from=build /app/setup.py .

RUN apk add --no-cache --virtual .build-deps gcc libc-dev make libffi-dev \
    && pip3 install . \
    && apk del .build-deps

ENTRYPOINT [ "websocks" ]
