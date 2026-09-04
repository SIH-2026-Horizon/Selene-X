#!/bin/sh
set -eu

umask 077
mkdir -p /tmp/selene-nginx
cp /usr/share/selene-nginx/selene-web.conf.template /tmp/selene-nginx/default.conf

exec nginx -g 'daemon off;'
