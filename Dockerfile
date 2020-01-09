FROM python:3.7 as build

WORKDIR /app

COPY . /app

RUN pip3 install dephell[full]
RUN dephell deps convert --to=setup.py --from=pyproject.toml

FROM python:3.7-alpine

ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8
# Python, don't write bytecode!
ENV PYTHONDONTWRITEBYTECODE 1

COPY --from=build /app/setup.py .

WORKDIR /app

COPY . /app
RUN rm -f pyproject.toml poetry.lock

RUN apk add --no-cache --virtual .build-deps gcc libc-dev make \
    && pip3 install . \
    && apk del .build-deps
