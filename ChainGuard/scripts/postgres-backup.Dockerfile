FROM postgres:16-alpine

COPY scripts/backup-postgres.sh /usr/local/bin/backup-postgres
RUN chmod 0755 /usr/local/bin/backup-postgres \
    && printf '0 2 * * * /usr/local/bin/backup-postgres >> /proc/1/fd/1 2>&1\n' > /etc/crontabs/root

CMD ["crond", "-f", "-l", "2"]
