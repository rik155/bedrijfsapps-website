"""Mount the work orders without changing an existing portal's sessions/hooks."""
from flask import Flask
from . import init_app


def attach_to_portal(portal, config=None):
    if 'janbos_werkbonnen_app' in portal.extensions:
        return portal.extensions['janbos_werkbonnen_app']
    work_orders = Flask('janbos_werkbonnen', static_folder=None)
    work_orders.config.update(SESSION_COOKIE_NAME='janbos_werkbon_session',
                             SESSION_COOKIE_PATH='/werkbonnen')
    if config:
        work_orders.config.update(config)
    init_app(work_orders)
    previous = portal.wsgi_app

    def dispatch(environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == '/werkbonnen' or path.startswith('/werkbonnen/'):
            return work_orders(environ, start_response)
        return previous(environ, start_response)

    portal.wsgi_app = dispatch
    portal.extensions['janbos_werkbonnen_app'] = work_orders
    return work_orders
