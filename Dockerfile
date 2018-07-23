FROM python:3.6-alpine

RUN pip install requests
COPY metainit.py /

CMD [ "python", "/metainit.py" ]
