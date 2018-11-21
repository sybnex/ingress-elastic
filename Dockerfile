FROM alpine

RUN \
    apk --no-cache add py-pip py-dateutil && \
    pip install --upgrade pip && \
    pip install elasticsearch==5.5.3 pytz

ENV ELASTICSERVER="192.168.0.1" \
    ELASTICINDEX="example" \
    MAILSERVER="192.168.0.2" \
    MAILPORT="993" \
    MAILUSER="root" \
    MAILPASS="root" \
    SLEEPTIMER="60" \
    DEBUGMODE="0"

COPY ingressMail2Elastic.py /
CMD ["/ingressMail2Elastic.py"]
