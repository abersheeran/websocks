FROM python:3.7-alpine

ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
# Python, don't write bytecode!
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN apk add --no-cache --virtual .build-deps gcc libc-dev make \
    && pip3 install -r requirements.txt \
    && apk del .build-deps

COPY ./websocks/ /app/websocks/
