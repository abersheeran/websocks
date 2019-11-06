FROM python:3.7-alpine

ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
# Python, don't write bytecode!
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /app

COPY . /app

RUN apk add --no-cache --virtual .build-deps gcc libc-dev make \
    && python3 setup.py install \
    && apk del .build-deps
