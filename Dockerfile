FROM alpine:3.3

RUN \
    apk --no-cache add py-pip py-dateutil && \
    pip install --upgrade pip && \
    pip install elasticsearch==2.4.0 pytz

ENV ELASTICSERVER 192.168.0.1
ENV ELASTICINDEX example
ENV MAILSERVER 192.168.0.2
ENV MAILPORT 993
ENV MAILUSER root
ENV MAILPASS root
ENV SLEEPTIMER 60
ENV DEBUGMODE 0

COPY ingressMail2Elastic.py /

CMD ["/ingressMail2Elastic.py"]
