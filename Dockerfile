FROM python:3.6-alpine

RUN pip install requests ; pip install kubernetes
COPY metainit.py /

CMD [ "python", "/metainit.py" ]
