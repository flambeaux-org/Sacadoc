import multiprocessing

bind = "0.0.0.0:8012"
pidfile = "../gunicorn.pid"
wsgi_app = "noethysweb.wsgi"
preload_app = False  # Don't preload to allow SIGHUP to reload code
limit_request_line = 8190
workers = multiprocessing.cpu_count() * 2 + 1

forwarded_allow_ips = "*"

logger_class = "glogging.Logger"
accesslog = "/var/log/sacadoc/gunicorn_access.log"
access_log_format = '{"datetime":"%({request_start}c)s","server":"gunicorn","ip":"%({x-real-ip}i)s","vhost":"sacadoc.flambeaux.org","c_host":"%({host}i)s","method":"%(m)s","uri":"%(U)s","qs":"%(q)s","status":"%(s)s","timetakenms":"%(M)s","size":"%(B)s","ua":"%(a)s","ref":"%(f)s","outct":"%({content-type}o)s","user":"%({x-user}o)s","uid":"%({x-uid}i)s","country":"%({x-country-code}i)s"}'

errorlog = "/var/log/sacadoc/gunicorn_error.log"

timeout = 3600 # Needed for batch mail sending which is done sync with a request for now
